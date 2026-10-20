# Kharakteres · 나만의 마법 주문 웹 서비스

고대 그리스어 χαρακτῆρες에서 이름을 가져온 **다국어 마법 주문 생성·관리 및 설정 충돌 검토 AI 웹 서비스**입니다. 현대어·고전어 주문을 만들고, 창작 언어의 주문도 직접 정의해 계정별 사전에 저장할 수 있습니다. 로컬과 Docker에서 같은 가입·로그인 흐름을 제공합니다.

## 실행

```bash
cd all_total_vue_student
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp -n .env.example .env  # 처음 준비할 때만 실행. 기존 .env가 있으면 덮어쓰지 않습니다.
# .env에 사용할 모델과 API 키 설정
bash sh/run_kharakteres.sh openai
```

기존 가상환경과 `.env`가 준비되어 있으면 마지막 실행 명령만 사용합니다. 준비 후 **http://localhost:8100** 에 접속해 처음에는 회원가입하고 이후 아이디·비밀번호로 로그인합니다. 계정별 주문사전이 분리되며 프런트엔드 서버는 따로 시작할 필요가 없습니다. 포트를 바꿀 때도 `PORT=8101 bash sh/run_kharakteres.sh openai` 하나로 실행하고 http://localhost:8101/ 에 접속합니다.

- `bash sh/run_kharakteres.sh ollama`: 로컬 Ollama로 언어 해석·생성·문맥 콘텐츠 분류
- `bash sh/run_kharakteres.sh fake`: 외부 LLM 호출 없는 데모. 콘텐츠 검사는 규칙만, 벡터 검색은 기본 비활성화
- `bash sh/run_kharakteres.sh openai --check`: 연결 상태만 확인

Docker Compose 배포는 `.env`의 모델 키와 `KHARAKTERES_SESSION_SECRET`을 설정한 뒤 `docker compose up --build -d`로 시작합니다. 기본 주소는 http://localhost:8100 이며 첫 접속에서 회원가입합니다. 계정과 사용자별 주문 DB, 임베딩 모델은 Docker 볼륨에 보존됩니다. 상세 절차는 [Docker·로그인·시크릿 모드 안내](all_total_vue_student/doc/DOCKER_AUTH.md)에 있습니다.

## [주요 기능]

- AI 주문 생성: 언어·속성·효과·문체·제약 조건 반영
- 다국어 표현: 주문 원문·읽기용 표기·한글 발음·IPA·한국어 의미
- 창작 언어: 사용자가 원문·발음·의미를 직접 정의하고 IPA는 선택 입력
- 주문사전 관리: 생성 초안 편집·저장, 직접 기록, 수정·삭제 및 JSON 내보내기
- 계정별 기록: 회원가입·로그인, 아이디 중복 확인, 가입 이메일 기반 아이디 찾기·비밀번호 재설정, 계정별 주문사전 분리
- 분류·검색: 언어·속성·계열·세계관 필터, 텍스트·의미 기반 검색
- 충돌 검토: 이름·주문문 중복 및 AI 설정 검토, 의도한 변형은 확인 후 저장
- 음성 기능: STT 음성 입력, 선택 구절·주문 항목·전체 기록의 TTS 재생
- 시크릿 모드: 임시 주문 DB·벡터 인덱스를 사용하고 종료 시 폐기, LangSmith tracing 비활성화

## [개선 포인트]

- 언어 출처 확인: Wiktionary 어휘 출처 연결, 확인 범위·실패 상태·원문 링크 표시
- 벡터 RAG: 다국어 로컬 임베딩으로 관련 주문을 검색해 새 주문 생성에 반영
- 콘텐츠 필터: 욕설·혐오·현실 정치 관련 입력을 규칙과 LLM으로 검사
- 생성 과정 체계화: LangGraph로 검색·작성·출처 확인·충돌 검토 순차 구성
- 실행 추적: LangSmith로 모델·검색·필터·음성 처리 과정 관측. 시크릿 모드에서는 추적 제외
- 사용성·검증: 반응형 서고 UI, 단계별 SSE 진행·토큰 표시, 기능·안전 필터·의미 검색 회귀 시나리오
- 배포·기록 보호: Docker Compose, 계정별 영구 저장 볼륨, 로그인 세션 및 임시 시크릿 저장소

## 현재 기술 구조와 도입 판단

`콘텐츠 검사 → 기존 주문 벡터 조회 → 주문 작성 → 웹 어휘 출처 확인 → 일관성 검토 → 사용자 편집·저장`

