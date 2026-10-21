# Kharakteres 검증

고정 데이터셋으로 검색·생성·충돌 검토의 기능 유무를 비교합니다. 미니 프로젝트에서 개선 효과와 한계를 설명할 평가 체계를 갖췄으며, 재현 가능한 평가와 서비스 성능의 충분함은 구분합니다. [평가 방법·수준 판단](../doc/EVALUATION.md)과 [과제 기준 대조](../doc/ASSIGNMENT_REVIEW.md)를 참고합니다.

## 현재 검증과 실측

2026-10-21 기준 pytest 105개, SSE 클라이언트 4개, Docker 빌드와 격리 컨테이너 스모크를 통과했습니다. 실제 OpenAI 핵심 함수 평가 208개 결과의 지표·사례 완전성도 재계산했습니다. [확정 보고서](results/kharakteres-benchmark-20261021/report.md), [자동 테스트 기록](results/kharakteres-benchmark-20261021/validation.json), [컨테이너 기록](results/kharakteres-benchmark-20261021/container-smoke.json)을 확인하세요.

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
