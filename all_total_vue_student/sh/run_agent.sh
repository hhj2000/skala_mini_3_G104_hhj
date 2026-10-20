#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "Python 가상환경이 없습니다. 먼저 bash sh/setup_venv.sh를 실행하세요."
  exit 1
fi
exec .venv/bin/python -u -m agent.launch "$@"
