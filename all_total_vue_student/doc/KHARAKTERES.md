# Kharakteres — 나만의 마법 주문 웹 서비스

기존 AI Agent 프로젝트의 주제를 **개인용 마법 주문 생성·관리 사전**으로 전환한 첫 버전입니다. FastAPI, Vue 3, LangGraph, SQLite, LLM 어댑터, LangSmith 연결을 재사용했습니다.

## 바로 실행

```bash
cd /Users/hyeongjunhan/skala_mini_3_G104_hhj/all_total_vue_student
bash sh/run_kharakteres.sh openai
```

준비 완료 후 **http://localhost:8100** 으로 바로 접속합니다. 새 서비스는 프런트엔드도 함께 제공하므로 다른 터미널에서 프런트엔드를 띄우지 않아도 됩니다. 서버를 실행하는 터미널은 열어둡니다.

다른 백엔드:

```bash
bash sh/run_kharakteres.sh ollama
bash sh/run_kharakteres.sh fake
```

백엔드 선택은 `run_kharakteres.sh`의 첫 번째 인자로 통일했습니다. OpenAI/Ollama 전환 전 기존 서버를 Ctrl+C로 종료합니다.
`--check`는 연결만 검사하며, 서버는 시작하지 않습니다.

```bash
bash sh/run_kharakteres.sh openai --check
```

화면과 API를 같은 서버에서 제공합니다. 별도 프런트엔드 실행은 필요하지 않습니다. Vue 배포 파일을 `assets/`에 포함해 화면 표시 자체는 외부 CDN에 의존하지 않습니다.

## 주요 기능

1. **주문 창작**: 효과·세계관·대상·제약, 채팅으로 언어를 입력하고, 속성(최대 4개), 계열, 문체 선택. 기존 주문의 맥락을 참고해 AI 초안 생성.
2. **다국어 주문문**: 한국어·영어·여러 현대 언어와 라틴어·고전 그리스어·산스크리트어 선택. 다른 언어도 직접 입력 가능. 현재 선택된 LLM이 언어를 해석하며 모호하면 추가 질문. 원문·로마자·한글 전사·IPA·발음 관례·한국어 의미를 별도 기록.
3. **개인 주문사전**: 저장 전 초안 편집, 저장 후 수정·삭제, 직접 기록, 이름·주문문·효과 검색, 언어·속성·계열·세계관 필터.
4. **일관성 검토**: 같은 세계관의 이름/주문문 중복, 속성·계열 차이, 유사 효과를 설명. AI 설정 검토는 별도 버튼으로 실행하며 비교 대상 ID와 검토 이유 제공.
5. **작가가 최종 결정**: 중복은 무조건 금지하지 않음. 검토 후 의도한 변형으로 저장 가능. 생성만으로 DB에 자동 저장하지 않음.
6. **데이터 보존**: SQLite 영구 저장, 서버 재시작 후 유지, 수정 버전 검사로 다른 화면의 변경을 덮어쓰지 않도록 보호, JSON 내보내기.
7. **관측 가능성**: LangGraph의 기존 주문 벡터 검색 → 초안 작성 → 웹 어휘 출처 검색 → 일관성 검토, LangSmith trace와 요청 Run ID. 실제 LLM 호출은 `spell.language_model` 노드에서 확인. 기본 실행 스크립트는 `kharakteres-openai` 또는 `kharakteres-ollama` 프로젝트 사용. 셸의 LANGCHAIN_PROJECT가 있으면 그 값을 유지.

8. **웹 어휘 출처**: 현대어·고전어를 같은 방식으로 영문 Wiktionary 검색 API에서 조회. 최대 4개 단어의 표제어와 해당 언어 섹션을 확인하고, 판본 고정 링크·일부 뜻풀이·명시된 단어 IPA(있을 때)·확인 시각 저장. 연결 실패/검색 결과 없음/데모/수정 후 만료 상태 구분.

## 실시간 생성

