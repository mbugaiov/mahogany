#!/usr/bin/env bash
# Ensure mbugaiov/themis-agent is at .themis-agent (follow-up + isolation scripts).
# Always derives ROOT from this script's location (ignores env ROOT=/ etc.).
# Default pin from scripts/THEMIS_AGENT_REF (also mirrored in workflow ref: lines; smoke checks drift).
# Skips network when already ready + at pin.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${THEMIS_AGENT_PATH:-$ROOT/.themis-agent}"
REPO_URL="${THEMIS_AGENT_GIT_URL:-https://github.com/mbugaiov/themis-agent.git}"
if [[ -z "${THEMIS_AGENT_REF:-}" && -f "$ROOT/scripts/THEMIS_AGENT_REF" ]]; then
  THEMIS_AGENT_REF="$(tr -d '[:space:]' < "$ROOT/scripts/THEMIS_AGENT_REF")"
fi
REF="${THEMIS_AGENT_REF:-3250607f3700d0c2cb73f226435e4b69afd2e118}"

ready() {
  [[ -f "$DEST/scripts/check_review_followups_disposed.sh" \
    && -f "$DEST/scripts/review_followups.py" \
    && -f "$DEST/scripts/ci_isolation.sh" ]]
}

at_pin() {
  local head
  head="$(git -C "$DEST" rev-parse HEAD 2>/dev/null || true)"
  [[ -n "$head" ]] || return 1
  [[ "$head" == "$REF" || "$head" == "$REF"* ]]
}

checkout_pin() {
  git -C "$DEST" fetch --depth 1 origin "$REF"
  git -C "$DEST" checkout --detach --force FETCH_HEAD
}

if [[ -d "$DEST/.git" ]]; then
  if ready && at_pin; then
    :
  elif checkout_pin && ready && at_pin; then
    :
  else
    echo "ensure_themis_agent: refresh to ${REF:0:12} failed — recloning" >&2
    rm -rf "$DEST"
  fi
fi

if ! ready || ! at_pin; then
  rm -rf "$DEST"
  if ! git clone --depth 1 "$REPO_URL" "$DEST"; then
    echo "ensure_themis_agent: git clone failed: $REPO_URL" >&2
    exit 1
  fi
  if ! checkout_pin; then
    echo "ensure_themis_agent: checkout pin $REF failed" >&2
    exit 1
  fi
fi

if ! ready || ! at_pin; then
  echo "ensure_themis_agent: follow-up/isolation scripts missing or not at pin under $DEST" >&2
  exit 1
fi
echo "$DEST"
