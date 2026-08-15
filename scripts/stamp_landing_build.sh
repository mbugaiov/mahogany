#!/usr/bin/env bash
# Stamp landing/index.html with BUILD_ID (meta name="mahogany-build").
# Usage: BUILD_ID=<sha> bash scripts/stamp_landing_build.sh [path/to/index.html]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${1:-$ROOT/landing/index.html}"
BUILD_ID="${BUILD_ID:-$(cd "$ROOT" && git rev-parse HEAD)}"
if [[ ! -f "$FILE" ]]; then
  echo "Missing landing file: $FILE" >&2
  exit 1
fi
# Prefer replacing existing meta; otherwise insert after charset meta.
if grep -q 'name="mahogany-build"' "$FILE"; then
  sed -i.bak -E "s/(name=\"mahogany-build\" content=\")[^\"]*(\")/\1${BUILD_ID}\2/" "$FILE"
  rm -f "${FILE}.bak"
else
  sed -i.bak -E "s|(<meta charset=\"UTF-8\" />)|\\1\\n  <meta name=\"mahogany-build\" content=\"${BUILD_ID}\" />|" "$FILE"
  rm -f "${FILE}.bak"
fi
echo "Stamped mahogany-build=${BUILD_ID} → $FILE"
