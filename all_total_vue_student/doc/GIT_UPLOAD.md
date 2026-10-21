# GitHub 업로드 용량 및 push 안내

대상 저장소: `https://github.com/hhj2000/skala_mini_3_G104_hhj.git`, 현재 브랜치 `main`.

## 실제 점검

2026-10-21 재점검에서 Git 후보는 **약 14.0MB(268개 파일, ngrok 문서·그림·검증 결과 포함)**이며 최대 파일은 ISO 언어 자료 **876,207바이트(약 0.84MiB)**입니다. 50MiB·100MiB 초과 후보와 과거 100MiB 초과 blob, 검사 대상 키 패턴은 발견되지 않았습니다. 가상환경·계정/세션/주문 DB·모델 캐시는 후보에서 제외됩니다. 파일 수와 합계는 문서/실험 결과 추가에 따라 달라지므로 push 직전에 다시 검사합니다.

```bash
cd /Users/hyeongjunhan/skala_mini_3_G104_hhj/all_total_vue_student
.venv/bin/python eval/git_upload_audit.py
```

이 읽기 전용 도구는 저장소 루트에서 `.gitignore`를 적용한 추적/미추적 파일, 합계·최대 크기, 과거 Git 객체의 대형 blob과 일부 OpenAI 키 패턴을 확인합니다. 키 값은 출력하지 않습니다. 모든 종류의 비밀정보를 탐지하는 전용 보안 스캐너는 아니며, 실제 압축 push 크기·인증·원격 브랜치 상태도 보장하지 않습니다.

현재 규모에서는 **일반 Git으로 업로드 가능하며 Git LFS가 필요하지 않습니다.** 가상환경, `.env`와 `.env.*`(예제 제외), DB·WAL·벡터 캐시, `.cache`, `node_modules`는 제외합니다. 외부 FastEmbed 모델 캐시와 Ollama 모델도 저장소에 넣지 않습니다.

## GitHub 제한

- 일반 Git 파일: **50MiB 초과 경고, 100MiB 초과 차단**. [공식 파일 제한](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
- 한 번의 push: **2GB 제한**. 폴더의 디스크 크기와 push 전송 크기는 다릅니다. [공식 저장소 제한](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)
- 대형 파일이 꼭 필요하면 Git LFS 또는 별도 배포/다운로드를 사용합니다. LFS에도 계정별 저장·전송 한도와 파일 크기 제한이 있습니다. 모델은 다운로드/캐시 방식이 적합합니다.

## 현재 프로젝트 push 방법

저장소 루트에서 실행합니다. 이 작업에서는 실제 add·commit·push를 수행하지 않았습니다.

```bash
cd /Users/hyeongjunhan/skala_mini_3_G104_hhj
all_total_vue_student/.venv/bin/python all_total_vue_student/eval/git_upload_audit.py

git status --short
git add .gitignore README.md all_total_vue_student
git diff --cached --stat
git diff --cached --name-only
# .env, 개인 DB, .venv, 모델 파일이 없는지 확인

git commit -m "Build Kharakteres spell lexicon with speech, safety and vector RAG"
git push -u origin main
```

원격에 로컬에 없는 변경이 있어 push가 거절되면 먼저 `git fetch origin`으로 상황을 확인하고 변경을 통합합니다. 무조건 `--force`로 덮어쓰지 않습니다. 인증 실패는 파일 용량과 별개이므로 GitHub 로그인/SSH/토큰 설정을 확인합니다.

## 나중에 큰 파일이 생긴 경우

- 아직 추적하지 않은 캐시·모델: `.gitignore`에 제외하고 다시 점검합니다.
- 이미 스테이징한 불필요한 파일: `git restore --staged -- 경로`로 스테이징만 취소합니다. `.gitignore`는 이미 추적한 파일을 자동으로 제거하지 않습니다.
- 큰 파일을 이미 로컬 커밋에 넣었다면 뒤의 커밋에서 파일만 삭제해도 과거 blob은 남습니다. 어떤 커밋에 들어갔는지 확인한 후 백업하고 기록 정리 또는 LFS 이전이 필요합니다. 현재 저장소에서는 이 문제가 발견되지 않았고 기록을 수정하지 않았습니다.
- 꼭 버전 관리할 대형 자산만 선택해 LFS를 구성합니다. `git lfs install`, `git lfs track "assets/large/*.wav"`처럼 실제 필요 경로에 적용하고 `.gitattributes`와 파일을 함께 커밋합니다. 기존 커밋의 파일은 `track`만으로 자동 이전되지 않습니다.

## Git push와 Docker Hub push 구분

이 문서의 `git push`는 소스·문서·그림을 Git 저장소에 올립니다. `joonsdocker/kharakteres:latest`의 이미지 갱신은 별도의 빌드·tag·`docker push`이며 ngrok HTTPS 주소도 별도 호스트 프로세스에서 발급합니다. [Hub 갱신 명령](DOCKER_HUB.md), [ngrok 공유](NGROK_SHARING.md)를 참고하세요. Hub 웹페이지 Overview도 일반 이미지 push만으로 갱신되지는 않습니다.
