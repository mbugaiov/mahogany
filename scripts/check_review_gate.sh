#!/usr/bin/env bash
# Fail when Themis review output has blocking issues.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  exec "$ROOT/.venv/bin/python" scripts/check_review_gate.py "${1:-review.md}"
fi
exec python3 scripts/check_review_gate.py "${1:-review.md}"