웹 화면은 `POST /api/generate/stream`으로 SSE를 수신합니다. 요청 검사 → 기존 주문 검색 → 주문 작성·콘텐츠 검사 → 언어 출처 확인 → 충돌 검토가 진행되는 대로 표시됩니다. OpenAI/Ollama 모델의 실제 응답 조각을 받아 주문 이름·원문·발음·효과 등을 작성 중 미리보기로 보여주고, 검사된 초안과 출처·검토 결과를 순차 갱신합니다.

완료 전에는 편집·저장·TTS를 사용할 수 없습니다. 생성 중단·오류·연결 끊김 때는 미완성 초안을 지우며 자동 재요청하지 않습니다. fake와 인공 언어 요청은 모델 토큰을 만들어내지 않고 실제 처리 단계만 표시합니다. LangSmith Run ID로 단계 및 모델의 `new_token` 기록을 찾을 수 있습니다. [동작·제약·검증 방법](STREAMING.md)을 참고하세요.

## 사용 흐름

- 홈에서 **새 주문 만들기** 또는 **주문 찾아보기** 선택.
- 창작 화면에서 “어떤 언어로 주문을 만들까요?”에 채팅으로 답하고 **언어 답장 보내기** 선택. 언어가 확인되면 효과·속성을 입력하고 생성. 예: “영어로”, “고전 그리스어로”. 모호한 답변에는 후속 질문.
- 오른쪽 초안에서 원문·로마자·한글 전사·IPA·의미·제약과 기존 주문 검토 확인. **단어 출처 발견** 영역의 실제 웹 사전 링크와 확인 시각도 확인.
- **편집하고 저장하기**로 문구를 다듬고 저장.
- 목록 카드를 열어 편집/삭제/중복 검토/AI 설정 검토. 기존 기록도 편집 화면에서 **웹 출처 다시 확인** 가능. 언어·주문문·발음을 바꾸면 출처는 재확인 필요 상태가 됨. 확인 결과는 저장 버튼을 눌러야 DB에 반영.
- 기존에 만든 주문은 **직접 기록**으로 AI 호출 없이 추가 가능.

## 변경된 구조

| 파일 | 역할 |
|---|---|
| `server.py` | 서비스 선택 진입점. 기본 Kharakteres, SERVICE_MODE=incident로 기존 서비스 선택 |
| `kharakteres/api.py` | 화면·카탈로그·생성·검색·CRUD·검토·내보내기 API |
| `kharakteres/models.py` | 주문/생성/편집 스키마, 언어·속성·계열 분류 |
| `kharakteres/store.py` | SQLite 저장, 수정 버전 검사, 기록 보존 |
| `kharakteres/lexicon.py` | 검색·분류·세계관 범위의 규칙 기반 중복 검토 |
| `kharakteres/verification.py` | 제한 시간 내 실제 웹 사전 검색, 언어 섹션 확인, 출처 판본·검토 대상 지문 관리 |
| `kharakteres/generation.py` | LangGraph 생성 파이프라인, LLM JSON 출력 검증, AI 설정 검토 |
| `web_chat.html` | 서고 분위기의 반응형 주문사전 UI |
| `assets/` | 로컬 Vue 런타임과 MIT 라이선스 |
| `sh/run_kharakteres.sh` | 서비스 실행과 LangSmith 프로젝트 기본 설정 |
| `incident_server.py` | 전환 직전 장애 진단 서버 보존 |
| `archive/base_ui/incident_web_chat.html` | 전환 직전 장애 진단 화면 보존 |

DB 기본 위치는 `data/kharakteres.sqlite`입니다. Git에 포함하지 않습니다. `SPELL_DB_PATH` 환경 변수로 별도 파일을 지정할 수 있습니다. 상대 경로는 프로젝트 폴더를 기준으로 해석하며 `~`도 지원합니다. 기본 경로를 쓰려면 해당 변수를 생략하거나 빈 값으로 두세요. `/absolute/path/...`는 안내용 예시이며 실제 저장 경로가 아닙니다. 시작 시 경로와 쓰기 권한을 검사하고 잘못된 설정은 모델 연결 전에 안내합니다. 기존 `session.db`와 장애 진단 데이터/매뉴얼은 삭제하지 않았습니다.

