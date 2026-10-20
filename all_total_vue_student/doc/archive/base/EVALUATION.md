> BASE 장애 진단 프로젝트의 과거 기록입니다. 아래 실행 명령은 당시 기준이며, 보존 코드의 현재 실행 방법은 [보관 안내](../../../archive/README.md)를 확인하세요.

# 개선 전후 비교

## 기준선

`agent/baseline_graph.py`는 수정 전 `agent/graph.py`의 복사본입니다. 실습용 v1은 기능이 더 적어 비교 대상으로 삼지 않습니다.
`baseline_manifest.json`에 원본 그래프와 공통 LLM 어댑터의 SHA-256을 저장했습니다.
baseline과 improved는 같은 모니터링 MCP 구현을 사용하며, `MONITORING_FIXED=1`로 값·시각을 고정합니다.
일부 공통 기반(MCP 오류 전달, 시간 고정 옵션)은 보강했으므로 당시 전체 애플리케이션의 바이트 단위 스냅샷은 아닙니다.

## 평가 조건

- 15개 고정 사례. 단일/복수/정상/미지정/미등록/혼합/이름 경계/일반 대화/시스템명만 입력.
- 같은 backend와 같은 fast/quality 모델로 비교. 기대값은 `cases.json`에 명시.
- 검색 인덱스와 임베딩 모델 초기화는 요청 지연에서 제외하고 `warmup_s`로 따로 기록.
- `--repeats`로 반복하고, 홀수 반복에는 실행 순서를 반대로 바꿔 캐시 편향 완화.
- fake: 결정론적 제어 흐름 회귀. 원본 fake가 web-01을 추가 조사하는 동작도 그대로 포함. 이 때문에 **정확히 지정한 대상만 조사**하는 엄격한 지표에서 기준선 점수가 낮아짐. 이를 실모델의 일반 정확도라고 발표하면 안 됨.
- 실제 모델 평가는 별도 폴더로 저장. 소규모 1회 smoke 결과만으로 일반화 금지.

## 지표

1. **target_accuracy**: 명확한 입력은 조사 대상 집합이 정답과 정확히 같아야 함. 확인이 필요한 입력은 모니터링 호출 없이 확인 질문을 해야 함. 일반 대화는 chat으로 처리해야 함.
2. **runbook_recall**: 해당 사례에 필요한 매뉴얼 유형 중 확보한 비율. 필요한 매뉴얼이 없으면 잘못된 매뉴얼도 조회하지 않은 경우 1, 조회한 경우 0.
3. **runbook_precision**: 검색한 매뉴얼 유형 중 정답 유형의 비율. 검색이 없고 정답도 없을 때 1.
4. **latency_s**: 그래프 요청 시간. 데이터셋 전체 중앙값은 빠른 확인 질문·인사 응답이 섞인 값임. 개별 사례도 함께 확인.
5. **validation_attempts/retry_count**: 검증 재작성·MCP 재시도 횟수.

매뉴얼 점수는 **사례 단위 유형 집합**의 비교입니다. 시스템별 근거 연결은 별도 그래프 테스트에서 확인합니다.
표시된 cost는 기존 교육용 단가 또는 문자 기반 추정치이며 실제 청구액이 아닙니다.

## 명령

```bash
.venv/bin/python eval/run_eval.py --backend fake --repeats 3
.venv/bin/python eval/run_eval.py --backend fake --repeats 3 --trace
.venv/bin/python eval/run_eval.py --backend ollama --repeats 1 \
  --case-ids cpu,multi-cpu-memory,unknown,missing,greeting \
  --trace --output eval/results/ollama
```

OpenAI 평가도 `--backend openai --output eval/results/openai`로 가능하며 API 비용이 발생합니다.

결과:
- `results.json`: 입력 식별자, 모드, 정확도, 시간, 오류, 답변/근거, Run ID.
- `results.csv`: 스프레드시트에서 비교할 수 있는 동일 데이터.
- `summary.json`: 평가 조건과 전체 지표.
- `summary.md`: 발표용으로 읽을 수 있는 지표 요약.

`--trace`를 붙이면 실제 LangSmith 프로젝트에 실행과 평가 feedback을 등록합니다.
화면에서 추적이 보이는 것과 평가 점수가 자동 생성되는 것은 별개입니다.
