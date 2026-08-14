#!/usr/bin/env bash
# Pantheon thin wrapper → themis-agent follow-up scripts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export THEMIS_REVIEW_MARKER="${THEMIS_REVIEW_MARKER:-<!-- mahogany-themis-review -->}"
export THEMIS_FOLLOWUP_DISPOSE_MARKER="${THEMIS_FOLLOWUP_DISPOSE_MARKER:-<!-- mahogany-review-followups-disposed -->}"
export THEMIS_FOLLOWUP_SECTIONS="${THEMIS_FOLLOWUP_SECTIONS:-Risks,Nits}"
export THEMIS_FOLLOWUP_REPO="${THEMIS_FOLLOWUP_REPO:-${GITHUB_REPOSITORY:-$(cd "$ROOT" && gh repo view --json nameWithOwner -q .nameWithOwner)}}"
THEMIS="$(bash "$ROOT/scripts/ensure_themis_agent.sh")"
exec bash "$THEMIS/scripts/file_review_followups.sh" "$@"
