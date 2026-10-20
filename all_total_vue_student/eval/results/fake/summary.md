# 개선 전후 평가 결과

Backend: fake; 사례 15개 × 3회

| 모드 | 대상 처리 정확도 | Runbook recall | Runbook precision | 요청 중앙값(초) | 오류 |
|---|---:|---:|---:|---:|---:|
| baseline | 13.3% | 50.0% | 60.0% | 0.7596 | 0 |
| improved | 100.0% | 100.0% | 100.0% | 0.053 | 0 |

주의: fake는 제어 흐름 검증입니다. 기준선의 인위적 지연, 사례 구성, 실제 모델 차이를 고려하세요. 지표 정의는 eval/README.md를 참조하세요.

Batch ID: 3d64ffc7-cbfb-4087-8ce3-07d729970ade
