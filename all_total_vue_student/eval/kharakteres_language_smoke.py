"""Real selected-LLM + live dictionary + browser smoke, isolated from the user's lexicon.
Run: .venv/bin/python eval/kharakteres_language_smoke.py (LLM_BACKEND=openai/ollama)
"""

import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from kharakteres_browser_smoke import stop, wait_ready
from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
base = f"http://127.0.0.1:{port}"
backend = os.getenv("LLM_BACKEND", "openai")
assert backend in {"openai", "ollama"}
with tempfile.TemporaryDirectory() as tmp:
    env = {
        **os.environ,
        "PORT": str(port),
        "LLM_BACKEND": backend,
        "SERVICE_MODE": "spells",
        "SPELL_DB_PATH": tmp + "/spell.sqlite",
        "LANGCHAIN_PROJECT": "kharakteres-language-feedback",
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
            with httpx.Client(base_url=base, timeout=180) as client:
                ambiguous = client.post(
                    "/api/language", json={"message": "그리스어로 해 줘"}
                )
                ambiguous.raise_for_status()
                assert not ambiguous.json()["resolved"], ambiguous.json()
                classical = client.post(
                    "/api/language",
                    json={
                        "message": "고전 그리스어로 해 줘",
                        "history": [
                            {"role": "user", "text": "그리스어로 해 줘"},
                            {"role": "assistant", "text": ambiguous.json()["reply"]},
                        ],
                    },
                )
                classical.raise_for_status()
                assert classical.json()["language"] == "grc", classical.json()
                modern = client.post(
                    "/api/language", json={"message": "영어로 만들어 줘"}
                )
                modern.raise_for_status()
                assert modern.json()["language"] == "en", modern.json()
                rows = []
                for choice in [modern.json(), classical.json()]:
                    started = time.monotonic()
                    response = client.post(
                        "/api/generate",
                        json={
                            "language": choice["language"],
                            "prompt": "짧은 한 문장으로 빛을 불러 어두운 방을 밝히는 주문",
                            "elements": ["light"],
                            "world": "발음 및 웹 출처 실검증",
                        },
                    )
                    assert response.status_code == 200, response.text
                    data = response.json()
                    draft = data["draft"]
                    assert (
                        draft["hangul_pronunciation"]
                        and draft["ipa"]
                        and draft["pronunciation_note"]
                    )
                    assert draft["verification"]["status"] in {
                        "references_found",
                        "not_found",
                        "unavailable",
                    }, draft["verification"]
                    saved = client.post("/api/spells", json=draft)
                    saved.raise_for_status()
                    record = saved.json()["spell"]
                    assert record["verification"] == draft["verification"]
                    assert (
                        client.get("/api/spells/" + record["id"]).json()["ipa"]
                        == draft["ipa"]
                    )
                    rows.append(
                        {
                            "language": choice["language"],
                            "seconds": round(time.monotonic() - started, 1),
                            **data,
                        }
                    )
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                        headless=True,
                    )
                    page = browser.new_page(viewport={"width": 1440, "height": 1080})
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(base)
                    expect(page.locator(".spell-card")).to_have_count(2)
                    page.locator(".spell-card").first.click()
                    expect(page.get_by_text("한글 전사 ·", exact=False)).to_be_visible()
                    expect(page.locator(".source-evidence")).to_be_visible()
                    if rows[-1]["draft"]["verification"]["sources"]:
                        expect(page.locator(".source-item a").first).to_be_visible()
                    page.screenshot(
                        path=str(
                            root / "eval/results/kharakteres-language-sources.png"
                        ),
                        full_page=True,
                    )
                    page.get_by_role("button", name="편집하기", exact=True).click()
                    page.locator("#edit-ipa").fill("/edited/")
                    expect(
                        page.get_by_text("수정됨 · 출처 재확인 필요", exact=False)
                    ).to_be_visible()
                    page.get_by_role(
                        "button", name="웹 출처 다시 확인", exact=True
                    ).click()
                    expect(
                        page.get_by_role("button", name="웹 출처 다시 확인", exact=True)
                    ).to_be_enabled(timeout=35000)
                    expect(page.locator(".source-evidence")).to_be_visible()
                    if rows[-1]["draft"]["verification"]["sources"]:
                        expect(page.locator(".source-item a").first).to_be_visible()
                    assert not errors, errors
                    browser.close()
                (root / "eval/results/kharakteres-language-smoke.json").write_text(
                    json.dumps(rows, ensure_ascii=False, indent=2)
                )
                print(
                    json.dumps(
                        {
                            "backend": backend,
                            "model": rows[0]["model"],
                            "results": [
                                {
                                    "language": r["language"],
                                    "seconds": r["seconds"],
                                    "source_status": r["draft"]["verification"][
                                        "status"
                                    ],
                                    "sources": len(
                                        r["draft"]["verification"]["sources"]
                                    ),
                                }
                                for r in rows
                            ],
                            "browser": "pronunciation/source links/edit invalidation/recheck PASS",
                        },
                        ensure_ascii=False,
                    )
                )
        except BaseException:
            log.flush()
            log.seek(0)
            print(log.read()[-2000:])
            raise
        finally:
            stop(process)
