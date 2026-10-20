# Kharakteres 실행 안내

프로젝트 루트에서 실행합니다.

```bash
bash sh/run_kharakteres.sh openai
# 또는
bash sh/run_kharakteres.sh ollama
# 외부 LLM 없는 데모
bash sh/run_kharakteres.sh fake
```

`[준비 완료]` 이후 http://localhost:8100/ 에 접속합니다. 화면과 API가 같은 서버에서 제공되므로 별도 프런트엔드 터미널은 필요 없습니다. 실행 터미널은 유지하고 종료할 때 Ctrl+C를 누릅니다.

## 연결·저장 경로 확인

```bash
bash sh/run_kharakteres.sh openai --check
```

이 검사는 의존성·주문 DB 경로 및 쓰기 권한·모델 정보 조회를 확인합니다. 생성 API의 잔액이나 실제 생성 품질까지 확인하지 않습니다. 실제 셸 환경 변수가 `.env`보다 우선합니다.

기본 DB는 `data/kharakteres.sqlite`입니다. `SPELL_DB_PATH`는 생략하거나 이 경로로 지정합니다. 상대 경로는 프로젝트 루트 기준이며 `/absolute/path/...`는 유효한 사용자 경로가 아닙니다. 기존 DB를 변경하려면 사용하던 파일 경로를 유지하세요.

## 포트 충돌·비교 실행

기존 서버는 해당 터미널에서 Ctrl+C로 종료합니다. 다른 프로세스를 자동으로 종료하지 않습니다.

```bash
lsof -nP -iTCP:8100 -sTCP:LISTEN
# 별도 통합 인스턴스가 필요한 경우
PORT=8101 bash sh/run_kharakteres.sh openai
```

두 번째 인스턴스는 http://localhost:8101/ 로 접속합니다. 테스트용 주문을 분리하려면 `SPELL_DB_PATH`도 별도 파일로 지정합니다. 포트만 바꾸면 동일 DB를 공유합니다.

## 처음 준비할 때

```bash
bash sh/setup_venv.sh
cp -n .env.example .env
# .env에 본인 API 키와 모델 설정
```

테스트 도구는 `.venv/bin/python -m pip install -r requirements-dev.txt`, 브라우저 도구는 `requirements-browser.txt`로 설치합니다. Ollama 준비는 `bash sh/setup_ollama.sh`를 사용합니다.

자세한 기능은 [서비스 안내](KHARAKTERES.md), BASE 재현은 [보관 안내](../archive/README.md)를 참고하세요.
