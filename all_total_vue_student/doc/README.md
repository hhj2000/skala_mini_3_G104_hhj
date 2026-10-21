# Kharakteres 문서

2026-10-21 기준. Kharakteres는 Vue 3 화면과 FastAPI API를 한 서버에서 제공하는 다국어 마법 주문 생성·관리 및 설정 충돌 검토 서비스입니다.

## 현재 실행과 지원 범위

```bash
# 로컬: openai / ollama / fake
bash sh/run_kharakteres.sh openai
# Docker: 프로젝트 폴더에서 실행
docker compose up --build -d
```

접속 주소는 기본 `http://localhost:8100/`입니다. Docker 명령 앞에 사전 환경변수를 붙일 필요는 없습니다. 로컬·Docker 모두 기본 제공자가 `wiktapi`이며 셸 또는 `.env`에 다른 값을 명시한 경우 그 설정을 유지합니다. 기존 볼륨은 유지하고 브라우저를 새로고침합니다.

- **언어:** 한글 이름이 있는 229개를 가나다순 표시. 현대 209개·고전 17개·사멸 3개. 고전은 ISO 고대/역사를 통합한 화면 분류입니다. 사전 갱신은 등록 상태만 바꾸며 지원 범위는 고정합니다.
- **로그인:** 계정별 주문 DB, 재시작 후 세션 복원, 새 로그인 성공 시 이전 로그인 해제. 비밀번호 오류·다른 계정 로그인은 기존 세션에 영향이 없습니다. 쿠키는 400일 수명으로 인증 응답마다 갱신합니다.
- **시크릿:** 임시 주문/벡터 DB와 추적 제외. 해제·로그아웃·세션 교체 시 폐기하고 재시작 후에는 빈 시크릿 서고로 복원합니다.
- **AI:** LangGraph 순차 생성, 로컬 벡터 RAG, 규칙+모델 콘텐츠 필터, 웹 어휘 근거, STT/TTS, 단계·토큰 SSE와 LangSmith 관측. 현재 Kharakteres에는 MCP/독립 Multi-Agent가 없습니다.

## 문서 안내

- [통합 실행·설정·문제 해결](STARTUP.md)
- [전체 기능·모듈·음성 사용법](KHARAKTERES.md)
- [229개 언어·가나다순·실제 품질 범위](LANGUAGES.md)
- [Docker·영구 로그인·계정당 활성 세션 1개·시크릿](DOCKER_AUTH.md)
- [ngrok HTTPS 공용 URL 발급·공유·포트별 연결](NGROK_SHARING.md)
- [joonsdocker/kharakteres 이미지 pull·실행·push·업데이트](DOCKER_HUB.md)
- [공유 경로 PNG](kharakteres-sharing.png) / [SVG](kharakteres-sharing.svg)
- [로컬/Docker 웹 사전 제공자·출처·실패 처리](WEB_SOURCES.md)
- [SSE 단계·토큰 전송](STREAMING.md)
- [콘텐츠 필터·벡터 RAG·MCP/Multi-Agent 판단](SAFETY_RAG_MCP.md)
- [고정 데이터셋·정량 지표·LLM 평가](EVALUATION.md)
- [과제 기준과 구현 증거](ASSIGNMENT_REVIEW.md)
- [회귀 테스트 절차](regression_test_queries.md)
- [Git 용량 점검·push](GIT_UPLOAD.md)
- [파일 정리와 BASE 보존 범위](CLEANUP.md)
- [현재 구조 PNG](kharakteres-architecture.png) / [SVG](kharakteres-architecture.svg)

## 검증 결과의 구분

현재 자동 회귀는 **pytest 152개·SSE 클라이언트 5개**입니다. 두 독립 브라우저의 세션 교체와 실제 컨테이너 재시작 후 최신 세션 유지·이전 쿠키 차단을 확인했습니다. 언어 목록·실제 사전·저장·데스크톱/모바일 배치는 별도 스모크 결과로 보존합니다. [검증 도구와 결과](../eval/README.md)를 참고하세요.

고정 데이터 정량 평가는 [208개 원본 결과](../eval/results/kharakteres-benchmark-20261021/report.md)의 실행 시점 코드 기준입니다. 최신 회귀 통과가 기존 생성 품질 점수의 재측정이나 229개 전 언어·음성 장치의 품질 인증을 뜻하지 않습니다. 새 실제 모델 호출 없이 문서를 최신화했습니다.

과거 BASE 문서·Runbook·평가 스냅샷·실험 보고서는 당시 기록으로 보존합니다. 현재 실행 안내로 사용하지 않습니다([BASE 보관](../archive/README.md), [과거 문서](archive/base/README.md)).

[문서·Compose·구조도·원본 보존 정합성 점검 기록](../eval/results/kharakteres-documentation-validation-20261021.json)에서 현재 문서 17개의 로컬 링크/앵커, Compose 제공자, 기존 평가 코드 17개의 원본 해시 보존 결과를 확인할 수 있습니다.

ngrok 공용 URL 접속·기능 사용은 2026-10-21 [사용자 확인 기록](../eval/results/kharakteres-ngrok-user-report-20261021.json)으로 추가했습니다. 앱 회귀/정량 점수와 구분합니다. 새 안내를 Hub 이미지 내부에도 제공하려면 재빌드·push가 필요하며 Hub Overview는 별도 편집합니다([갱신 절차](DOCKER_HUB.md)).

[ngrok 안내·명령·그림·이미지 포함 점검](../eval/results/kharakteres-ngrok-docs-validation-20261021.json)은 이번 설명 추가의 검증 범위입니다. 공개 URL 기능 사용은 사용자 보고이고, 에이전트는 문서/예제와 격리 로컬 이미지 포장을 확인했습니다.