## 설정

기존 `.env` 키/모델 설정을 그대로 사용합니다.

```dotenv
# 선택 설정
SERVICE_MODE=spells
# SPELL_DB_PATH=data/kharakteres.sqlite
SPELL_MAX_TOKENS=1536
SPELL_GENERATION_TIMEOUT_SECONDS=120
```

Ollama는 개선 어댑터를 사용하고 `think=false`를 기본으로 합니다. 주문 JSON 생성을 위해 해당 모델 인스턴스에만 1536 생성 토큰 예산을 적용하며 기존 장애 진단 어댑터는 바꾸지 않습니다.

## 확인한 테스트

```bash
.venv/bin/python -m pytest -q
# 선택: requirements-browser.txt와 Chrome 또는 Playwright Chromium 필요
.venv/bin/python eval/kharakteres_browser_smoke.py
# 실제 모델과 웹 검색 검증 (OpenAI 실행 시 기존 API 계정 사용)
.venv/bin/python eval/kharakteres_language_smoke.py
```

브라우저 테스트는 임시 DB와 별도 포트에서 실행해 사용자 주문을 변경하지 않습니다. 생성 → 편집 → 저장 → 검색 → 충돌 검토·허용 → 삭제, 모바일 가로 넘침, 서버 프로세스 재시작 후 기록 일치를 확인합니다.

자동 테스트 94개와 브라우저 CRUD·재시작 검증을 통과했습니다. 실제 Ollama(qwen3:8b) 한국어 주문 생성도 성공했으며 이번 단일 요청은 약 19초였습니다.

실제 OpenAI로 라틴어·고전 그리스어·산스크리트어 생성과 AI 검토 API가 성공하는 것을 확인했습니다. 그리스 문자·데바나가리 문자 출력도 확인했습니다. **해당 언어 문법이 정확하다는 검증은 아닙니다.** 결과는 `eval/results/kharakteres-llm-smoke.json`, 실행 trace 정보는 `eval/results/kharakteres-langsmith.json`에 있습니다.

이번 언어 입력 개선은 실제 OpenAI(gpt-4o)로 영어·고전 그리스어의 한글 전사·IPA 생성, 저장/다시 읽기, 웹 출처 UI와 수정 후 만료/재조회까지 실행했습니다. 영어는 단어 출처 4개를 확인했고, 고전 그리스어는 외부 사전 429 요청 제한으로 `unavailable`과 재확인 안내가 표시됐습니다. 요청 제한을 우회하지 않고 Retry-After를 존중합니다. Ollama(qwen3:8b)에서도 채팅 언어 해석 → 영어 주문·한글 전사·IPA 생성 → 실제 단어 출처 조회가 성공하는 것을 별도로 확인했습니다. 발음의 언어학적 정확성은 검증한 것이 아닙니다. 확인 결과는 `eval/results/kharakteres-language-smoke.json`, 화면은 `eval/results/kharakteres-language-sources.png`에 있습니다. 실제 모델 테스트의 LangSmith 프로젝트는 `kharakteres-language-feedback`입니다.

화면 캡처: `eval/results/kharakteres-desktop.png`, `kharakteres-create.png`, `kharakteres-mobile.png`.

## 범위와 한계

