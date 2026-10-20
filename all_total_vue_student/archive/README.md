# BASE 프로젝트 보관 안내

Kharakteres는 `bash sh/run_kharakteres.sh openai` 하나로 화면과 API를 제공합니다. 이 폴더는 현재 서비스 실행에서 사용하지 않는 과거 브라우저 UI와 프록시만 보관합니다.

## BASE가 화면 서버를 따로 실행했던 이유

기존 `server.py`는 진단 API(`/chat`, `/chat/stream`, `/health`)를 제공했습니다. 이 API 서버를 수정하지 않고 브라우저 채팅 화면을 덧붙이기 위해 `web_demo_server.py`가 HTML을 제공하고 요청을 API 서버로 중계했습니다. 브라우저가 같은 출처로 요청하도록 해서 CORS 설정 없이 POST와 SSE를 이용하려는 데모 구성입니다. 포트 분리가 비동기 처리나 스트리밍의 필수 조건은 아닙니다.

## 보존 코드 실행 (프로젝트 루트 기준)

```bash
# 터미널 1: Base 진단 API
SERVICE_MODE=incident bash sh/run_agent.sh --backend fake
# 터미널 2: 과거 진단 화면 (선택)
bash archive/base_ui/run_frontend.sh
```

BASE 화면은 http://localhost:8600/ 입니다. 실제 모델은 첫 번째 명령의 `fake`를 `openai` 또는 `ollama`로 바꿉니다. 이 선택 실행은 Kharakteres 실행 절차와 별개입니다.

- `base_ui/incident_web_chat.html`: 이전 진단 채팅 화면
- `base_ui/web_demo_server.py`: 진단 API 전용 프록시. Kharakteres API 프록시는 제거
- `base_ui/run_frontend.sh`: 보존한 BASE 화면 전용 실행기
- `base_ui/browser_smoke.py`: 이전 화면 테스트 (`.venv/bin/python archive/base_ui/browser_smoke.py`)
- [기존 문서·캡처](../doc/archive/base/README.md)
- [기존 비교 실험 설명](../doc/archive/base/EVALUATION.md)

기존 BASE API·그래프·MCP 도구·테스트·평가 데이터는 비교 재현을 위해 원래 경로에 유지했습니다. 공용 LLM 어댑터도 현재 서비스가 재사용하므로 삭제하지 않았습니다. 문서 내 과거 실행 명령은 역사적 기록이며 현재 명령은 이 안내를 따릅니다.

## BASE 전용 설정

현재 `.env.example`은 Kharakteres용입니다. BASE 실험에서 필요한 경우 `.env` 또는 실행 환경에 다음을 추가합니다.

```dotenv
MONITORING_FIXED=0
MCP_DEMO_FLAKY=0
CONTEXT_SUMMARY_AFTER_MESSAGES=20
RAG_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RAG_MIN_SCORE=0.30
MCP_STARTUP_TIMEOUT_SECONDS=20
REQUEST_TIMEOUT_SECONDS=180
```
