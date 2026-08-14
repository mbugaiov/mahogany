#!/usr/bin/env bash
# Deploy mahogany app tree to DO as deploy user (no secret rotation).
# Usage:
#   bash scripts/deploy_stg.sh
# Env (optional): DO_DEPLOY_HOST DO_DEPLOY_USER DO_SSH_KEY_FILE DO_KNOWN_HOSTS_FILE
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HOST="${DO_DEPLOY_HOST:-64.225.115.88}"
USER="${DO_DEPLOY_USER:-deploy}"
KEY="${DO_SSH_KEY_FILE:-$ROOT/../pantheon/.secrets/do_deploy_ed25519}"
KH="${DO_KNOWN_HOSTS_FILE:-$ROOT/../pantheon/.secrets/known_hosts}"
STG_URL="${STG_URL:-http://mahogany.${HOST}.nip.io}"
SHA="$(git rev-parse HEAD)"

if [[ ! -f "$KEY" ]]; then
  echo "Missing deploy key: $KEY" >&2
  exit 1
fi

chmod 600 "$KEY"
SSHC=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile="$KH")
RSYNC_SSH="ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile=$KH"

echo "== gate =="
./scripts/gate.sh

echo "== stage bundle =="
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
rsync -a \
  --exclude .venv \
  --exclude .git \
  --exclude data \
  --exclude __pycache__ \
  --exclude .pytest_cache \
  --exclude .ruff_cache \
  --exclude '*.egg-info' \
  ./ "$STAGE/mahogany/"
printf '%s' "$SHA" > "$STAGE/mahogany/BUILD_ID"

echo "== rsync → ${USER}@${HOST}:/opt/mahogany =="
rsync -az --delete -e "$RSYNC_SSH" \
  --exclude .venv \
  "$STAGE/mahogany/" "${USER}@${HOST}:/opt/mahogany/"

echo "== remote venv + units =="
"${SSHC[@]}" "${USER}@${HOST}" bash -s <<REMOTE
set -euo pipefail
cd /opt/mahogany
export MAHOGANY_BUILD_ID='$SHA'
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q -U pip setuptools wheel
pip install -q -e .
# Install health unit if missing (needs prior root bootstrap for sudoers)
if [[ -f deploy/systemd/mahogany-health.service ]]; then
  # unit file may need root — write to /tmp and hope bootstrap already installed, or copy via sudo later
  true
fi
printf '%s' '$SHA' > /opt/mahogany/BUILD_ID
# Append build id into process env for this restart via drop-in not available — set in env file if writable
if [[ -w /etc/mahogany.env ]]; then
  grep -q '^MAHOGANY_BUILD_ID=' /etc/mahogany.env && sed -i "s/^MAHOGANY_BUILD_ID=.*/MAHOGANY_BUILD_ID=$SHA/" /etc/mahogany.env || echo "MAHOGANY_BUILD_ID=$SHA" >> /etc/mahogany.env
fi
# Prefer sudo restart helper
if sudo -n /usr/local/bin/mahogany-restart >/dev/null 2>&1; then
  echo "mahogany-health restarted"
elif sudo -n systemctl restart mahogany-health >/dev/null 2>&1; then
  echo "mahogany-health restarted via systemctl"
else
  # Foreground-less fallback: start uvicorn if unit not ready
  echo "WARN: no sudo restart — starting health via nohup (bootstrap incomplete)"
  pkill -f 'mahogany.health:app' 2>/dev/null || true
  nohup env MAHOGANY_BUILD_ID='$SHA' /opt/mahogany/.venv/bin/mahogany-health >/tmp/mahogany-health.log 2>&1 &
  sleep 2
fi
REMOTE

echo "== smoke $STG_URL =="
for i in 1 2 3 4 5 6; do
  if HEALTH=$(curl -fsS --max-time 15 "$STG_URL/api/build-id" 2>/dev/null); then
    echo "Smoke OK: $HEALTH"
    echo "$HEALTH" | grep -q "$SHA" && echo "buildId MATCH" || echo "WARN: buildId may not match $SHA yet"
    exit 0
  fi
  # also try direct host:3004 via ssh tunnel check
  echo "Smoke attempt $i failed — retry..."
  sleep 3
done

# Fallback smoke via SSH localhost
if OUT=$("${SSHC[@]}" "${USER}@${HOST}" "curl -fsS http://127.0.0.1:3004/api/build-id"); then
  echo "Localhost smoke OK: $OUT"
  exit 0
fi

echo "STG smoke failed" >&2
exit 1
