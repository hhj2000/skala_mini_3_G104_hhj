# 웹 어휘 출처: 로컬과 Docker

프런트엔드는 `web_chat.html`에서 로컬 `assets/vue.global.prod.js`를 사용하는 Vue 3 화면입니다. FastAPI가 화면과 API를 같은 포트에서 제공합니다. 사전 요청은 브라우저가 아닌 백엔드가 수행하므로 Docker의 외부 연결 조건이 로컬과 다를 수 있습니다.

## 확인한 원인과 변경

2026-10-21 같은 Wiktionary Action API 요청이 호스트에서는 HTTP 200, 기존 Docker 이미지에서는 로봇 정책에 따른 HTTP 403으로 응답하는 것을 확인했습니다. TLS 인증서 오류나 프런트엔드 CORS 오류가 아니었습니다. 공급자가 거절한 경로를 다른 헤더·프록시로 재시도하지 않습니다.

두 조회 제공자를 명시적으로 선택할 수 있습니다.

| 설정 | 조회 대상 | 출처에 표시되는 근거 |
|---|---|---|
| `SPELL_DICTIONARY_PROVIDER=wiktionary` | Wiktionary Action API 직접 검색 및 언어 섹션 읽기 | 조회한 원문 판본의 oldid 고정 링크 |
| `SPELL_DICTIONARY_PROVIDER=wiktapi` | WiktAPI가 독립 배포하는 Kaikki/Wiktextract 데이터 | 실제 응답한 정의 API URL, 원 사전 현재 항목 링크, 배포 데이터·판본 미고정 안내 |

언어 목록 확장 이후 로컬·Docker 이미지·Compose 기본값은 모두 `wiktapi`입니다. 기존 직접 조회는 `wiktionary`로 명시해 사용할 수 있습니다. `.env` 또는 환경 변수로 명시하면 그 값을 사용합니다. 한 제공자의 오류를 숨기고 자동으로 다른 제공자로 바꾸지는 않습니다.

