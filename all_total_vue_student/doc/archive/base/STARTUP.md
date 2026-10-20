> BASE 장애 진단 프로젝트의 과거 기록입니다. 아래 실행 명령은 당시 기준이며, 보존 코드의 현재 실행 방법은 [보관 안내](../../../archive/README.md)를 확인하세요.

# 서버 실행·응답 지연 문제 해결

현재 작업 경로: `/Users/hyeongjunhan/skala_mini_3_G104_hhj/all_total_vue_student`

## 확인한 원인

- 이전 스크립트는 서버 실행만 하고 uvicorn 로그 레벨도 warning이라, 정상 준비 상태에서도 출력이 거의 없었습니다. 재현 결과 Ollama는 약 2.9초, OpenAI는 약 2.3초에 /health가 열렸으나 터미널 출력은 비어 있었습니다.
- 서버 명령은 실행 중 터미널을 계속 사용합니다. 프롬프트가 돌아오지 않는 것 자체는 오류가 아닙니다.
- 두 백엔드의 기본 포트는 모두 8100입니다. 동시에 실행하면 충돌합니다. 평소에는 하나만 사용하고 전환 시 기존 터미널에서 Ctrl+C를 누릅니다.
- 이전 Ollama 어댑터는 Qwen3의 thinking을 명시적으로 끄지 않고 생성 길이 제한도 두지 않았습니다. 서버 시작과 별개로 첫 모델 로딩/추론/답변 검증에 시간이 걸릴 수 있었습니다.
- OpenAI 어댑터는 async 함수 안에서 동기 HTTP를 실행해, 답변 생성 동안 이벤트 루프와 /health가 멈출 수 있었습니다.

## 권장 실행

프로젝트 폴더에서 **하나만** 선택:

```bash
cd /Users/hyeongjunhan/skala_mini_3_G104_hhj/all_total_vue_student
bash sh/run_agent_openai.sh
# 또는: bash sh/run_agent_ollma.sh
# 또는: bash sh/run_agent_fake.sh
```

터미널에 `[준비 완료] http://127.0.0.1:8100/health`가 나오면 정상입니다. 이 터미널은 그대로 둡니다.

새 터미널:

```bash
cd /Users/hyeongjunhan/skala_mini_3_G104_hhj/all_total_vue_student
bash sh/run_frontend.sh
```

브라우저: http://localhost:8600
종료: 서버 실행 터미널에서 Ctrl+C.

기존 `ollma` 이름과 올바르게 쓴 `run_agent_ollama.sh` 모두 지원합니다.
통합 명령도 같습니다: `bash sh/run_agent.sh --backend openai`.

## 연결만 진단하기

```bash
bash sh/run_agent_ollma.sh --check
bash sh/run_agent_openai.sh --check
```

이 명령은 검사 후 종료하고 서버를 시작하지 않습니다. OpenAI는 모델 정보 GET만 호출하며 생성 API를 호출하지 않습니다. 모델 정보 조회 성공이 생성 API 잔액/한도까지 보장하지는 않습니다. 검사 출력에 API 키나 서버가 반환한 원문 오류 본문을 표시하지 않습니다.

Ollama `--check`는 daemon을 자동 시작하지 않습니다. 일반 실행은 로컬 Ollama가 꺼져 있고 CLI가 설치되어 있으면 시작을 시도합니다. 모델이 없으면 필요한 `ollama pull ...` 명령만 안내하며 자동 다운로드하지 않습니다. 이번 실행기가 시작한 daemon만 종료 시 정리하며, 기존 Ollama 서비스는 유지합니다.

## 포트 충돌

```bash
lsof -nP -iTCP:8100 -sTCP:LISTEN
```

기존 실행 터미널에서 Ctrl+C로 종료한 뒤 다른 백엔드를 실행하세요. 실행기는 다른 프로세스를 강제로 종료하지 않습니다.
동시 비교가 필요한 경우에만:

```bash
PORT=8101 bash sh/run_agent_openai.sh
# 해당 서버를 바라볼 프런트엔드
BACKEND_URL=http://127.0.0.1:8101 FRONTEND_PORT=8601 bash sh/run_frontend.sh
```

별도 포트 사용 시 브라우저는 http://localhost:8601 입니다.

## 변경 파일

