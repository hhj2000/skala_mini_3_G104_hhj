# Kharakteres 검증

고정 데이터셋으로 검색·생성·충돌 검토의 기능 유무를 비교합니다. 미니 프로젝트에서 개선 효과와 한계를 설명할 평가 체계를 갖췄으며, 재현 가능한 평가와 서비스 성능의 충분함은 구분합니다. [평가 방법·수준 판단](../doc/EVALUATION.md)과 [과제 기준 대조](../doc/ASSIGNMENT_REVIEW.md)를 참고합니다.

## 현재 검증과 실측

현재 전체 회귀는 **pytest 152개·SSE 클라이언트 5개**입니다. 로그인 유지·단일 세션·언어 목록의 최신 스모크를 아래에 안내합니다. 고정 데이터 평가 당시에는 pytest 105개·SSE 클라이언트 4개·격리 컨테이너 스모크를 기록했습니다. 실제 OpenAI 핵심 함수 평가 208개 결과의 지표·사례 완전성도 재계산했습니다. [확정 보고서](results/kharakteres-benchmark-20261021/report.md), [자동 테스트 기록](results/kharakteres-benchmark-20261021/validation.json), [컨테이너 기록](results/kharakteres-benchmark-20261021/container-smoke.json)을 확인하세요.

검색 Recall@3는 70.6%, Precision@3는 24.1%이며, AI 의미 충돌 검토 P/R/F1은 0.625/1.000/0.769였습니다. 무정답 오검색과 충돌 오탐이 남아 있고 생성 품질 향상은 확인되지 않았습니다. 작은 합성 세트의 결과이며 전체 사용자 환경이나 고전어 정확도를 인증하지 않습니다.

## 재실행

프로젝트 루트에서 새 결과 폴더를 지정합니다. 검색은 LLM fake 모드에서도 실제 ONNX 임베딩을 사용합니다. 모델 파일은 첫 실행에 내려받을 수 있습니다.

```bash
# 외부 LLM 호출 없이 검색·규칙 검토 비교
.venv/bin/python eval/kharakteres_benchmark.py --tasks retrieval conflicts --repeat 2 --output eval/results/my-local-eval
# 실제 API 사용료 발생: 동일 모델 생성 대조·AI 검토·블라인드 judge
.venv/bin/python eval/kharakteres_benchmark.py --backend openai --tasks retrieval conflicts generation --judge --repeat 2 --max-model-calls 80 --output eval/results/my-model-eval
# API 호출 없이 누락·중복·지표·통계 재계산
.venv/bin/python eval/audit_kharakteres_report.py eval/results/my-model-eval/report.json
# 실제 가입을 거치는 API/기능·지표 계산 회귀
.venv/bin/python -m pytest -q
node --test tests/test_stream_client.cjs
```

