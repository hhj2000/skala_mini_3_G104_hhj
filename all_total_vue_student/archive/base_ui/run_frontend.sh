#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8100}"
export FRONTEND_PORT="${FRONTEND_PORT:-8600}"
if ! curl -fsS --max-time 3 "$BACKEND_URL/health" >/dev/null; then
    echo "백엔드가 응답하지 않습니다: $BACKEND_URL"
    echo "다른 터미널에서 SERVICE_MODE=incident bash sh/run_agent.sh --backend fake를 먼저 실행하세요."
    exit 1
fi
echo "브라우저에서 http://localhost:$FRONTEND_PORT 에 접속하세요."
exec .venv/bin/python archive/base_ui/web_demo_server.py
