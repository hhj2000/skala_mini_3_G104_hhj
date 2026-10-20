#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -c 'from agent.retrieval import RunbookIndex; print(RunbookIndex().build())'
