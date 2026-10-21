# Docker Hub 이미지 배포와 업데이트

배포 저장소는 **`joonsdocker/kharakteres:latest`**입니다. 이미지 배포와 ngrok 공용 URL은 별개입니다. 운영자는 이미지를 실행해 서버를 준비하고 [ngrok 공유 안내](NGROK_SHARING.md)로 HTTPS 주소를 발급합니다. 웹 방문자는 브라우저만 필요합니다.

## 내려받아 실행하기

아래는 macOS Docker Desktop이 실행 중인 컴퓨터 기준입니다. 소스 코드나 로컬 Python 가상환경은 없어도 됩니다. 소스 Compose의 8100과 충돌하지 않게 이 예시는 호스트 **8101 → 컨테이너 8100**을 사용합니다.

```bash
mkdir -p ~/kharakteres-deploy
cd ~/kharakteres-deploy
docker pull joonsdocker/kharakteres:latest
```

저장소가 비공개면 먼저 권한 있는 계정으로 `docker login`합니다. 최초 이미지가 호스트 CPU에 맞아야 하며 2026-10-21 조회한 latest의 실행 플랫폼은 `linux/arm64`입니다. Intel/AMD 배포에는 아래 멀티플랫폼 빌드가 필요합니다. 이후 latest가 교체되면 플랫폼을 다시 확인합니다.

```bash
docker buildx imagetools inspect joonsdocker/kharakteres:latest
```

세션 서명 키를 생성하고 **이 배포 폴더의** `.env`에 실제 값을 입력합니다. 기존 `.env`나 서명 키를 덮어쓰지 않습니다.

```bash
openssl rand -hex 32
nano .env
```

```dotenv
LLM_BACKEND=openai
OPENAI_API_KEY=본인의_OpenAI_API_키
REQUIRE_SESSION_SECRET=1
KHARAKTERES_SESSION_SECRET=생성한_64자리_16진수_서명_키
KHARAKTERES_COOKIE_SECURE=1
SPELL_DICTIONARY_PROVIDER=wiktapi
LANGCHAIN_TRACING_V2=false
LANGSMITH_TRACING=false
```

이는 HTTPS 공유용 구성입니다. LangSmith 추적을 사용하려면 본인의 추적 키·프로젝트를 추가합니다. API 키·ngrok 토큰·실제 `.env`·개인 DB를 이미지에 넣지 않습니다.

```bash
docker run -d \
  --name kharakteres-hub \
  --restart unless-stopped \
  --init \
  --env-file .env \
  -p 127.0.0.1:8101:8100 \
  -v kharakteres_hub_data:/app/data \
  -v kharakteres_hub_models:/models/fastembed \
  --read-only \
  --tmpfs /tmp:size=256m,mode=1777 \
  --security-opt no-new-privileges:true \
  joonsdocker/kharakteres:latest
```

`kharakteres_hub_data`는 계정·영구 세션·주문·벡터 DB, `kharakteres_hub_models`는 임베딩 모델 캐시입니다. 소스 Compose의 기존 볼륨이나 로컬 DB와는 별개이므로 새 볼륨은 회원가입부터 시작합니다. 같은 이름의 컨테이너가 있으면 상태를 확인하고 기존 컨테이너를 재사용/갱신하며 다른 컨테이너를 임의 삭제하지 않습니다.

```bash
docker ps --filter name=kharakteres-hub
docker logs --tail=100 kharakteres-hub
curl http://127.0.0.1:8101/health
```

