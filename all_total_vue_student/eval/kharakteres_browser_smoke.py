"""Browser regression in an isolated temporary lexicon; never changes user data.

Historical experiment: predates account-aware regression coverage. Review login
handling before rerunning; old results do not certify the current full UI flow.
For current fixed-data quantitative evaluation use kharakteres_benchmark.py.
"""

import os
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]


def exercise(base):
    with sync_playwright() as p:
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        browser = p.chromium.launch(
            **({"executable_path": str(chrome)} if chrome.exists() else {}),
            headless=True,
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1080})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "console",
            lambda m: (
                errors.append(m.text)
                if m.type == "error" and "409 (Conflict)" not in m.text
                else None
            ),
        )
        page.goto(base)
        expect(
            page.get_by_role("heading", name="당신의 첫 번째 주문을 기다립니다.")
        ).to_be_visible()
        page.get_by_role("button", name="달빛으로 잇는 작은 치유", exact=False).click()
        expect(page.locator("#prompt")).to_have_value(
            "달빛을 모아 작은 상처를 치유하지만, 밤에만 사용할 수 있는 주문"
        )
        expect(
            page.get_by_role("button", name="✦ 주문 생성하기", exact=True)
        ).to_be_disabled()
        page.locator("#language-message").fill("알 수 없는 언어")
        page.get_by_role("button", name="언어 답장 보내기", exact=True).click()
        expect(page.get_by_text("데모에서는 한국어", exact=False)).to_be_visible()
        expect(
            page.get_by_role("button", name="✦ 주문 생성하기", exact=True)
        ).to_be_disabled()
        page.locator("#language-message").fill("한국어")
        page.locator("#language-message").press("Enter")
        expect(
            page.get_by_role("button", name="✦ 주문 생성하기", exact=True)
        ).to_be_enabled()

        if (
            page.locator("#language-message").input_value()
            or page.get_by_role(
                "button", name="✦ 주문 생성하기", exact=True
            ).is_disabled()
        ):
            page.locator("#language-message").fill("한국어")
            page.get_by_role("button", name="언어 답장 보내기", exact=True).click()
            expect(
                page.get_by_role("button", name="✦ 주문 생성하기", exact=True)
            ).to_be_enabled()
        page.get_by_role("button", name="✦ 주문 생성하기", exact=True).click()
        expect(page.get_by_role("button", name="편집하고 저장하기 →")).to_be_visible(
            timeout=20000
        )
        page.get_by_role("button", name="편집하고 저장하기 →").click()
        page.locator("#edit-name").fill("새벽의 봉합")
        page.get_by_role("button", name="서고에 저장", exact=True).click()
        expect(page.locator(".spell-card")).to_have_count(1)
        page.locator(".spell-card").click()
        page.get_by_role("button", name="편집하기", exact=True).click()
        page.locator("#edit-notes").fill(
            "밤에만 사용하는 달빛의 치유. 브라우저 검증 기록."
        )
        page.get_by_role("button", name="서고에 저장", exact=True).click()
        expect(page.locator(".spell-card")).to_have_count(1)
        page.reload()
        expect(page.locator(".spell-card")).to_have_count(1)
        page.get_by_label("주문 검색", exact=True).fill("없는주문")
        expect(
            page.get_by_role("heading", name="아직 그 마법을 찾지 못했어요.")
        ).to_be_visible()
        page.get_by_role("button", name="검색 조건 초기화", exact=True).click()
        expect(page.locator(".spell-card")).to_have_count(1)
        page.locator(".spell-card").click()
        page.get_by_role("button", name="AI 설정 검토", exact=True).click()
        expect(
            page.get_by_text("fake 모드는 규칙 기반 검토만 제공합니다.", exact=False)
        ).to_be_visible()
        page.get_by_role("button", name="닫기", exact=True).click()
        page.get_by_role("button", name="새 주문 만들기", exact=False).first.click()
        page.locator("#prompt").fill("기존 주문과 동일한 빛을 이용해 상처를 치유한다.")
        if (
            page.locator("#language-message").input_value()
            or page.get_by_role(
                "button", name="✦ 주문 생성하기", exact=True
            ).is_disabled()
        ):
            page.locator("#language-message").fill("한국어")
            page.get_by_role("button", name="언어 답장 보내기", exact=True).click()
            expect(
                page.get_by_role("button", name="✦ 주문 생성하기", exact=True)
            ).to_be_enabled()
        page.get_by_role("button", name="✦ 주문 생성하기", exact=True).click()
        expect(page.get_by_role("button", name="편집하고 저장하기 →")).to_be_visible()
        page.get_by_role("button", name="편집하고 저장하기 →").click()
        page.locator("#edit-name").fill("새벽의 봉합")
        page.get_by_role("button", name="서고에 저장", exact=True).click()
        expect(
            page.get_by_text(
                "같은 세계관의 중복 주문을 검토한 뒤 저장해 주세요.", exact=False
            )
        ).to_be_visible()
        page.get_by_role(
            "checkbox", name="검토 내용을 확인했습니다.", exact=False
        ).check()
        page.get_by_role("button", name="서고에 저장", exact=True).click()
        expect(page.locator(".spell-card")).to_have_count(2)
        page.locator(".spell-card").first.click()
        page.get_by_role("button", name="삭제", exact=True).click()
        page.get_by_role("button", name="주문 삭제", exact=True).click()
        expect(page.locator(".spell-card")).to_have_count(1)
        page.get_by_role("button", name="＋ 직접 기록", exact=True).click()
        page.locator("#edit-name").fill("손으로 적은 별의 편린")
        page.locator("#edit-incantation").fill("별빛아, 손끝에 모여라.")
        page.locator("#edit-effect").fill("작은 별빛 조각을 손끝에 모아 주변을 비춘다.")
        page.get_by_role("button", name="서고에 저장", exact=True).click()
        expect(page.locator(".spell-card")).to_have_count(2)
        page.get_by_role("button", name="손으로 적은 별의 편린", exact=False).click()
        page.get_by_role("button", name="삭제", exact=True).click()
        page.get_by_role("button", name="주문 삭제", exact=True).click()
        expect(page.locator(".spell-card")).to_have_count(1)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
        page.screenshot(
            path=str(root / "eval/results/kharakteres-mobile.png"), full_page=True
        )
        page.set_viewport_size({"width": 1440, "height": 1080})
        page.screenshot(
            path=str(root / "eval/results/kharakteres-desktop.png"), full_page=True
        )
        page.get_by_role("button", name="새 주문 만들기", exact=False).first.click()
        page.screenshot(
            path=str(root / "eval/results/kharakteres-create.png"), full_page=True
        )
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
        assert not errors, errors
        print(
            "Kharakteres browser: generate/edit/save/reload/search/AI review/conflict acknowledgment/delete/mobile PASS"
        )
        browser.close()


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def wait_ready(base, process):
    for _ in range(100):
        try:
            if httpx.get(base + "/health", timeout=0.4).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if process.poll() is not None:
            raise RuntimeError("Preview startup failed")
        time.sleep(0.1)
    raise RuntimeError("Preview startup timeout")


if __name__ == "__main__":
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "PORT": str(port),
            "LLM_BACKEND": "fake",
            "CONTENT_FILTER_MODE": "rules",
            "SPELL_VECTOR_ENABLED": "0",
            "SERVICE_MODE": "spells",
            "LANGCHAIN_TRACING_V2": "false",
            "LANGSMITH_TRACING": "false",
            "SPELL_DB_PATH": tmp + "/test.sqlite",
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
                exercise(base)
                before = httpx.get(base + "/api/spells").json()["items"]
                assert len(before) == 1
                stop(process)
                process = subprocess.Popen(
                    [str(root / ".venv/bin/python"), "server.py"],
                    cwd=root,
                    env=env,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                wait_ready(base, process)
                after = httpx.get(base + "/api/spells").json()["items"]
                assert before == after
                print("Backend restart persistence: PASS")
            except BaseException:
                log.flush()
                log.seek(0)
                print(log.read()[-4000:])
                raise
            finally:
                stop(process)
