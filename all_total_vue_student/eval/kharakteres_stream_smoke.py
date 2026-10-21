"""Delayed mock-provider browser and wire SSE checks, always using a temporary DB.

Historical experiment: predates account-aware regression coverage. Review login
handling before rerunning; old results do not certify the current full UI flow.
For current fixed-data quantitative evaluation use kharakteres_benchmark.py.
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

import httpx
from playwright.sync_api import sync_playwright, expect

from kharakteres_browser_smoke import stop, wait_ready

ROOT = Path(__file__).resolve().parents[1]


def check_wire(base):
    rows = []
    start = time.monotonic()
    kind = ""
    with httpx.stream("POST", base + "/api/generate/stream", json={
        "prompt": "빛으로 작은 상처를 치유한다", "language": "ko", "elements": ["light"],
    }, timeout=20) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                rows.append({"event": kind, "time": round(time.monotonic()-start, 3), "data": json.loads(line[6:])})
    assert rows[-1]["event"] == "done"
    first_token = next(row["time"] for row in rows if row["event"] == "token")
    assert rows[-1]["time"] - first_token > 1
    assert httpx.get(base + "/api/spells").json()["items"] == []
    return {"first_token_seconds": first_token, "done_seconds": rows[-1]["time"], "token_chunks": sum(row["event"] == "token" for row in rows)}


def check_browser(base):
    with sync_playwright() as p:
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        browser = p.chromium.launch(**({"executable_path": str(chrome)} if chrome.exists() else {}), headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1080})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base)
        page.get_by_role("button", name="달빛으로 잇는 작은 치유", exact=False).click()
        page.locator("#language-message").fill("한국어")
        page.get_by_role("button", name="언어 답장 보내기", exact=True).click()
        generate = page.get_by_role("button", name="✦ 주문 생성하기", exact=True)
        expect(generate).to_be_enabled()
        generate.click()
        preview = page.get_by_role("region", name="실시간 주문 미리보기")
        expect(preview.get_by_text("새벽의 치유", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="편집하고 저장하기 →")).to_have_count(0)
        expect(page.get_by_role("button", name="생성 중단")).to_be_visible()
        page.screenshot(path=str(ROOT / "eval/results/kharakteres-streaming.png"), full_page=True)
        verify_stage = page.locator('.generation-stages li.running', has_text="언어·발음 출처 확인")
        expect(verify_stage).to_be_visible(timeout=10000)
        expect(page.get_by_role("button", name="편집하고 저장하기 →")).to_be_disabled()
        expect(page.get_by_role("button", name="편집하고 저장하기 →")).to_be_enabled(timeout=10000)
        expect(page.locator('.generation-stages li.completed')).to_have_count(5)
        assert httpx.get(base + "/api/spells").json()["items"] == []
        # Cancellation clears partial tokens and cannot leave a savable draft.
        generate.click()
        expect(preview.get_by_text("새벽의 치유", exact=True)).to_be_visible()
        page.get_by_role("button", name="생성 중단").click()
        expect(page.get_by_text("생성을 중단했습니다. 주문은 저장되지 않았습니다.", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="편집하고 저장하기 →")).to_have_count(0)
        expect(preview).to_have_count(0)
        # A failed or interrupted transport is never retried as a second generation.
        page.route("**/api/generate/stream", lambda route: route.fulfill(status=200, content_type="text/event-stream", body='event: token\ndata: {"text":"test"}\n\n'))
        generate.click()
        expect(page.get_by_role("alert").filter(has_text="완료 전에 연결이 끊어졌습니다")).to_be_visible()
        expect(page.get_by_role("button", name="편집하고 저장하기 →")).to_have_count(0)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    (ROOT / "eval/results").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "LLM_BACKEND": "fake", "CONTENT_FILTER_MODE": "rules",
               "SPELL_VECTOR_ENABLED": "0", "SPELL_DB_PATH": tmp + "/spells.sqlite",
               "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false"}
        with open(tmp + "/server.log", "w+") as log:
            process = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "stream_fixture:app",
                "--app-dir", "tests", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True)
            try:
                wait_ready(base, process)
                result = check_wire(base)
                check_browser(base)
                (ROOT / "eval/results/kharakteres-stream-smoke.json").write_text(json.dumps({
                    "provider": "delayed mock (not a real LLM)", **result,
                    "browser": "partial fields, stages, cancellation, broken transport, mobile PASS",
                }, ensure_ascii=False, indent=2))
                print("SSE wire + browser live fields/stages/cancel/broken transport/mobile PASS", result)
            finally:
                stop(process)
