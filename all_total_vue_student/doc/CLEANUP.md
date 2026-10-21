# 통합 실행과 파일 정리 기록

## 현재 실행

```bash
bash sh/run_kharakteres.sh openai
```

준비 후 http://localhost:8100/ 에 접속합니다. 별도 프런트엔드 서버나 프록시는 필요 없습니다. `PORT`를 변경하면 화면·API가 함께 해당 포트에서 동작합니다.

## 제거·이동

- `sh/run_frontend.sh`, 루트 `web_demo_server.py`, `doc/incident_web_chat.html`, `eval/browser_smoke.py`를 `archive/base_ui/`로 이동했습니다. 프록시의 주문 API 중계 코드는 제거하고 BASE 진단용 화면·POST·SSE만 보존했습니다.
- 중복 백엔드 별칭 `sh/run_agent_fake.sh`, `sh/run_agent_ollama.sh`, `sh/run_agent_ollma.sh`, `sh/run_agent_openai.sh`를 제거했습니다. `run_kharakteres.sh {fake,ollama,openai}`로 통일합니다.
- 현재 개인 서비스 배포에서 사용하지 않는 이전 학생 배포용 `sh/make_student_zip.sh`를 제거했습니다.
- BASE 설명·개선·검증·과거 실행 안내·수업 매뉴얼·그래프·캡처를 `doc/archive/base/`로 모았습니다. `doc/STARTUP.md`와 `eval/README.md`는 현재 서비스용으로 다시 작성했습니다.
- `.env.example`의 존재하지 않는 자동 설정 복사 안내와 BASE 전용 옵션을 정리했습니다. 실제 `.env`는 변경하지 않았습니다.
- 재생성 가능한 Python 바이트코드, pytest/ruff 캐시와 `.DS_Store`를 정리했습니다. 실행·검사 후 다시 생길 수 있으며 Git에서는 제외됩니다.

## 실행 경로 정리

- `agent/model_factory.py`로 공용 모델 선택 함수를 추출했습니다. 기존 모델 설정·어댑터 동작은 유지합니다.
- Kharakteres가 모델 선택 때문에 `incident_server.py`와 MCP 클라이언트를 불러오던 의존성을 제거했습니다. 기존 서버·평가용 `_build_llms` 호환 경로는 유지합니다.
- Kharakteres 사전 의존성 검사에서 MCP 패키지를 필수로 요구하지 않습니다. BASE 모드에서는 검사하며, 현재 공용 `requirements.txt`에는 BASE 비교 실험을 위해 패키지를 유지합니다.
- 서버 시작 로그와 설치 스크립트는 통합 URL만 안내합니다. BASE 선택 모드는 보관 안내를 표시합니다.
- fake 브라우저 실험은 로컬 `.env`의 실모델 필터·벡터 설정과 분리했습니다.

## 유지한 파일

주문 DB·벡터 캐시·기존 세션 DB, API 키 설정, 가상환경, 모델 캐시, 현재 테스트·실험 결과는 유지했습니다. 기존 BASE API·그래프·MCP·Runbook·테스트·평가 코드는 이전 과제 비교 재현에 사용하므로 삭제하지 않았습니다. 원본 기준선 그래프와 세 LLM 어댑터의 지문도 유지합니다.

BASE의 별도 화면 서버는 기존 API 서버를 변경하지 않고 데모 화면을 붙이고 CORS 설정을 피하기 위한 프록시였습니다. 비동기 처리나 SSE가 별도 포트를 요구하는 것은 아닙니다. [보관 안내](../archive/README.md)에 현재 재현 명령을 정리했습니다.

## 정리 당시 검증

- 전체 pytest 83개 통과
- 통합 실행기: 임시 DB와 임의 포트에서 화면·assets·API 응답 및 별도 프런트엔드 안내 제거 확인
- 이전 BASE UI: 이동한 HTML과 로컬 Vue 파일 응답 확인
- 현재 브라우저 회귀: 생성·편집·저장·검색·중복 확인·삭제·모바일·서버 재시작 보존 확인

사용자 주문 DB를 테스트 데이터로 사용하지 않았고, 검증용 서버는 종료했습니다.


## 현재 유지하는 경계

현재는 계정별 주문·영구 단일 로그인·시크릿 저장소·한국어 이름 229개·고전 통합 분류를 제공합니다. Docker는 `docker compose up --build -d`로 갱신하며 사전 기본값은 `wiktapi`입니다. 하위 SQLite/DB와 개인 사용자 폴더를 이미지 빌드에서 제외하고 볼륨에서 관리합니다. 현재 전체 회귀는 pytest 152개·SSE 클라이언트 5개입니다([문서 목차](README.md)).

이 문서의 83개 테스트와 제거/이동 목록은 파일 정리 당시 기록입니다. BASE 코드·Runbook·원본 평가 스냅샷과 과거 보고서는 최신 기능으로 다시 쓰지 않습니다. 현재 코드의 주석과 사용 안내만 실제 구현에 맞춰 관리합니다.
