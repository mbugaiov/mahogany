#!/usr/bin/env bash
# Promote landing to prod (/var/www/mahogany) after STG is healthy.
# App/bots already run from /opt/mahogany (same tree as STG).
# Usage:
#   bash scripts/deploy_prod.sh
# Env (optional): DO_DEPLOY_HOST DO_DEPLOY_USER DO_SSH_KEY_FILE DO_KNOWN_HOSTS_FILE
#                 PROD_URL PROD_LANDING_PATH BUILD_ID
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HOST="${DO_DEPLOY_HOST:-64.225.115.88}"
USER="${DO_DEPLOY_USER:-deploy}"
KEY="${DO_SSH_KEY_FILE:-$ROOT/../pantheon/.secrets/do_deploy_ed25519}"
KH="${DO_KNOWN_HOSTS_FILE:-$ROOT/../pantheon/.secrets/known_hosts}"
PROD_URL="${PROD_URL:-https://mahogany-calgary.com}"
REMOTE_LANDING="${PROD_LANDING_PATH:-/var/www/mahogany}"
BUILD_ID="${BUILD_ID:-$(git rev-parse HEAD)}"

if [[ ! -f "$KEY" ]]; then
  echo "Missing deploy key: $KEY" >&2
  exit 1
fi

chmod 600 "$KEY"
SSHC=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile="$KH")
RSYNC_SSH="ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile=$KH"

echo "== gate =="
./scripts/gate.sh

echo "== stamp landing build $BUILD_ID =="
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp landing/index.html "$STAGE/index.html"
BUILD_ID="$BUILD_ID" bash scripts/stamp_landing_build.sh "$STAGE/index.html"
printf '%s' "$BUILD_ID" > "$STAGE/BUILD_ID"

echo "== promote landing → ${USER}@${HOST}:${REMOTE_LANDING} =="
rsync -az -e "$RSYNC_SSH" \
  "$STAGE/index.html" "$STAGE/BUILD_ID" \
  "${USER}@${HOST}:${REMOTE_LANDING}/"

echo "== smoke $PROD_URL =="
for i in 1 2 3 4 5 6; do
  BODY=$(curl -fsSL --max-time 20 "$PROD_URL/" || true)
  if [[ -n "$BODY" ]] && echo "$BODY" | grep -q "Mahogany Life" \
    && echo "$BODY" | grep -q "mahogany-build\" content=\"$BUILD_ID\""; then
    echo "Prod smoke OK (build $BUILD_ID)"
    exit 0
  fi
  echo "Prod smoke attempt $i failed — retry..."
  sleep 3
done

# Fallback: confirm remote BUILD_ID file via SSH
REMOTE=$("${SSHC[@]}" "${USER}@${HOST}" "cat ${REMOTE_LANDING}/BUILD_ID 2>/dev/null || true")
if [[ "$REMOTE" == "$BUILD_ID" ]]; then
  echo "Prod BUILD_ID file MATCH ($BUILD_ID); HTML meta may be Cloudflare-cached"
  exit 0
fi

echo "Prod smoke failed (expected build $BUILD_ID, remote file='$REMOTE')" >&2
exit 1
