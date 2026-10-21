"""통합 서비스 진입점: 기본 Kharakteres, SERVICE_MODE=incident는 보존된 BASE.

공용 HTTPS URL은 호스트 ngrok에서 발급하며 화면/API/SSE는 같은 출처를 사용한다.
호스트 포트와 컨테이너 포트를 구분한다(doc/NGROK_SHARING.md).
주문 서비스의 정량 평가는 eval/kharakteres_benchmark.py를 사용한다.
장애 진단 BASE의 과거 평가는 서로 다른 도메인의 현재 성능 근거로 사용하지 않는다.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
from agent.model_factory import _build_llms  # compatibility for existing evaluation scripts

if os.getenv("SERVICE_MODE", "spells") == "incident":
    from incident_server import app
else:
    from kharakteres.api import app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8100")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