- `sh/run_agent.sh`: 가상환경 검사 및 통합 실행기 호출.
- `sh/run_agent_{ollma,ollama,openai,fake}.sh`: 백엔드 선택용 호환 스크립트. 추가 인자 전달.
- `agent/launch.py`: 단계별 상태, 의존성/모델/키/포트 진단, 제한 시간 내 준비 확인, 정상 종료와 자식 프로세스 정리.
- `agent/runtime_llm.py`: 개선 모드 전용 Ollama thinking/output/time 제한, OpenAI chat/write의 동기 HTTP를 별도 스레드로 이동.
- `server.py`: MCP 연결 및 구성 로그, MCP 준비 제한, POST/SSE 요청 제한, SSE 접수·5초 heartbeat.
- `web_chat.html`: 접수/경과 시간 표시. 미검증 AI 초안은 계속 숨김.
- `eval/run_eval.py`: baseline은 원본 어댑터를 명시적으로 선택. 과거 비교 조건 보존.
- `tests/test_startup.py`, `tests/test_api.py`: 포트 충돌, 키 비노출, 설치 모델 검사, 모델 옵션, 이벤트 루프 응답성, 요청 제한 회귀 테스트.

원본 `agent/ollama_llm.py`, `agent/openai_llm.py`, `agent/baseline_graph.py`는 변경하지 않았습니다.

## 조정 가능한 설정

`.env` 또는 명령 앞 환경 변수로 지정합니다. 셸 환경 변수가 `.env`보다 우선합니다.

| 설정 | 기본값 | 의미 |
|---|---|---|
| OLLAMA_THINK | false | 개선 모드에서 thinking 비활성. true로 바꾸면 지연이 증가할 수 있음 |
| OLLAMA_NUM_PREDICT | 768 | 최대 생성 길이. 너무 작으면 답변/JSON이 잘릴 수 있음 |
| OLLAMA_BASE_URL | http://127.0.0.1:11434 | 개선 모드의 Ollama 주소 |
| LLM_TIMEOUT_SECONDS | 90 | 개선 모드 단일 모델 응답 대기 제한 |
| REQUEST_TIMEOUT_SECONDS | 180 | POST/SSE 전체 요청 제한 |
| STARTUP_TIMEOUT_SECONDS | 30 | 실행기의 /health 준비 확인 제한 |
| MCP_STARTUP_TIMEOUT_SECONDS | 20 | MCP 시작 제한 |
| AUTO_START_OLLAMA | 1 | 일반 실행 중 로컬 Ollama 자동 시작 허용 |
| LOG_LEVEL | info | 서버 로그 수준 |

모델 이름은 기존 qwen3:0.6b / qwen3:8b, gpt-4o-mini / gpt-4o를 유지했습니다.
출력 제한·thinking 비활성은 긴 답변의 완성도와 추론 품질에 영향을 줄 수 있습니다. 기존 성능 보고서는 이전 실행 조건이며 새 기본 설정의 품질을 보장하는 결과가 아닙니다.
OpenAI 원본 동기 요청은 별도 스레드에서 실행합니다. 대기 취소가 이미 시작한 원격 생성/청구를 중단한다고 보장하지 않습니다.

모델 정보 조회가 정책상 금지된 환경에서는 `--skip-backend-check`로 사전 연결 검사를 생략할 수 있습니다. 실제 요청 성공 여부는 별도 확인해야 합니다.

## 재검증

```bash
.venv/bin/python -m pytest -q
bash sh/run_agent_ollma.sh --check
bash sh/run_agent_openai.sh --check
curl -s http://127.0.0.1:8100/health
```

이번 머신의 실제 진단 요청 1건씩:

| 백엔드 | 서버 준비 | CPU 진단 요청 | 검증 | 근거 |
|---|---:|---:|---|---:|
| Ollama | 3.07초 | 25.72초 | 통과 | 3건 |
| OpenAI | 5.33초 | 6.07초 | 통과 | 3건 |

동일 입력 `payments-service CPU 급증 원인 진단해줘`, 고정 시뮬레이션 데이터, 로컬 tracing 비활성 상태에서 측정했습니다. 캐시/모델 로딩/네트워크 상태가 달라지는 단일 smoke 측정이며 통제된 성능 벤치마크가 아닙니다. 상세 결과는 `eval/results/startup-smoke.json`.

- [Ollama thinking 공식 문서](https://docs.ollama.com/capabilities/thinking)
- [OpenAI 모델 정보 조회 공식 문서](https://developers.openai.com/api/reference/resources/models/methods/retrieve)
- [OpenAI 오류 코드 공식 문서](https://developers.openai.com/api/docs/guides/error-codes)
