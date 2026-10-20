#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
KHARAKTERES_BACKEND="${1:-openai}"
if [ "$#" -gt 0 ]; then shift; fi
export SERVICE_MODE=spells
export LANGCHAIN_PROJECT="${LANGCHAIN_PROJECT:-kharakteres-${KHARAKTERES_BACKEND}}"
exec bash sh/run_agent.sh --backend "$KHARAKTERES_BACKEND" "$@"
