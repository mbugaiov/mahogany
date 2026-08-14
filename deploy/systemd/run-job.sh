#!/usr/bin/env bash
# Drop-in oneshot for mahogany-job@.service — arg = CLI job name
set -euo pipefail
JOB="${1:?job name}"
exec /opt/mahogany/.venv/bin/mahogany "$JOB"
