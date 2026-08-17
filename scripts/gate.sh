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

echo "== themis build_review_prompt selftest =="
THEMIS_TMP=$(mktemp -d)
git clone --depth 1 https://github.com/mbugaiov/themis-agent.git "$THEMIS_TMP/themis" >/dev/null 2>&1
OUT=$(bash "$THEMIS_TMP/themis/scripts/build_review_prompt.sh" --pr 1 --base origin/main --label mahogany-selftest --local-rule .cursor/rules/code-review.mdc --themis-root "$THEMIS_TMP/themis")
echo "$OUT" | grep -q review-rules/10-tests-must-have
rm -rf "$THEMIS_TMP"
