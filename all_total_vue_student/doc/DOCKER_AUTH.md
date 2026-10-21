# Docker, 로그인, 시크릿 모드

## Docker Compose 실행

Docker Desktop 또는 Docker Engine과 Compose plugin이 필요합니다. 프로젝트 루트에서 `.env`를 준비하고 세션 서명 키를 설정합니다. 로그인 계정은 최초 실행 뒤 웹 가입 화면에서 만듭니다.

```bash
cp -n .env.example .env
openssl rand -hex 32
```

`.env`에서 서명 키와 사용할 모델 설정을 입력합니다. 기존 `.env`가 있으면 덮어쓰지 마세요.

```dotenv
KHARAKTERES_SESSION_SECRET=openssl_출력값
LLM_BACKEND=openai
OPENAI_API_KEY=실제_API_키
```

그 다음 실행합니다.

```bash
docker compose up --build -d
docker compose logs -f kharakteres
```

`http://localhost:8100/` 에서 회원가입합니다. 종료는 `docker compose down`, 이미지까지 다시 만들려면 `docker compose up --build -d`를 사용합니다. 계정 정보와 사용자별 주문 DB, FastEmbed 모델 파일은 named volume에 보존됩니다. `docker compose down -v`는 계정·주문 DB와 캐시를 지우므로 백업 없이 실행하지 마세요.

포트 변경은 `.env`의 `DOCKER_PORT=8101`로 지정합니다. Compose 설정은 기본적으로 호스트의 loopback 주소에만 공개합니다. 외부 네트워크에 공개할 때는 TLS를 제공하는 reverse proxy, 강한 비밀번호, 방화벽 규칙을 함께 구성하고 `KHARAKTERES_COOKIE_SECURE=1`을 설정하세요. Compose 기본 포트를 공인망에 직접 공개하지 않습니다.

Ollama를 호스트에서 실행한다면 다음을 설정합니다.

```dotenv
LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Docker Desktop에서는 `host.docker.internal`로 호스트 Ollama에 접근합니다. Linux Engine 환경에서 이름을 해석하지 못하면 compose 서비스에 `host.docker.internal:host-gateway` 매핑을 추가합니다. Ollama가 해당 연결을 받도록 호스트 방화벽/네트워크도 설정해야 합니다.

## 로그인

- 로컬과 Docker 모두 같은 계정 가입·로그인을 사용합니다. 첫 사용자 가입 시 이전 공용 주문 DB가 있으면 첫 계정 서고로 복사하고, 이후 사용자는 별도 주문 DB와 벡터 인덱스를 사용합니다.
- 아이디는 영문·숫자와 `. _ -`로 3~32자, 비밀번호는 12자 이상입니다. 비밀번호는 salted PBKDF2 해시로 저장합니다. 중복 확인은 즉시 확인용이며 실제 가입 시 DB unique 제약으로 다시 검사합니다.
- 로그인은 8시간 유효한 HttpOnly·SameSite Strict 서명 쿠키를 사용합니다. Docker는 `KHARAKTERES_SESSION_SECRET`을 필수로 요구하며 로컬에서 생략하면 서버 프로세스마다 임의 서명 키를 사용합니다.
- 아이디 찾기는 가입 이메일로, 비밀번호 재설정은 아이디와 이메일로 확인합니다. SMTP 이메일 인증을 보내지 않는 개인용 편의 기능이므로 인터넷 공개 서비스의 계정 복구로 사용하지 마세요. Docker 기본 포트는 계속 loopback에만 공개됩니다.
- 비밀번호를 재설정하면 해당 계정의 기존 로그인 세션을 폐기합니다.
- 서버 재시작 시 로그인 세션은 만료되고 다시 로그인해야 합니다. 계정/주문 데이터는 영구 저장됩니다.
- HTTPS reverse proxy에서는 secure cookie를 켭니다. HTTP를 쓰는 loopback 로컬 개발에서는 기본값을 그대로 둡니다.

## 시크릿 모드

화면에서 **시크릿 모드 시작**을 누르면 로그인 계정의 서고와 분리된 빈 임시 SQLite DB와 별도 벡터 인덱스를 사용합니다. 모드를 종료하거나 로그아웃하면 임시 파일과 주문을 폐기합니다. 서버가 정상 종료되면 진행 중인 세션 임시 저장소도 닫고 지웁니다.

시크릿 요청은 LangSmith tracing을 끕니다. OpenAI/Ollama 등 생성 모델·음성 API에 전송한 내용은 해당 공급자의 정책을 따르며 로컬 시크릿 모드가 원격 처리까지 숨기지는 않습니다. 실제 주문 입력은 외부 모델에 전송될 수 있습니다. Ollama를 로컬로 실행하면 텍스트 생성은 해당 Ollama 서버에서 처리되고, 음성 기능은 설정에 따라 OpenAI API를 사용합니다.

시크릿 임시 DB는 운영체제 임시 폴더의 제한된 권한 디렉터리에 작성됩니다. 전원 강제 차단·프로세스 강제 종료 때 즉시 정리되지 못할 가능성이 있습니다. 따라서 디스크 forensic 수준의 비밀 저장소로 쓰면 안 됩니다. 이 모드는 앱에서 시크릿 종료를 눌렀을 때 기록을 폐기하는 개인용 작업 공간입니다.

## 검증 범위

2026-10-21에 이미지 빌드와 read-only + 임시 /app/data 컨테이너에서 health·가입/로그인·주문 저장·시크릿 폐기·fake SSE를 확인했습니다. 사용자 볼륨이나 외부 모델 API를 사용하지 않은 격리 검증이며 운영 Compose 배포나 컨테이너의 실제 음성/LLM 품질 검증과는 구분합니다. [재현 명령](EVALUATION.md#docker-격리-스모크-재현)과 [기록](../eval/results/kharakteres-benchmark-20261021/container-smoke.json)을 참고합니다.

계정 중복·복구·접근 격리·이전 세션 취소·재시작 보존은 pytest로 확인했습니다. 이 동작 검증이 공개 서비스용 보안 인증을 의미하지는 않습니다.

## 기존 로컬 주문을 컨테이너에 복사

Docker named volume은 로컬 프로젝트의 계정 DB와 주문 DB와 별도입니다. 예전 공용 주문 DB는 첫 계정 가입 시 자동 복사됩니다. 기존 계정 DB를 Docker에 옮기는 경우 `accounts.sqlite`와 `users/` 디렉터리를 백업 후 컨테이너를 중지한 상태에서 `/app/data/`에 복사하세요. SQLite 파일을 실행 중인 앱에 덮어쓰지 마세요.
