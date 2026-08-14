#!/usr/bin/env bash
# Compare STG /api/build-id to local HEAD.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${DO_DEPLOY_HOST:-64.225.115.88}"
STG_URL="${STG_URL:-http://mahogany.${HOST}.nip.io}"
SHA="$(cd "$ROOT" && git rev-parse HEAD)"
echo "HEAD=$SHA"
echo "GET $STG_URL/api/build-id"
BODY=$(curl -fsS --max-time 20 "$STG_URL/api/build-id")
echo "$BODY"
echo "$BODY" | grep -q "$SHA"
echo "MATCH"
