# Kharakteres 문서

Kharakteres는 다국어 마법 주문 생성·관리, 계정별 주문사전, 설정 충돌 검토를 제공하는 AI 웹 서비스입니다. 로컬 또는 Docker에서 회원가입해 사용하며, 주문 데이터는 사용자별 SQLite에 분리 저장됩니다.

- [통합 실행·환경 설정·문제 해결](STARTUP.md)
- [SSE 실시간 단계·토큰 전송](STREAMING.md)
- [전체 기능·언어·음성 사용법](KHARAKTERES.md)
- [Docker 배포·로그인·시크릿 모드](DOCKER_AUTH.md)
- [콘텐츠 필터·벡터 RAG·MCP/Multi-Agent 판단](SAFETY_RAG_MCP.md)
- [고정 데이터셋·정량 지표·LLM 평가](EVALUATION.md)
- [과제 평가 항목과 구현 증거 점검](ASSIGNMENT_REVIEW.md)
- [회귀 테스트 입력과 기대 결과](regression_test_queries.md)
- [GitHub 용량 점검·push 방법](GIT_UPLOAD.md)
- [현재 구조 PNG](kharakteres-architecture.png) / [SVG](kharakteres-architecture.svg)
- [파일 정리 기록](CLEANUP.md)

현재 정량 평가 체계는 미니 프로젝트에서 개선 효과·한계를 설명할 수준이며, 실사용 전반의 품질 인증과는 구분합니다. 2026-10-21 실측은 [평가 결과](../eval/results/kharakteres-benchmark-20261021/report.md)에, 최신 자동 검증은 pytest 105개·SSE 클라이언트 4개·격리 컨테이너 스모크 결과에 기록했습니다.

주제 전환 이전 자료는 [BASE 보관 안내](../archive/README.md)에서 확인합니다. [과거 문서와 캡처](archive/base/README.md)는 현재 서비스의 실행 안내·기능 증거와 구분합니다.
