#!/usr/bin/env bash
# Write BUILD_ID and optionally sync landing for local/STG smoke.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SHA="${1:-$(git rev-parse --short HEAD 2>/dev/null || echo dev)}"
echo "$SHA" > BUILD_ID
export MAHOGANY_BUILD_ID="$SHA"
echo "BUILD_ID=$SHA"
