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
# Themis review job floats themis-agent main (shared review-rules); isolation/ensure stay pinned.

echo "== themis review wiring =="
grep -q 'build_review_prompt.sh' .github/workflows/pr.yml
grep -q 'repository: mbugaiov/themis-agent' .github/workflows/pr.yml
echo "themis review wiring ok"

echo "== themis build_review_prompt selftest =="
# Offline local runs may skip the builder when git clone is unavailable.
# CI (GITHUB_ACTIONS=true) must never skip — missing checkout/builder exits 1.
# Stale .themis-agent/ is OK locally (pinned via ensure); CI review job floats themis main.
print_themis_tip() {
  local root="$1"
  local sha="unknown"
  if [[ -d "$root/.git" ]]; then
    sha="$(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  fi
  echo "themis builder tip: $root @ ${sha}"
}
THEMIS_ROOT=""
THEMIS_TMP=""
if [[ -x .themis-agent/scripts/build_review_prompt.sh ]]; then
  THEMIS_ROOT=.themis-agent
else
  THEMIS_TMP=$(mktemp -d)
  if git clone --depth 1 https://github.com/mbugaiov/themis-agent.git "$THEMIS_TMP/themis" >/dev/null 2>&1; then
    THEMIS_ROOT="$THEMIS_TMP/themis"
  fi
fi
if [[ -n "$THEMIS_ROOT" ]]; then
  print_themis_tip "$THEMIS_ROOT"
  OUT=$(bash "$THEMIS_ROOT/scripts/build_review_prompt.sh" --pr 1 --base origin/main --label mahogany-selftest --local-rule .cursor/rules/code-review.mdc --themis-root "$THEMIS_ROOT")
  echo "$OUT" | grep -q review-rules/10-tests-must-have
else
  if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
    echo "themis builder missing in CI — fail-closed" >&2
    exit 1
  fi
  echo "themis builder skipped (offline local) — review wiring grep already passed"
fi
rm -rf "${THEMIS_TMP:-}"