[WiktAPI 공식 설명](https://wiktapi.dev/)과 [API 저장소 문서](https://github.com/TheAlexLichter/wiktapi.dev#api-overview)에 따르면 Kaikki의 Wiktionary 추출 배포 데이터를 제공합니다. 원본 사전의 실시간 최신 판본을 직접 조회한 결과가 아니므로 oldid 검증이나 실시간 최신성으로 표시하지 않습니다.

## 적용

프로젝트 폴더에서 이미지를 다시 만들고 컨테이너를 갱신합니다. 이 명령은 기존 데이터 볼륨을 삭제하지 않습니다.

```bash
docker compose up --build -d
docker compose logs --tail=80 kharakteres
```

기본 설정에서는 `.env`에 사전 변수를 추가하거나 명령 앞에 붙일 필요 없이 위 명령만 사용합니다. 셸 또는 `.env`에 `SPELL_DICTIONARY_PROVIDER=wiktionary`를 명시했다면 그 값이 우선하므로, WiktAPI를 사용하려면 해당 설정을 제거하거나 `wiktapi`로 바꿉니다. 컨테이너만 restart하면 기존 이미지의 코드가 그대로이므로 이번 변경은 rebuild가 필요합니다.

이전에 실패한 주문은 편집 화면의 **웹 출처 다시 확인**을 눌러 재조회하고, 결과를 남기려면 저장합니다. 웹 브라우저를 새로고침해 갱신된 화면도 불러옵니다. fake 모드는 기존처럼 외부 사전을 조회하지 않습니다.

로컬에서도 같은 제공자를 사용할 수 있습니다.

```bash
bash sh/run_kharakteres.sh openai
# 로컬도 wiktapi가 기본값입니다. 사전 제공자와 생성 LLM 설정은 별개입니다.
```

## 조회와 실패의 의미

- 최대 4단어·동시 2개·전체 25초 제한, 성공/미일치 결과 캐시 10분·최대 256개를 유지합니다. 캐시와 접근 거절·요청 제한 상태는 제공자별로 구분합니다.
- WiktAPI의 정의/발음 응답에서 요청한 `lang_code`만 채택합니다. 다른 언어의 동형어는 출처로 사용하지 않습니다. 공통 언어 카탈로그의 ISO 코드와 제공자 코드를 연결하며, 한국어 이름이 있는 전체 지원 언어를 같은 경로로 처리합니다. 정확한 원 사전 언어 섹션을 확인하지 않은 확장 언어에는 실제 API 응답 링크만 제공하고 임의 섹션 링크를 생성하지 않습니다([언어별 범위](LANGUAGES.md)).
- 404/빈 정의/해당 언어 없음은 `not_found`, 연결·응답 오류는 `unavailable`입니다. 403·429/503·시간 초과·연결 실패를 구분한 안내를 보여 줍니다. 공급자 응답 본문·프록시 URL·인증 정보는 사용자 메시지에 넣지 않습니다.
- 403이 확인된 제공자에는 해당 서버 프로세스에서 추가 요청을 중단합니다. 짧은 Retry-After만 한 번 재시도하고 긴 요청 제한은 기다리지 않고 안내합니다. 네트워크가 허용돼도 사전 제공자의 가용성·제한은 보장하지 않습니다.
- 정의를 확보했으나 선택적인 단어 IPA 조회만 실패했다면 정의 근거는 보존하고 IPA를 비워 둡니다. 전체 주문의 발음이나 문법을 검증했다고 표시하지 않습니다.
- 외부 사전 조회에는 해당 단어와 언어 코드가 전송됩니다. 시크릿 모드는 로컬 기록·LangSmith 추적을 제어하며 외부 사전 요청 자체를 숨기는 기능은 아닙니다.

## 실제 검증

사전 제공자 수정 당시 pytest 115개를 통과했습니다. 현재 전체 회귀는 pytest 152개·SSE 클라이언트 5개입니다. 제공자별 동형어 필터·응답 형식·접근 거절 후 중단·Retry-After·캐시 분리·기존 출처 호환·새 출처의 저장/조회 등을 포함합니다.

수정 이미지를 별도 read-only 컨테이너와 임시 DB로 실행해 영어 `light`, 라틴어 `lux`, 고전 그리스어 `φῶς`, 산스크리트어 `अग्नि`의 실제 조회를 확인했습니다. 로그인 → `/api/verify-language` → 저장 → 다시 읽기를 통과했고, Chrome에서 Vue 출처 영역·제공자/판본 안내·원 사전 링크·JavaScript 오류 없음도 확인했습니다. 이 실험에는 LLM·음성 API 호출이 없습니다.

- [실제 컨테이너 결과](../eval/results/kharakteres-dictionary-docker-20261021.json)
- [브라우저 화면](../eval/results/kharakteres-dictionary-docker-20261021.png)
- 스크립트: `eval/kharakteres_dictionary_live.py`. 기존 사용자 서버 대신 빈 계정 DB를 가진 별도 테스트 컨테이너에만 사용합니다.

```bash
# 사용자 볼륨·.env를 연결하지 않는 별도 검사 인스턴스
# 18120 포트가 비어 있을 때 사용합니다.
docker run --rm -d --name kharakteres-dictionary-check --read-only \
  --tmpfs /app/data:uid=10001,gid=10001,mode=0700 --tmpfs /tmp \
  -e LLM_BACKEND=ollama -e SPEECH_BACKEND=disabled \
  -e SPELL_DICTIONARY_PROVIDER=wiktapi -e CONTENT_FILTER_MODE=rules \
  -e SPELL_VECTOR_ENABLED=0 -e LANGSMITH_TRACING=false -e LANGCHAIN_TRACING_V2=false \
  -p 127.0.0.1:18120:8100 kharakteres:local
# /health가 준비된 뒤 실행. --browser는 requirements-browser.txt와 Chrome/Chromium 필요.
.venv/bin/python eval/kharakteres_dictionary_live.py --base-url http://127.0.0.1:18120 --browser --output eval/results/my-dictionary-check.json
docker stop kharakteres-dictionary-check
```

위 검사 서버의 Ollama 어댑터는 생성 요청을 받지 않으므로 모델 호출은 하지 않습니다. 출처 조회·저장·렌더링만 확인한 결과이며, 모든 언어·LLM 생성 주문·외부 서비스 가용성을 검증한 것은 아닙니다. 기존 고정 데이터셋 평가 결과와 재현 스냅샷은 변경하지 않았습니다.

확장 목록 구현 후 로컬/Docker에서 포르투갈어·핀란드어·히브리어의 실제 사전 조회·저장과 언어 목록 UI도 확인했습니다. 현재 229개 범위와 최신 자동 테스트 기록은 [언어 문서](LANGUAGES.md#검증과-적용)를 참고합니다.

## ngrok 공용 URL과 사전 조회

ngrok은 브라우저에서 앱으로 들어오는 요청 경로입니다. 웹 사전 호출은 계속 앱 백엔드가 처리하며 `wiktapi` 기본값·선택 코드 확인·실패 상태·판본 범위를 바꾸지 않습니다. 공개 URL이라고 언어 검증 수준이 높아지거나 사전 공급자 제한이 해제되는 것은 아닙니다. [공용 URL 실행](NGROK_SHARING.md), [이미지 교체](DOCKER_HUB.md)를 참고하세요.
