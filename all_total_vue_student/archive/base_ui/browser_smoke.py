from playwright.sync_api import sync_playwright
from pathlib import Path
import argparse

args = argparse.ArgumentParser()
args.add_argument("--url", default="http://127.0.0.1:8600")
options = args.parse_args()
root = Path(__file__).resolve().parents[2]
with sync_playwright() as p:
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    browser = p.chromium.launch(
        **({"executable_path": str(chrome)} if chrome.exists() else {}), headless=True
    )
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(options.url)
    page.get_by_role("button", name="billing-service 응답이 느려요", exact=True).click()
    page.get_by_role("button", name="cache-service", exact=True).wait_for()
    page.get_by_role("button", name="cache-service", exact=True).click()
    page.get_by_text("진단 근거 3건", exact=False).wait_for(timeout=30000)
    assert "memory-leak" in page.locator("body").inner_text()
    root.joinpath("eval/results").mkdir(exist_ok=True, parents=True)
    page.locator("#log").evaluate("(el) => el.scrollTop = 0")
    page.screenshot(
        path=str(root / "eval/results/desktop-evidence.png"), full_page=True
    )
    page.get_by_role("button", name="새 대화", exact=True).click()
    page.get_by_role(
        "button",
        name="payments-service랑 cache-service 공통 원인을 진단해줘",
        exact=True,
    ).click()
    page.get_by_text("진단 근거 6건", exact=False).wait_for(timeout=30000)
    text = page.locator("body").inner_text()
    assert "cpu-spike" in text and "memory-leak" in text
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("#log").evaluate("(el) => el.scrollTop = 0")
    page.screenshot(path=str(root / "eval/results/mobile-evidence.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert not errors, errors
    print(
        "Browser: clarification, target selection, multi-system evidence, mobile width, JS errors: PASS"
    )
    browser.close()
