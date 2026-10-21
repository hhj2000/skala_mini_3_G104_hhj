# Kharakteres 고정 데이터셋 평가

완료: True / 실행: openai / split: test / 데이터 SHA256: `7ee87ae82607778145dc10764242e886a1d39ba35ec2783958ba6b59295bdc44`

fake 결과는 제어 흐름 검증이며 생성·언어·AI 충돌 품질 근거가 아닙니다. 비용은 기존 어댑터의 가상 단가 추정입니다.

| 과제 | 조건 | 사례/실행 | 오류율 | 평균 ms | 주요 수치 |
|---|---|---:|---:|---:|---|
| conflict_ai | model | 14/28 | 0.0% | 889.3 | precision=0.625, recall=1.000, f1=0.769, accuracy=0.769 |
| conflict_ai | no_findings | 14/28 | 0.0% | 0.0 | precision=0.000, recall=0.000, f1=0.000, accuracy=0.615 |
| conflict_rules | name_only | 14/28 | 0.0% | 0.0 | precision=1.000, recall=0.312, f1=0.476, accuracy=0.788 |
| conflict_rules | rules | 14/28 | 0.0% | 0.1 | precision=1.000, recall=1.000, f1=1.000, accuracy=1.000 |
| generation | no_context | 6/12 | 0.0% | 2610.3 | contract_pass=1.000; judge=3.875 (coverage=100%) |
| generation | vector | 6/12 | 0.0% | 2419.9 | contract_pass=1.000; judge=3.8541666666666665 (coverage=100%) |
| retrieval | keyword | 18/36 | 0.0% | 0.2 | ndcg_at_k=0.000, precision_at_k=0.000, recall_at_k=0.000 |
| retrieval | vector | 18/36 | 0.0% | 8.0 | ndcg_at_k=0.611, precision_at_k=0.241, recall_at_k=0.706 |

## 대응 비교 (차이 = After - Before)

| 과제/지표 | 비교 | 평균 차이 | 사례 bootstrap 95% 구간 | n |
|---|---|---:|---|---:|
| retrieval/recall_at_k | keyword → vector | 0.706 | [0.500, 0.882] | 17 |
| retrieval/precision_at_k | keyword → vector | 0.241 | [0.167, 0.296] | 18 |
| retrieval/ndcg_at_k | keyword → vector | 0.611 | [0.413, 0.796] | 17 |
| retrieval/mrr | keyword → vector | 0.608 | [0.402, 0.794] | 17 |
| retrieval/no_answer_correct | keyword → vector | -1.000 | [-1.000, -1.000] | 1 |
| conflict_rules/exact_match | name_only → rules | 0.714 | [0.429, 0.929] | 14 |
| conflict_rules/f1 | name_only → rules | 0.524 | [0.286, 0.762] | 14 |
| conflict_ai/exact_match | no_findings → model | 0.143 | [-0.214, 0.500] | 14 |
| conflict_ai/f1 | no_findings → model | 0.357 | [0.143, 0.643] | 14 |
| generation/contract_pass | no_context → vector | 0.000 | [0.000, 0.000] | 6 |
| generation/judge_score | no_context → vector | -0.021 | [-0.062, 0.000] | 6 |
| generation/judge_criteria_rate | no_context → vector | 0.000 | [0.000, 0.000] | 6 |

검색 라벨이 없는 질의는 recall/nDCG 평균에서 제외하고 무정답 거절 정확도로 별도 평가합니다. 오류는 rows에 남고 성공률·계약 검사에서 실패로 계산합니다. 작은 합성 데이터셋의 CI는 일반화 성능이나 유의성 보장이 아닙니다.