- 주문은 **창작물**입니다. 고전어 문법·발음·직역을 검증했다고 표시하지 않으며, 언어학적 검수가 필요합니다. 웹 검증은 **어휘 출처 확인** 범위입니다. 주문 전체 문법·의미·한글 전사·IPA의 정확성을 인증하지 않습니다. 위키낱말사전은 공동 편집 사전이므로 전문 언어학적 검수와 구분합니다.
- 웹 검색은 별도 검색 API 키 없이 실제 Wiktionary에 연결합니다. Ollama 실행 시에도 이 사전 조회는 외부 네트워크 요청이며 생성 LLM을 OpenAI로 바꾸지는 않습니다. 조회 단어 최대 4개, 동시 조회 2개, 전체 25초 제한. 짧은 Retry-After에 한 번만 재시도하며, 성공한 결과는 10분간 최대 256개 캐시해 반복 요청을 줄입니다. 검색 실패해도 AI 초안은 보존합니다. 굴절형과 한국어 조사·띄어쓰기 없는 일본어/중국어 문장·창작 언어는 일치 항목을 찾지 못할 수 있습니다.
- 한글 전사와 전체 문장 IPA는 **사용 중인 LLM의 추정 출력**입니다. 고전어의 재구음/시대·현대어 방언은 발음 관례 필드에 기록합니다. 출처의 단어 IPA를 전체 주문의 검증된 발음으로 표시하지 않습니다.
- fake 모드는 UI/제어 흐름 데모입니다. 외국어 변환이 수행되지 않으면 한국어 임시 문구와 명확한 미변환 표시를 사용합니다.
- 목록에서 키워드/벡터 의미 검색을 선택할 수 있습니다. 실제 모드는 다국어 임베딩 기반 주문 RAG를 사용하며, 준비 실패 시 대체 조회와 이유를 표시합니다. Base의 Runbook 인덱스와 새 주문 인덱스는 별개입니다.
- 중복은 이름/주문문의 정규화 비교, 유사 효과는 문자열 유사도입니다. 산스크리트 등 결합 문자의 의미를 훼손하지 않도록 문자 부호를 보존합니다.
- AI 충돌 검토는 같은 세계관에서 속성이 관련된 최대 30개 주문만 참고합니다. 후보·추정이며 설정 충돌을 완전히 검출하거나 오류로 확정하지 않습니다.
- 현재 한 서버의 개인용 서고입니다. 로그인·사용자별 권한 분리·인터넷 호스팅은 이번 첫 작업에 포함하지 않았습니다.
- JSON 내보내기는 구현했지만 가져오기/백업 복원 UI는 아직 없습니다. DB 파일과 JSON을 함께 보관하면 좋습니다.

## 기존 프로젝트 실행

```bash
SERVICE_MODE=incident bash sh/run_agent.sh --backend openai
# 과거 화면까지 확인할 때만 다른 터미널에서 실행
bash archive/base_ui/run_frontend.sh
```

기존 진단 API·그래프·비교 자료는 그대로 보존했습니다. 과거 테스트/평가 코드는 보존된 incident_server와 기존 그래프를 사용합니다.

## 언어 관련 API