ngrok을 **같은 호스트의 터미널**에서 인증한 뒤 연결합니다. 설치/인증은 [ngrok 안내](NGROK_SHARING.md#최초-준비)를 참고하세요.

```bash
ngrok http 8101
```

Forwarding에 표시된 HTTPS 주소를 공유하고 해당 주소에서 가입/로그인합니다. Docker Desktop의 Containers에서도 이 컨테이너를 관리할 수 있습니다. Docker/앱/ngrok은 계속 실행돼 있어야 합니다.

Docker Desktop **ngrok Extension**의 Endpoints를 사용할 때는 위 포트 옵션을 `-p 0.0.0.0:8101:8100`으로 바꾸고 같은 볼륨으로 컨테이너를 재생성합니다. Extension의 Target Port는 호스트 포트 **8101**입니다. [CLI와 Extension의 연결 차이](NGROK_SHARING.md#docker-desktop-ngrok-extension으로-연결)를 참고하세요. 이 변경만으로는 이미지 재빌드/push가 필요하지 않습니다.

## 기존 컨테이너 중지와 시작

```bash
docker stop kharakteres-hub
docker start kharakteres-hub
```

이 명령은 컨테이너를 삭제하지 않으며 기존 환경·이미지·볼륨을 사용합니다. `.env`나 Hub latest를 바꿨다고 기존 컨테이너 설정이 자동 변경되지는 않습니다.

## 이번 문서 변경을 이미지에도 반영해야 하는가

| 원하는 결과 | 필요한 작업 |
|---|---|
| 현재 앱을 계속 ngrok으로 공유 | 문서 갱신만으로 재배포할 필요 없음. ngrok은 호스트에서 별도 실행 |
| Git의 설명 갱신 | 문서·이미지·예제·주석을 commit/push |
| 내려받는 이미지 안의 새 doc/그림/.env.example 제공 | 이미지를 다시 빌드하고 같은 저장소에 push |
| Docker Hub 웹페이지의 Overview 설명 갱신 | Hub에서 별도 편집. 일반 CLI push로 README가 자동 동기화되지는 않음 |
| API/화면 코드 변경을 이미지 사용자에게 제공 | 재빌드·push 후 사용자도 pull하고 컨테이너 재생성 |

현재 Dockerfile의 `COPY . .`는 빌드 폴더 안의 `doc/`, 구조도, `.env.example`을 포함합니다. `.dockerignore`는 실제 `.env`, 계정/주문 DB, 가상환경·캐시·실험 결과를 제외합니다. Git 저장소 최상위 README는 이 하위 프로젝트 빌드 컨텍스트 밖에 있으므로 Hub Overview에는 별도로 옮깁니다.

## 게시자: ARM64 이미지 갱신

소스 프로젝트 폴더에서 실행합니다. 아래 명령은 사용자가 직접 게시할 때 사용하는 절차이며 이번 문서 작업에서 실제 push는 수행하지 않았습니다.

```bash
cd /Users/hyeongjunhan/skala_mini_3_G104_hhj/all_total_vue_student
docker login
docker compose build kharakteres
docker tag kharakteres:local joonsdocker/kharakteres:latest
docker push joonsdocker/kharakteres:latest
```

`docker compose build`는 이미지를 갱신하며 실행 중인 컨테이너를 자동 교체하지 않습니다. 자신의 소스 Compose 서비스까지 갱신하려면 `docker compose up -d`로 교체하고 브라우저를 새로고침합니다. `docker compose up --build -d`도 동일한 코드 갱신 경로이며, 어느 명령도 Hub에 자동 push하지 않습니다.

CLI 빌드는 실행한 호스트/빌더의 플랫폼을 따릅니다. Mac ARM64에서의 단일 플랫폼 push는 ARM64 이미지가 됩니다. 이미 멀티플랫폼으로 게시한 태그를 이후 단일 플랫폼 push로 교체하면 다른 플랫폼 지원이 사라질 수 있으므로 게시 방식을 일관되게 유지합니다.

## 게시자: ARM64와 AMD64 함께 제공

Docker Desktop의 멀티플랫폼 빌드가 가능한 빌더에서 아래 명령을 사용합니다. 처음에는 두 플랫폼의 의존성을 준비하므로 시간이 더 걸릴 수 있습니다. 두 이미지 모두 검증하기 전에는 모든 환경의 동작이 확인됐다고 표시하지 않습니다.

```bash
docker login
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t joonsdocker/kharakteres:latest \
  --push .
docker buildx imagetools inspect joonsdocker/kharakteres:latest
```

`--push`가 빌드 결과를 바로 업로드하므로 별도 tag/push는 필요하지 않습니다. 로컬 `kharakteres:local` 컨테이너나 이미지를 이 명령이 자동 교체하지는 않습니다. 빌더가 여러 플랫폼을 지원하지 않으면 [Docker 공식 빌더 준비](https://docs.docker.com/build/building/multi-platform/)를 따릅니다.

## 이미지 사용자: 새 버전 적용

배포 폴더에서 새 이미지를 받고 **이 안내로 만든 컨테이너만** 중지/삭제한 뒤 위 docker run 명령으로 다시 만듭니다.

```bash
cd ~/kharakteres-deploy
docker pull joonsdocker/kharakteres:latest
docker stop kharakteres-hub
docker rm kharakteres-hub
```

같은 `.env`·서명 키·두 볼륨 이름·포트로 위 docker run을 재실행합니다. 볼륨은 삭제하지 않습니다. 데이터 볼륨이 있어도 바뀐 이미지가 자동 실행되는 것은 아니며 `pull` 또는 `restart`만으로는 새 이미지가 적용되지 않습니다. 서비스가 돌아오면 ngrok과 공개 HTTPS 주소의 로그인·주문·SSE를 확인합니다. ngrok 프로세스를 계속 유지했다면 앱 교체 중 일시 중단 뒤 같은 터널이 다시 업스트림에 연결될 수 있습니다.

## Hub 웹페이지 설명

Docker Hub의 `joonsdocker/kharakteres` 저장소에서 Repository overview를 편집하고 최신 실행/환경/볼륨/ngrok 안내를 옮깁니다. 자동 빌드의 README 동기화를 별도 설정한 경우는 예외이며, 일반 `docker push`와 Overview 변경은 독립 작업입니다([공식 저장소 설명 관리](https://docs.docker.com/docker-hub/repos/manage/information/)).

공식 참고: [이미지 게시](https://docs.docker.com/get-started/docker-concepts/building-images/build-tag-and-publish-an-image/), [컨테이너 실행](https://docs.docker.com/reference/cli/docker/container/run/), [멀티플랫폼 빌드](https://docs.docker.com/build/building/multi-platform/).
