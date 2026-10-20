# Kharakteres 검증

프로젝트 루트에서 실행합니다. 자동 테스트와 브라우저 검증은 임시 주문 DB를 사용합니다.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python eval/kharakteres_browser_smoke.py
.venv/bin/python eval/kharakteres_stream_smoke.py
node --test tests/test_stream_client.cjs
.venv/bin/python eval/kharakteres_audio_smoke.py
.venv/bin/python eval/kharakteres_safety_rag_browser.py
```

- `kharakteres_stream_smoke.py`: 지연된 모의 공급자와 실제 SSE 경로로 토큰 선도착·단계 표시·취소·연결 끊김·모바일 확인
- `kharakteres_browser_smoke.py`: CRUD·중복·필터·모바일·서버 재시작 보존
- `kharakteres_audio_smoke.py`: 인공 언어·선택/전체 읽기·음성 입력 UI (기본 모의 오디오, 실제 마이크 검증 아님)
- `kharakteres_safety_rag_browser.py`: 실제 ONNX 의미 검색·세계관 범위·차단 UI (임베딩 모델 다운로드 가능)
- `git_upload_audit.py`: Git 후보 크기·큰 과거 객체·일부 키 패턴 확인, 업로드 없음

다음은 실제 모델/API와 네트워크를 사용하는 선택 실험입니다. OpenAI 요청에는 사용료가 발생할 수 있습니다.

```bash
LLM_BACKEND=openai .venv/bin/python eval/kharakteres_rag_live.py
.venv/bin/python eval/kharakteres_stream_live.py openai
.venv/bin/python eval/kharakteres_stream_live.py ollama
.venv/bin/python eval/kharakteres_language_smoke.py
.venv/bin/python eval/kharakteres_audio_smoke.py --live
```

`eval/results/kharakteres-*`에 현재 주제의 결과·화면이 있습니다. 나머지 BASE 비교 결과는 과거 증거이므로 현재 품질 측정과 구분합니다.

## 보존한 BASE 비교

`run_eval.py`, `compare_context.py`, `cases.json`, `baseline_manifest.json`과 과거 결과는 기존 진단 기능의 비교 재현에 사용합니다. 상세 조건은 [BASE 평가 기록](../doc/archive/base/EVALUATION.md), 화면 재현은 [보관 안내](../archive/README.md)를 참고하세요.