종료 코드 0과 audit 통과는 실험 완료·기록 일관성을 뜻하며 품질 목표 통과 판정이 아닙니다. 오류·무정답·오탐·미탐과 채점 이유를 함께 확인합니다. Docker 격리 검사의 재현 명령도 [평가 문서](../doc/EVALUATION.md#docker-격리-스모크-재현)에 있습니다.

## 기존 단일 요청·브라우저 실험

아래 스크립트와 결과는 별도의 과거 실험입니다. 특히 브라우저/HTTP 스크립트에는 계정 도입 이전 흐름이 있어 로그인 처리에 맞게 수정하기 전에는 최신 기능 통과 근거로 사용하지 않습니다. 실제 음성·외부 사전·브라우저 전체·LangSmith를 최신 계정 구조에서 모두 재검증한 것은 아닙니다.

| 파일 | 실험 범위 |
|---|---|
| `kharakteres_browser_smoke.py` | CRUD·중복·필터·모바일·재시작 보존 UI |
| `kharakteres_stream_smoke.py` | 지연된 모의 공급자와 SSE 단계·토큰·취소·모바일 |
| `kharakteres_audio_smoke.py` | 인공 언어·음성 입력·선택/전체 TTS UI, 기본 모의 오디오 |
| `kharakteres_safety_rag_browser.py` | 실제 ONNX 의미 검색·세계관 필터·콘텐츠 차단 UI |
| `kharakteres_rag_live.py` | 실제 모델 안전 판정·검색·생성의 단일 스모크, 고정 데이터 정량 평가와 별개 |
| `kharakteres_language_smoke.py` | 실제 모델 언어·출처 UI 실험 |
| `kharakteres_stream_live.py` | 실제 모델 SSE/추적 단일 요청 실험 |
| `git_upload_audit.py` | Git 후보 크기·큰 과거 객체·일부 키 패턴 확인, 업로드 없음 |

과거 결과를 사용할 때는 실행 시점·모델·모의 공급자 여부·인증 구조를 함께 설명합니다. 최신 정량 비교는 `kharakteres_benchmark.py`를 기준으로 합니다. 실제 모델/음성 API를 호출하는 실험에는 사용료가 발생할 수 있습니다.

## 보존한 BASE 비교

`run_eval.py`, `compare_context.py`, `cases.json`, `baseline_manifest.json`과 과거 결과는 장애 진단 기능의 비교 재현에 사용합니다. 현재 주문 서비스의 기능·품질 점수와 직접 합산하지 않습니다. 상세 조건은 [BASE 평가 기록](../doc/archive/base/EVALUATION.md), 화면 재현은 [보관 안내](../archive/README.md)를 참고하세요.

## Docker 웹 출처 추가 검증

정량 평가 이후 웹 출처 제공자 분리를 추가해 pytest 115개와 실제 Docker API·저장·Vue 렌더링을 확인했습니다. `kharakteres_dictionary_live.py`는 빈 계정 DB의 별도 인스턴스에서 4언어 사전 조회를 수행하며 LLM/음성은 호출하지 않습니다. [설정과 재현](../doc/WEB_SOURCES.md), [원본 결과](results/kharakteres-dictionary-docker-20261021.json)를 참고하세요.

## 추가 언어 등록 검증

과거 내부 기본 등록을 13개로 확장했을 때 pytest 131개와 실제 OpenAI의 이탈리아어·고대 교회 슬라브어 해석·생성·저장·사전 연결을 확인했습니다. `kharakteres_language_registry_live.py`는 API 사용료가 발생할 수 있는 별도 단일 요청 스모크이며 고정 데이터셋 품질 점수와 구분합니다. [지원 범위](../doc/LANGUAGES.md)와 [결과](results/kharakteres-language-registry-20261021.json)를 참고하세요.

## 확장 언어 카탈로그 검증

목록 확장 당시 pytest 143개 통과. 현재 전체 회귀는 152개입니다. `tests/test_language_catalog.py`가 자연어/수어·특수/인공어 구분, 코드 병합, 오프라인·파일/메모리 캐시, 외부 실패·403·Retry-After, 검색/페이지와 모델 후보 크기를 검사합니다. `kharakteres_expanded_languages_smoke.py`는 별도의 빈 서버에서 실제 목록 갱신·3언어 사전·저장과 데스크톱/모바일 Vue 흐름을 확인합니다. 생성/음성 API는 호출하지 않습니다. 실제 생성은 `kharakteres_language_registry_live.py --extended`로 별도 확인했으며 API 사용료가 발생할 수 있습니다. [범위와 산출물](../doc/LANGUAGES.md#검증과-적용)을 참고하세요.

### 한국어 이름 기준 지원 범위 정리 (2026-10-21)

현재 언어 목록은 한글 이름이 등록된 자연어 **229개**만 가나다순으로 제공합니다. `kharakteres_expanded_languages_smoke.py`는 이 수·한국어 이름·전체 정렬·데스크톱 필터/버튼 높이·모바일 배치를 검사합니다. 갱신은 사전 가용성만 바꾸며 지원 범위는 고정합니다. 이전 7,737개 목록의 JSON/PNG는 당시 결과로 보존하고, 당시 결과는 `kharakteres-korean-languages-{local,docker}-20261021.json`입니다.

### 고전 언어·로그인 유지 (2026-10-21)

pytest 146개를 통과했습니다. 언어 브라우저 스모크는 고전 필터 17개와 브라우저 컨텍스트 재생성 후 로그인 복원도 검사합니다. 언어·세션 복원 결과는 `kharakteres-session-classical-{local,docker}-20261021.json`입니다. Docker 기록의 `docker_lifecycle`은 별도 테스트 볼륨으로 실제 컨테이너를 재시작하여 세션/주문 보존과 로그아웃 토큰 무효화를 재확인한 결과입니다.


### 동일 계정 중복 로그인 (2026-10-21)

`kharakteres_single_session_smoke.py`는 빈 임시 서버에만 실행합니다. Chromium의 독립 컨텍스트 2개에서 새 로그인 우선, 이전 창 로그인 화면 전환, 이전 쿠키 API 차단, 틀린 비밀번호/다른 계정의 영향 없음을 검사합니다. 모델·웹 사전·음성 호출은 없습니다. 최신 결과는 `kharakteres-single-session-{local,docker}-20261021.json`입니다. Docker의 `docker_lifecycle`은 영구 테스트 볼륨과 실제 컨테이너 재시작 후 최신 쿠키 유지·이전 쿠키 차단·로그아웃 후 재사용 차단 결과입니다. 세션/암호는 결과 파일에 기록하지 않습니다. pytest 152개, SSE 클라이언트 5개도 통과했습니다.

```bash
.venv/bin/python eval/kharakteres_single_session_smoke.py --base-url http://127.0.0.1:18120 --output eval/results/my-single-session-check.json
```
