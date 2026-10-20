"""Optional real-provider SSE smoke. Uses temporary storage; API usage may be billed."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

import httpx
from dotenv import load_dotenv

from kharakteres_browser_smoke import stop, wait_ready

ROOT = Path(__file__).resolve().parents[1]


def run(backend):
    load_dotenv(ROOT / ".env")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    rows, received, result = [], [], None
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "PORT": str(port), "SPELL_DB_PATH": tmp + "/spells.sqlite",
               "SPELL_VECTOR_ENABLED": "0", "CONTENT_FILTER_MODE": "model",
               "LANGCHAIN_PROJECT": "kharakteres-sse-feedback", "LANGSMITH_PROJECT": "kharakteres-sse-feedback"}
        with open(tmp + "/server.log", "w+") as log:
            process = subprocess.Popen(["bash", "sh/run_kharakteres.sh", backend, "--skip-backend-check"],
                cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True)
            try:
                wait_ready(base, process)
                start = time.monotonic()
                kind = ""
                with httpx.stream("POST", base + "/api/generate/stream", json={
                    "prompt": "작은 방을 은은하게 밝히는 짧은 주문", "language": "ko",
                    "elements": ["light"], "limitations": "작은 방에서만 사용할 수 있다", "world": "SSE 검증 서고",
                }, timeout=240) as response:
                    assert response.status_code == 200
                    for line in response.iter_lines():
                        if line.startswith("event: "):
                            kind = line[7:]
                        elif line.startswith("data: "):
                            data = json.loads(line[6:])
                            rows.append({"event": kind, "time": round(time.monotonic()-start, 3),
                                         **({"stage": data["stage"], "status": data["status"]} if kind == "stage" else {})})
                            if kind == "token": received.append(data["text"])
                            if kind == "error": raise RuntimeError(data["message"])
                            if kind == "done": result = data
                assert result and received
                raw = json.loads("".join(received))
                assert raw["incantation"] == result["draft"]["incantation"]
                assert len([row for row in rows if row.get("status") == "completed"]) == 5
                assert httpx.get(base + "/api/spells").json()["items"] == []
            finally:
                stop(process)  # Flush trace batches before reading the remote trace.

    summary = {"backend": backend, "model": result["model"], "token_chunks": len(received),
               "first_token_seconds": next(row["time"] for row in rows if row["event"] == "token"),
               "done_seconds": rows[-1]["time"], "langsmith_run_id": result["langsmith_run_id"],
               "events": [row for row in rows if row["event"] != "token"],
               "verification_status": result["draft"]["verification"]["status"]}
    if result["langsmith_run_id"]:
        from langsmith import Client
        client = Client()
        root = client.read_run(result["langsmith_run_id"])
        children = list(client.list_runs(trace_id=root.trace_id))
        llms = [run for run in children if run.name == "spell.language_model"]
        summary["langsmith_token_events"] = sum(
            event.get("name") == "new_token" for run in llms for event in run.events or []
        )
        assert summary["langsmith_token_events"] == len(received)
    out = ROOT / f"eval/results/kharakteres-stream-{backend}-live.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in summary.items() if key != "events"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=["openai", "ollama"], default="openai", nargs="?")
    run(parser.parse_args().backend)
