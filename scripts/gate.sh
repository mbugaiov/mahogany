#!/usr/bin/env bash
# Local MR gate — lint + unit tests (Pantheon-equivalent for Python).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  if command -v python3.12 >/dev/null 2>&1; then PY=python3.12
  elif command -v python3.11 >/dev/null 2>&1; then PY=python3.11
  else PY=python3
  fi
fi
if [[ ! -d .venv ]]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q -U pip setuptools wheel
pip install -q -e ".[dev]"

echo "== ruff =="
ruff check src tests

echo "== pytest =="
pytest -q

echo "gate OK"

echo "== themis review wiring =="
grep -q 'build_review_prompt.sh' .github/workflows/pr.yml
grep -q 'repository: mbugaiov/themis-agent' .github/workflows/pr.yml
echo "themis review wiring ok"
