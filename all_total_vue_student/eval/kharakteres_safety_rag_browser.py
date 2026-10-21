"""Actual ONNX semantic search and content-block UI in an isolated fake-LLM server.

Historical experiment: predates account-aware regression coverage. Review login
handling before rerunning; old results do not certify the current full UI flow.
For current fixed-data quantitative evaluation use kharakteres_benchmark.py.
"""

import os
import socket
import subprocess
import tempfile
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, expect
from kharakteres_browser_smoke import stop, wait_ready

root = Path(__file__).resolve().parents[1]
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
base = f"http://127.0.0.1:{port}"
with tempfile.TemporaryDirectory() as tmp:
    env = {
        **os.environ,
        "PORT": str(port),
        "LLM_BACKEND": "fake",
        "SPELL_VECTOR_ENABLED": "1",
        "CONTENT_FILTER_MODE": "rules",
        "SERVICE_MODE": "spells",
        "SPELL_DB_PATH": tmp + "/spell.sqlite",
        "LANGCHAIN_TRACING_V2": "false",
        "LANGSMITH_TRACING": "false",
    }
    with open(tmp + "/server.log", "w+") as log:
        process = subprocess.Popen(
            [str(root / ".venv/bin/python"), "server.py"],
            cwd=root,
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            wait_ready(base, process)
            with httpx.Client(base_url=base, timeout=40) as client:
                for name, effect, world in [
                    (
                        "여명의 봉합",
                        "다친 사람의 상처를 치료하고 출혈을 멈춘다",
                        "달의 세계",
                    ),
                    ("불의 폭발", "거대한 불꽃 폭발로 적을 공격한다", "달의 세계"),
                    ("다른 세계의 치유", "부상자의 몸을 회복시킨다", "다른 세계"),
                ]:
                    response = client.post(
                        "/api/spells",
                        json={
                            "name": name,
                            "incantation": name + " 깨어나라",
                            "language": "ko",
                            "elements": ["light"],
                            "effect": effect,
                            "world": world,
                        },
                    )
                    assert response.status_code == 201, response.text
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                        headless=True,
                    )
                    page = browser.new_page(viewport={"width": 1440, "height": 1080})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(base)
                    expect(page.locator(".spell-card")).to_have_count(3)
                    page.locator("#world-filter").select_option("달의 세계")
                    page.get_by_label("검색 방식", exact=True).select_option("semantic")
                    page.get_by_label("주문 검색", exact=True).fill(
                        "부상자의 몸을 회복시키는 마법"
                    )
                    expect(
                        page.get_by_text(
                            "의미 검색 · sentence-transformers/", exact=False
                        )
                    ).to_be_visible(timeout=35000)
                    expect(page.locator(".spell-card").first).to_contain_text(
                        "여명의 봉합"
                    )
                    assert (
                        "다른 세계의 치유"
                        not in page.locator(".spell-grid").inner_text()
                    )
                    page.screenshot(
                        path=str(root / "eval/results/kharakteres-semantic-search.png"),
                        full_page=True,
                    )
                    page.get_by_role("button", name="＋ 직접 기록", exact=True).click()
                    page.locator("#edit-name").fill("씨발")
                    page.locator("#edit-incantation").fill("빛이여 깨어나라")
                    page.locator("#edit-effect").fill("작은 방을 밝힌다")
                    page.get_by_role("button", name="서고에 저장", exact=True).click()
                    expect(
                        page.get_by_text(
                            "욕설·모욕이 포함되어 처리하지 않았습니다.", exact=False
                        )
                    ).to_be_visible()
                    assert client.get("/api/spells").json()["total"] == 3
                    page.get_by_role("button", name="닫기", exact=True).click()
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    )
                    assert not errors, errors
                    browser.close()
                print(
                    "Actual vector semantic search/world filter/content-block UI/mobile PASS"
                )
        except BaseException:
            log.flush()
            log.seek(0)
            print(log.read()[-2000:])
            raise
        finally:
            stop(process)
