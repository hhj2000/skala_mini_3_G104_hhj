"""Visible preflight + foreground server supervisor. Never prints secrets or kills existing servers."""

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parents[1]


class StartupError(RuntimeError):
    pass


def say(message):
    print(message, flush=True)


def check_dependencies():
    modules = [
        "dotenv", "httpx", "fastapi", "uvicorn", "langgraph", "langsmith", "fastembed"
    ]
    if os.getenv("SERVICE_MODE", "spells") == "incident":
        modules.extend(["mcp", "fastmcp"])
    missing = [
        name
        for name in modules
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        raise StartupError(
            "필요 패키지가 없습니다: "
            + ", ".join(missing)
            + "\n복구: bash sh/setup_venv.sh"
        )


def check_port(port):
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
    except OSError as exc:
        raise StartupError(
            f"포트 {port}를 사용할 수 없습니다. 이미 실행 중인 서버가 있는지 확인하세요.\n확인: lsof -nP -iTCP:{port} -sTCP:LISTEN\nOllama와 OpenAI는 하나만 실행하세요. 전환하려면 기존 터미널에서 Ctrl+C.\n별도 포트: PORT=8101 bash sh/run_kharakteres.sh openai (접속: http://localhost:8101/)"
        ) from exc


def openai_error(status):
    return {
        401: "API 키 인증 실패: .env의 OPENAI_API_KEY를 확인하세요.",
        403: "모델 조회 권한/네트워크 정책을 확인하세요.",
        404: "설정한 모델에 접근할 수 없습니다. 모델 이름과 권한을 확인하세요.",
        429: "요청 한도 또는 크레딧/사용량 제한을 확인하세요.",
    }.get(status, "OpenAI 서비스 응답을 확인하세요.")


def check_openai(client):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or "..." in key:
        raise StartupError(
            "OPENAI_API_KEY가 비어 있거나 예시 값입니다. .env에 실제 키를 설정하세요."
        )
    models = list(
        dict.fromkeys(
            [
                os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini"),
                os.getenv("OPENAI_QUALITY_MODEL", "gpt-4o"),
            ]
        )
    )
    for model in models:
        try:
            response = client.get(
                "https://api.openai.com/v1/models/" + quote(model, safe=""),
                headers={"Authorization": "Bearer " + key},
            )
        except Exception as exc:
            raise StartupError(
                f"OpenAI 연결 실패 ({type(exc).__name__}). 인터넷·프록시·방화벽을 확인하세요."
            ) from None
        if response.status_code != 200:
            raise StartupError(
                f"OpenAI 모델 조회 HTTP {response.status_code}: "
                + openai_error(response.status_code)
            )
        say(f"  OpenAI 모델 접근 OK: {model}")
    say(
        "  모델 정보 조회만 수행했습니다. 생성 API의 잔액/한도까지 보장하는 검사는 아닙니다."
    )


def check_ollama(client, allow_start=False):
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    daemon = None
    try:
        response = client.get(base + "/api/tags")
        response.raise_for_status()
    except Exception:
        local = urlparse(base).hostname in {"localhost", "127.0.0.1"}
        executable = shutil.which("ollama")
        if not (
            allow_start
            and local
            and executable
            and os.getenv("AUTO_START_OLLAMA", "1") != "0"
        ):
            raise StartupError(
                "Ollama에 연결할 수 없습니다. 다른 터미널에서 ollama serve를 실행하세요.\n주소: "
                + base
            ) from None
        say("  Ollama가 꺼져 있어 시작합니다 (최대 15초 대기)…")
        (ROOT / ".cache").mkdir(exist_ok=True)
        with (ROOT / ".cache/ollama.log").open("a") as log:
            daemon = subprocess.Popen(
                [executable, "serve"],
                stdout=log,
                stderr=log,
                env={**os.environ, "OLLAMA_HOST": urlparse(base).netloc},
            )
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    response = client.get(base + "/api/tags")
                    response.raise_for_status()
                    break
                except Exception:
                    if daemon.poll() is not None or time.monotonic() > deadline:
                        raise StartupError(
                            "Ollama 시작 실패. .cache/ollama.log를 확인하세요."
                        )
                    time.sleep(0.3)
        except BaseException:
            stop_child(daemon)
            raise
    try:
        available = {
            m.get("name", m.get("model")) for m in response.json().get("models", [])
        }
        models = list(
            dict.fromkeys(
                [
                    os.getenv("OLLAMA_FAST_MODEL", "qwen3:0.6b"),
                    os.getenv("OLLAMA_QUALITY_MODEL", "qwen3:8b"),
                ]
            )
        )
        missing = [
            m for m in models if m not in available and m + ":latest" not in available
        ]
        if missing:
            raise StartupError(
                "Ollama 모델이 설치되지 않았습니다. 아래 명령 후 다시 실행하세요.\n"
                + "\n".join("ollama pull " + m for m in missing)
            )
        say("  Ollama 연결/설치 모델 OK: " + ", ".join(models))
        if os.getenv("AGENT_MODE", "improved") == "improved":
            say(
                f"  응답 설정: think={os.getenv('OLLAMA_THINK', 'false')}, 최대 생성={os.getenv('OLLAMA_NUM_PREDICT', '768')} tokens"
            )
        say("  실제 모델 로딩은 첫 질문 때 수행하므로 첫 응답이 더 느릴 수 있습니다.")
        return daemon
    except BaseException:
        stop_child(daemon)
        raise


def stop_child(child):
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def main(argv=None):
    parser = argparse.ArgumentParser(description="AI Agent 시작/연결 진단")
    parser.add_argument(
        "--backend",
        choices=["fake", "ollama", "openai"],
        default=os.getenv("LLM_BACKEND", "fake"),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="연결만 검사하고 종료 (서버를 실행하지 않음)",
    )
    parser.add_argument(
        "--skip-backend-check",
        action="store_true",
        help="모델 연결 검사를 건너뛰고 서버만 실행",
    )
    args = parser.parse_args(argv)
    server = daemon = None
    try:
        say("[1/3] Python 환경·설정 확인…")
        check_dependencies()
        from dotenv import load_dotenv
        import httpx

        load_dotenv(ROOT / ".env")
        os.environ["LLM_BACKEND"] = args.backend
        mode = os.environ.setdefault("AGENT_MODE", "improved")
        if os.getenv("SERVICE_MODE", "spells") == "spells":
            from kharakteres.config import prepare_spell_storage

            say(f"  주문 DB: {prepare_spell_storage()}")
        if mode not in {"improved", "baseline"}:
            raise StartupError("AGENT_MODE는 improved 또는 baseline이어야 합니다.")
        port = int(os.getenv("PORT", "8100"))
        if not 1 <= port <= 65535:
            raise StartupError("PORT는 1~65535 범위여야 합니다.")
        os.environ.setdefault(
            "LANGCHAIN_PROJECT", f"mini-project-{args.backend}-{mode}"
        )
        say(f"  backend={args.backend} · mode={mode} · Python={sys.executable}")
        say(
            "[2/3] "
            + ("모델 연결만 검사…" if args.check else f"포트 {port} / 모델 연결 검사…")
        )
        if not args.check:
            check_port(port)
        with httpx.Client(timeout=httpx.Timeout(5, connect=3)) as client:
            if args.skip_backend_check:
                say("  모델 연결 검사 생략")
            elif args.backend == "ollama":
                daemon = check_ollama(client, allow_start=not args.check)
            elif args.backend == "openai":
                check_openai(client)
            else:
                say("  fake: 외부 생성 모델 없이 실행합니다.")
        if args.check:
            say("[완료] 연결 검사 통과. 서버를 실행하려면 --check를 빼세요.")
            return 0
        say(
            "[3/3] Kharakteres 웹 서버 시작…"
            if os.getenv("SERVICE_MODE", "spells") == "spells"
            else "[3/3] FastAPI / MCP 서버 시작…"
        )
        say("이 터미널은 서버가 실행되는 동안 유지됩니다. 종료: Ctrl+C")
        server = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "server.py")], cwd=ROOT
        )
        with httpx.Client(timeout=0.5) as client:
            deadline = time.monotonic() + float(
                os.getenv("STARTUP_TIMEOUT_SECONDS", "30")
            )
            while True:
                if server.poll() is not None:
                    raise StartupError(
                        "서버가 준비되기 전에 종료되었습니다. 위 오류 로그를 확인하세요."
                    )
                try:
                    health = client.get(f"http://127.0.0.1:{port}/health")
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise StartupError(
                        "서버 준비 제한 시간을 초과했습니다. 마지막 MCP/서버 로그를 확인하세요."
                    )
                time.sleep(0.2)
        say(f"[준비 완료] http://127.0.0.1:{port}/health")
        if os.getenv("SERVICE_MODE", "spells") == "spells":
            say(
                f"Kharakteres 바로 접속: http://localhost:{port}/ (별도 프런트엔드 실행 없이 사용 가능)"
            )
        else:
            say("Base 진단 API 준비 완료. 보존된 화면 실행 방법: archive/README.md")
        return server.wait()
    except KeyboardInterrupt:
        say("\n서버를 종료합니다.")
        return 0
    except (StartupError, ValueError) as exc:
        say("[실행 중단] " + str(exc))
        return 1
    finally:
        stop_child(server)
        stop_child(daemon)


def handle_termination(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_termination)
    raise SystemExit(main())