- `POST /api/language`: `message`, 최근 `history`(최대 10개)로 현재 quality LLM에 언어 선택 요청. `resolved`, 표준 언어 코드 또는 영어 언어명, 한국어 답장 반환. 대화 기록 자체는 DB에 저장하지 않음.
- `POST /api/generate`: 기존 요청 형식 유지. 응답 draft에 `hangul_pronunciation`, `ipa`, `pronunciation_note`, `verification` 추가. 기존 저장 기록은 새 필드의 빈 기본값으로 호환.
- `POST /api/verify-language`: 현재 주문 필드로 웹 어휘 출처 재조회. 자동 저장하지 않음.
- 출처 조회 구현은 [MediaWiki Search API](https://www.mediawiki.org/wiki/API:Search) 및 [Revisions API](https://www.mediawiki.org/wiki/API:Revisions)를 사용. LLM이 지어낸 URL을 출처로 사용하지 않음. 검색된 표제어의 해당 언어 섹션을 실제로 읽은 경우만 링크를 생성하며 판본 ID로 고정함.

## 인공 언어와 음성 입력·재생 (1차 피드백)

### 나의 인공 언어 / 세계관 속 언어

창작 화면의 **주문 언어 종류 → 나의 인공 언어 · 세계관 속 언어**를 선택합니다.
언어 이름, 주문문, 발음(한글이나 읽을 수 있는 표기), 의미는 작가가 직접 입력합니다. **IPA는 비워도 생성·저장할 수 있습니다.**
이 경로에서는 LLM이 언어를 임의로 번역하거나 발음·의미를 채우지 않습니다. 입력값을 그대로 초안에 옮기고 기존 주문과 일관성을 검토합니다. 효과·속성·세계관은 같은 화면에서 지정합니다. 주문 이름과 내용은 저장 전에 자유롭게 편집할 수 있습니다.
인공 언어는 웹 사전의 참·거짓 검증 대상으로 취급하지 않고 **작가가 직접 정의한 언어**로 표시합니다. 기존 실제 언어의 생성 경로는 유지합니다.

### STT: 말한 내용을 입력 칸으로

창작 화면이나 편집 화면에서 **음성으로 입력하기**를 펼칩니다.

1. **마이크 녹음 시작 → 녹음 종료** 또는 음성 파일 올리기. 녹음은 최대 60초, 파일은 10MB입니다.
2. 말한 언어(한국어·영어·자동 감지)를 고르고 **음성 전사 실행**을 누릅니다.
3. 전사 결과를 확인·수정하고, 입력할 곳을 고른 뒤 **선택한 칸에 적용**합니다. 기존 내용을 교체하므로 적용 전에 확인합니다.

마이크는 localhost 또는 HTTPS와 브라우저의 마이크 허용이 필요합니다. 권한이 없거나 녹음 지원이 부족하면 파일 업로드를 사용합니다.
인공어·고전어는 STT가 정상적인 원문으로 인식하지 못할 수 있으므로, 한국어로 설명을 말하거나 발음 표기를 직접 정정하는 방식을 권장합니다.
전사 실패나 API 키 누락 시 예시 문구를 실제 인식 결과처럼 반환하지 않습니다.

### TTS: 부분·전체 변환

초안 또는 저장한 주문의 상세·편집 화면에서 **주문과 기록을 음성으로 듣기**를 펼칩니다.

- 범위: 주문 원문, 한글 전사/지정 발음, 의미, 효과, 전체 기록.
- 인공 언어의 주문 읽기는 **작가가 입력한 발음**을 사용합니다. 원문이나 IPA에서 새로운 발음을 추측하지 않습니다.
- 읽을 내용은 편집할 수 있고, 원하는 구절을 드래그한 뒤 **선택한 구절 변환**을 누를 수 있습니다.
- **읽을 내용 전체 변환**은 현재 칸의 전체 내용을 읽습니다. 범위를 ‘전체 기록’으로 바꾸면 이름·주문·의미·효과·대상·제약·메모 전체를 읽습니다.
- 음색과 읽기 속도를 고를 수 있으며 생성한 음성은 재생·정지하거나 WAV로 내려받을 수 있습니다. 긴 내용은 잘라 버리지 않고 나눠 합칩니다. 입력 최대 14,000자, 전체 처리 제한 240초입니다.
- TTS는 AI 합성 음성입니다. 특히 인공어·고전어의 음소나 IPA가 정확히 재현된다는 보장은 없습니다.

### 노트북에서 반영한 코드와 설정

공유한 `3반_한형준_AIDubsar.ipynb`의 `transcribe_audio_file`(셀 22)과 `ui_tts_summary`(셀 32)를 참고했습니다.
노트북의 **Whisper `whisper-1` STT**, **`gpt-4o-mini-tts` / `coral` TTS**, 전사 후 사용자가 텍스트를 확인하는 흐름을 유지했습니다.
Gradio와 노트북 실행 대신 FastAPI 비동기 HTTP와 Vue의 MediaRecorder로 옮겼습니다. TTS는 부분 및 긴 기록을 하나의 파일로 제공하기 위해 WAV로 반환합니다.

```dotenv
SPEECH_STT_MODEL=whisper-1
SPEECH_TTS_MODEL=gpt-4o-mini-tts
# 음성만 비활성화하려면
# SPEECH_BACKEND=disabled
```

음성 API 키는 기존 서버 `.env`의 `OPENAI_API_KEY`를 사용하며 브라우저에 전달하지 않습니다. 별도 패키지나 모델 다운로드는 추가하지 않았습니다.
**Ollama로 주문을 생성할 때에도 STT/TTS는 별도의 OpenAI API를 사용하므로 외부 전송·과금이 발생합니다.** fake 실행은 기본적으로 음성 API가 비활성화됩니다.
원본 녹음과 생성 음성은 서비스 DB·디스크에 자동 저장하지 않습니다. 브라우저 메모리에 보관하며 내려받기는 사용자 선택입니다. STT 결과도 적용·저장하기 전에는 주문 DB에 남지 않습니다.
LangSmith에는 오디오 바이트 대신 길이·모델 등의 메타데이터가 기록되고 STT 전사 텍스트는 출력으로 기록될 수 있습니다.

| 파일 | 추가 역할 |
|---|---|
| `kharakteres/models.py`, `generation.py`, `verification.py` | 인공 언어 입력·선택 IPA·작가 정의 상태 |
| `kharakteres/speech.py` | Whisper STT, TTS 분할·WAV 결합, API 오류·키 처리 |
| `kharakteres/api.py` | `/api/audio/transcribe`, `/api/audio/speech`, 음성 설정 제공 |
| `assets/speech.js` | 마이크/파일 입력, 전사 검토와 적용, 선택 구절/전체 TTS 및 다운로드 |
| `web_chat.html` | 인공 언어 양식, 창작·편집·상세에 음성 도구 연결 |

음성 API는 [OpenAI 공식 STT 문서](https://developers.openai.com/api/docs/guides/speech-to-text)와 [TTS 문서](https://developers.openai.com/api/docs/guides/text-to-speech)를 확인해 연결했습니다.

### 음성 검증

현재 자동 테스트 94개와 기존 브라우저 회귀 검증을 통과했습니다. 실제 `gpt-4o-mini-tts` 한국어 음성을 `whisper-1`로 다시 전사하는 왕복 요청도 성공했습니다. 상세 결과는 `eval/results/kharakteres-audio-live.json`에 있습니다.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python eval/kharakteres_browser_smoke.py
# API 호출 없는 브라우저 검증: 모의 마이크 녹음기와 STT/TTS 응답
.venv/bin/python eval/kharakteres_audio_smoke.py
# 실제 TTS → STT 왕복 검증도 포함 (기존 OpenAI API 계정 사용)
.venv/bin/python eval/kharakteres_audio_smoke.py --live
```

모든 검증은 임시 DB·별도 포트를 사용합니다. `--live`의 한국어 TTS 음성은 `eval/results/kharakteres-audio-live.wav`에 시험 산출물로만 저장합니다. 브라우저 마이크 검증은 실제 사용자의 마이크 대신 모의 녹음기를 사용하며, 실제 장치·권한은 사용자 환경에서 추가 확인이 필요합니다.

## 콘텐츠 필터·벡터 RAG 개선

실제 실행 경로에 공통 콘텐츠 필터와 로컬 다국어 벡터 검색을 연결했습니다. 구성·판정 범위·한계와 MCP/Multi-Agent 도입 판단은 [별도 문서](SAFETY_RAG_MCP.md)를 참조하세요. 목록에서 **검색 방식 → 의미 검색 · 벡터**를 선택할 수 있습니다. API 응답의 `retrieval.mode`와 화면 안내에서 벡터 검색 또는 대체 조회를 구분합니다.

```dotenv
# 실제 모드 기본값. fake는 rules 및 벡터 비활성화
CONTENT_FILTER_MODE=model
SPELL_VECTOR_ENABLED=1
SPELL_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
SPELL_RAG_MIN_SCORE=0.25
SPELL_RETRIEVAL_TIMEOUT_SECONDS=25
```

콘텐츠 분류 모델은 기존 검사 LLM 설정을 사용합니다. 모델 분류가 실패하면 요청을 중단합니다. 단어 규칙만 쓰려면 `CONTENT_FILTER_MODE=rules`로 설정하며 문맥 분류의 보호 범위가 줄어듭니다.

[새 회귀 테스트 쿼리](regression_test_queries.md)와 [Git 업로드 안내](GIT_UPLOAD.md)도 갱신했습니다.