FastAPI + Vue 3 + LangGraph + SQLite 기반입니다. 가입 계정과 salted PBKDF2 비밀번호 해시는 `accounts.sqlite`에, 각 사용자의 주문과 벡터 인덱스는 `users/<id>/` 아래 별도 SQLite 파일에 저장합니다. Docker Compose는 이 데이터와 FastEmbed 모델 캐시를 영구 볼륨에 보존합니다. LLM은 OpenAI/Ollama 어댑터를 사용합니다. 벡터 검색 모델 준비 지연·오류 시 기본 조회로 대체하고 응답과 화면에 표시합니다.

**Multi-Agent는 도입하지 않았습니다.** 현재 작업 순서가 명확하고 기존 별도 AI 검토가 있어, 독립 에이전트 간 메시지·재계획을 추가할 이익보다 호출 비용·지연·복잡도가 큽니다. 역할을 나눈 함수나 STT/TTS 모델 사용을 멀티 에이전트라고 주장하지 않습니다.

**현재 Kharakteres는 MCP 서버를 사용하지 않습니다.** 웹 사전과 음성 API는 HTTP로, 주문 DB와 임베딩은 로컬 모듈로 연결합니다. 보존된 장애 진단 Base에서만 `agent/mcp_client.py`가 stdio로 `mcp_server.py`(모니터링·Runbook)와 `mcp_server_docs.py`(서비스 문서)를 연결합니다. Base는 도구·리소스 인터페이스를 분리하고 재사용하기 위해 MCP를 사용했습니다. 기본 `SERVICE_MODE=spells` 경로는 이 MCP 세션을 시작하지 않습니다.

![현재 구조](all_total_vue_student/doc/kharakteres-architecture.png)

## 설정과 한계

- 기존 `.env`를 사용합니다. 키·DB·가상환경·벡터 캐시는 Git에서 제외합니다.
- 벡터 모델 기본값은 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`(384차원)입니다. 처음 사용할 때 모델 파일을 내려받을 수 있습니다. 개인 주문 내용은 외부 임베딩 API에 보내지 않습니다.
- `SPELL_VECTOR_ENABLED=0`으로 벡터 조회를 끌 수 있습니다. `SPELL_RETRIEVAL_TIMEOUT_SECONDS=25`, `SPELL_RAG_MIN_SCORE=0.25`가 기본값입니다.
- `CONTENT_FILTER_MODE=model`이 실제 실행의 기본값이며, 검사 모델 오류·시간 초과·판정 형식 오류 때 요청을 중단합니다. `rules`는 알려진 표현만 검사하는 제한된 모드입니다. 필터가 모든 언어·변형·문맥을 완전히 탐지하지는 못합니다.
- 현실 정치 관련 콘텐츠는 서비스 범위에서 차단하지만, ‘정치’라는 단어 자체나 허구의 왕국 정치는 일괄 차단하지 않습니다. 기존 개인 DB 내용을 자동 삭제하지 않습니다.
- Ollama로 주문을 생성해도 **STT/TTS는 별도의 OpenAI API**를 사용하므로 API 키와 사용료가 필요합니다. fake 실행에서는 기본 비활성화됩니다.
- 실제 마이크 권한·장치는 사용자 환경에서 확인해야 합니다. 자동 브라우저 검증의 녹음기는 모의 장치입니다.

## 검증과 문서

```bash
cd all_total_vue_student
.venv/bin/python -m pytest -q
.venv/bin/python eval/kharakteres_browser_smoke.py
.venv/bin/python eval/kharakteres_audio_smoke.py
.venv/bin/python eval/kharakteres_safety_rag_browser.py
# 실제 모델·ONNX 검색 검증: 구성된 모델/API 사용
LLM_BACKEND=openai .venv/bin/python eval/kharakteres_rag_live.py
# Git 후보 파일 크기·큰 과거 객체·일부 키 패턴 검사 (읽기 전용)
.venv/bin/python eval/git_upload_audit.py
```

- [SSE 단계·토큰 전송과 테스트](all_total_vue_student/doc/STREAMING.md)
- [전체 기능·실행 안내](all_total_vue_student/doc/KHARAKTERES.md)
- [Kharakteres 회귀 테스트 쿼리와 기대 결과](all_total_vue_student/doc/regression_test_queries.md)
- [콘텐츠 필터·벡터 RAG·MCP 판단](all_total_vue_student/doc/SAFETY_RAG_MCP.md)
- [Git 업로드 용량과 push 안내](all_total_vue_student/doc/GIT_UPLOAD.md)
- [Docker 배포·로그인·시크릿 모드](all_total_vue_student/doc/DOCKER_AUTH.md)

기존 장애 진단 코드는 보존했습니다. `SERVICE_MODE=incident`로 선택하며 해당 평가 자료는 새 주문 서비스의 기능 증거와 구분합니다.

정리 후 파일 구성과 보존한 BASE 자료는 [정리 기록](all_total_vue_student/doc/CLEANUP.md)과 [BASE 보관 안내](all_total_vue_student/archive/README.md)를 참고하세요.
