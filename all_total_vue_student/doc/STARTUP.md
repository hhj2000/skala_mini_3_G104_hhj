# Kharakteres 실행 안내

프로젝트 루트에서 실행합니다.

```bash
bash sh/run_kharakteres.sh openai
# 또는
bash sh/run_kharakteres.sh ollama
# 외부 LLM 없는 데모
bash sh/run_kharakteres.sh fake
```

`[준비 완료]` 이후 http://localhost:8100/ 에 접속합니다. 화면과 API가 같은 서버에서 제공되므로 별도 프런트엔드 터미널은 필요 없습니다. 실행 터미널은 유지하고 종료할 때 Ctrl+C를 누릅니다.

첫 실행은 회원가입 후 자동 로그인되고, 이후에는 아이디와 비밀번호로 로그인합니다. 계정별 주문사전은 분리되며 로그인은 재시작 후 복원합니다. 같은 계정의 새 로그인 성공 시 이전 기기의 세션은 해제됩니다. 자세한 쿠키 수명·시크릿 폐기 범위는 [로그인 정책](DOCKER_AUTH.md)을 참고합니다.

## 연결·저장 경로 확인

```bash
bash sh/run_kharakteres.sh openai --check
```

이 검사는 의존성·주문 DB 경로 및 쓰기 권한·모델 정보 조회를 확인합니다. 생성 API의 잔액이나 실제 생성 품질까지 확인하지 않습니다. 실제 셸 환경 변수가 `.env`보다 우선합니다.

Docker로 실행하려면 [Compose 배포·인증 설정](DOCKER_AUTH.md)을 참고하세요. Compose 실행에는 `KHARAKTERES_SESSION_SECRET`이 필요하며 계정은 웹에서 가입합니다. 업데이트 명령은 `docker compose up --build -d` 하나입니다. 사전 기본값은 이미 `wiktapi`이며 명시한 셸/`.env` 제공자 설정은 유지합니다. 데이터 볼륨은 삭제하지 않고 브라우저만 새로고침합니다.

계정 DB와 사용자별 주문 DB는 `data/accounts.sqlite`, `data/users/<account-id>/spells.sqlite`에 저장됩니다. 이전 공용 `data/kharakteres.sqlite`가 있으면 첫 회원가입 때 첫 계정으로 복사합니다. `SPELL_DB_PATH`는 이전 공용 DB의 위치를 지정할 때 사용합니다. 상대 경로는 프로젝트 루트 기준이며 `/absolute/path/...`는 유효한 사용자 경로가 아닙니다.

## 포트 충돌·비교 실행

기존 서버는 해당 터미널에서 Ctrl+C로 종료합니다. 다른 프로세스를 자동으로 종료하지 않습니다.

```bash
lsof -nP -iTCP:8100 -sTCP:LISTEN
# 별도 통합 인스턴스가 필요한 경우
PORT=8101 bash sh/run_kharakteres.sh openai
```

두 번째 인스턴스는 http://localhost:8101/ 로 접속합니다. 테스트용 주문/계정을 분리하려면 `SPELL_DB_PATH`를 별도 폴더의 파일로 지정합니다. 같은 폴더의 다른 파일명만 지정하면 `accounts.sqlite`와 `users/`는 여전히 공유합니다. 포트만 바꿔도 같은 DB를 사용합니다.

## 처음 준비할 때

```bash
bash sh/setup_venv.sh
cp -n .env.example .env
# .env에 본인 API 키와 모델 설정
```

테스트 도구는 `.venv/bin/python -m pip install -r requirements-dev.txt`, 브라우저 도구는 `requirements-browser.txt`로 설치합니다. Ollama 준비는 `bash sh/setup_ollama.sh`를 사용합니다.

자세한 기능은 [서비스 안내](KHARAKTERES.md), 로그인·시크릿 모드·Docker 배포는 [배포 안내](DOCKER_AUTH.md), BASE 재현은 [보관 안내](../archive/README.md)를 참고하세요.

## Docker에서 웹 출처가 실패할 때

기존 Docker에서는 Wiktionary의 HTTP 403 거절을 확인했습니다. 수정 버전은 Docker 기본 WiktAPI 배포 데이터 조회를 사용합니다. `docker compose up --build -d`로 갱신한 뒤 기존 주문의 웹 출처를 다시 확인합니다. [원인·설정·검증](WEB_SOURCES.md)을 참고하세요.

## 언어 목록이 다를 때

한국어 이름이 있는 지원 언어 229개를 가나다순으로 제공합니다. **언어 목록** 메뉴가 없거나 전체 목록이 표시되지 않으면 로컬 서버 재시작 또는 Docker 이미지 rebuild 후 브라우저를 새로고침합니다. [목록·이름/코드·지원 한계](LANGUAGES.md)를 참고하세요.

## ngrok과 Hub 이미지로 공유

로컬/소스 Compose의 기본 포트는 `ngrok http 8100`, Hub 이미지의 호스트 8101 실행 예시는 `ngrok http 8101`로 연결합니다. ngrok은 같은 컴퓨터에서 별도 실행하므로 loopback 바인딩을 바꿀 필요가 없습니다. HTTPS용 `KHARAKTERES_COOKIE_SECURE=1`과 서명 키를 준비하고 실제 Forwarding 주소를 공유합니다. [ngrok 설치·환경·공유](NGROK_SHARING.md), [joonsdocker/kharakteres:latest pull·실행·갱신](DOCKER_HUB.md)을 참고하세요.
