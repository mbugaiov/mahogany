#!/usr/bin/env bash
# Compare prod landing mahogany-build meta (or BUILD_ID file) to local HEAD.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${DO_DEPLOY_HOST:-64.225.115.88}"
USER="${DO_DEPLOY_USER:-deploy}"
KEY="${DO_SSH_KEY_FILE:-$ROOT/../pantheon/.secrets/do_deploy_ed25519}"
KH="${DO_KNOWN_HOSTS_FILE:-$ROOT/../pantheon/.secrets/known_hosts}"
PROD_URL="${PROD_URL:-https://mahogany-calgary.com}"
REMOTE_LANDING="${PROD_LANDING_PATH:-/var/www/mahogany}"
SHA="$(cd "$ROOT" && git rev-parse HEAD)"

echo "HEAD=$SHA"
echo "GET $PROD_URL/"
BODY=$(curl -fsSL --max-time 20 "$PROD_URL/" || true)
if echo "$BODY" | grep -q "mahogany-build\" content=\"$SHA\""; then
  echo "HTML meta MATCH"
  exit 0
fi

if [[ -f "$KEY" ]]; then
  chmod 600 "$KEY"
  REMOTE=$(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile="$KH" \
    "${USER}@${HOST}" "cat ${REMOTE_LANDING}/BUILD_ID 2>/dev/null || true")
  echo "REMOTE_BUILD_ID=$REMOTE"
  [[ "$REMOTE" == "$SHA" ]] && echo "BUILD_ID file MATCH" && exit 0
fi

echo "MISMATCH" >&2
exit 1
