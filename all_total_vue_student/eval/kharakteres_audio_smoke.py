"""Isolated conlang/audio UI regression. --live also runs real notebook-model TTS→STT.
Microphone capture uses a deterministic fake recorder; it never opens the user's mic.


Historical experiment: predates account-aware regression coverage. Review login
handling before rerunning; old results do not certify the current full UI flow.
For current fixed-data quantitative evaluation use kharakteres_benchmark.py.
"""

import argparse
import base64
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import wave

import httpx
from playwright.sync_api import expect, sync_playwright
from kharakteres_browser_smoke import stop, wait_ready

root = Path(__file__).resolve().parents[1]


def sample_wav():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * 2400)
    return buffer.getvalue()


def exercise(base, audio):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            headless=True,
            args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
            ],
        )
        context = browser.new_context(
            permissions=["microphone"], viewport={"width": 1440, "height": 1080}
        )
        page = context.new_page()
        # A deterministic fake recorder tests UI state without requiring a device or
        # headless macOS audio clock. Real provider WAV/STT is covered by --live.
        page.add_init_script(
            """(() => {
          const bytes = Uint8Array.from(atob("__WAV__"), c => c.charCodeAt(0));
          navigator.mediaDevices.getUserMedia = async () => { if (window.microphoneDenied) throw new DOMException('Denied', 'NotAllowedError'); return new MediaStream(); };
          window.MediaRecorder = class {
            static isTypeSupported() { return false; }
            constructor() { this.state='inactive'; this.mimeType='audio/wav'; }
            start() { this.state='recording'; }
            stop() { this.state='inactive'; queueMicrotask(() => {
              this.ondataavailable?.({data:new Blob([bytes], {type:'audio/wav'})});
              this.onstop?.();
            }); }
          };
        })();""".replace("__WAV__", base64.b64encode(audio).decode())
        )
        errors, tts_inputs, stt_sizes = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def catalog(route):
            response = route.fetch()
            data = response.json()
            data["audio"]["enabled"] = True
            route.fulfill(response=response, json=data)

        def stt(route):
            stt_sizes.append(len(route.request.post_data_buffer or b""))
            route.fulfill(json={"text": "아엘 루메나", "model": "browser-test"})

        def tts(route):
            tts_inputs.append(route.request.post_data_json)
            route.fulfill(body=audio, content_type="audio/wav")

        page.route("**/api/catalog", catalog)
        page.route("**/api/audio/transcribe?*", stt)
        page.route("**/api/audio/speech", tts)
        page.goto(base)
        page.get_by_role("button", name="새 주문 만들기", exact=False).first.click()
        page.locator("#language-kind").select_option("constructed")
        page.locator("#constructed-language").fill("별의 언어")
        page.locator("#author-incantation").fill("Æl lumena")
        page.locator("#author-pronunciation").fill("아엘 루메나")
        page.locator("#author-meaning").fill("별빛이여 깨어나라")
        page.locator("#prompt").fill("작은 빛을 불러 어두운 방을 밝힌다")
        voice = page.locator(".voice-input").first
        voice.locator("summary").click()
        page.evaluate("window.microphoneDenied=true")
        voice.get_by_role("button", name="마이크 녹음 시작", exact=True).click()
        expect(
            voice.get_by_text("마이크 권한이 필요합니다.", exact=False)
        ).to_be_visible()
        page.evaluate("window.microphoneDenied=false")
        voice.get_by_role("button", name="마이크 녹음 시작", exact=True).click()
        expect(
            voice.get_by_role("button", name="녹음 종료", exact=False)
        ).to_be_visible()
        page.wait_for_timeout(350)
        voice.get_by_role("button", name="녹음 종료", exact=False).click()
        expect(voice.locator("audio")).to_have_attribute(
            "src", __import__("re").compile("^blob:")
        )
        recorded_bytes = voice.locator("audio").evaluate(
            "async el => (await (await fetch(el.src)).arrayBuffer()).byteLength"
        )
        assert recorded_bytes > 0, recorded_bytes
        voice.get_by_role("button", name="음성 전사 실행", exact=True).click()
        expect(voice.get_by_label("음성 전사 결과", exact=True)).to_have_value(
            "아엘 루메나"
        )
        voice.get_by_label("음성 입력 대상", exact=True).select_option(
            "author_pronunciation"
        )
        voice.get_by_role("button", name="선택한 칸에 적용", exact=True).click()
        expect(page.locator("#author-pronunciation")).to_have_value("아엘 루메나")
        voice.get_by_label("전사할 음성 파일", exact=True).set_input_files(
            {"name": "test.wav", "mimeType": "audio/wav", "buffer": audio}
        )
        voice.get_by_role("button", name="음성 전사 실행", exact=True).click()
        expect(voice.get_by_label("음성 전사 결과", exact=True)).to_have_value(
            "아엘 루메나"
        )
        assert len(stt_sizes) == 2 and min(stt_sizes) > 0, stt_sizes
        page.get_by_role("button", name="✦ 주문 생성하기", exact=True).click()
        expect(
            page.get_by_role("button", name="편집하고 저장하기 →", exact=True)
        ).to_be_visible()
        speech = page.locator(".preview-panel .spell-audio")
        speech.locator("summary").click()
        area = speech.get_by_label("음성으로 읽을 내용", exact=True)
        expect(area).to_have_value("아엘 루메나")
        area.evaluate(
            "el=>{el.focus();el.setSelectionRange(0,2);el.dispatchEvent(new Event('select'))}"
        )
        speech.get_by_role("button", name="선택한 구절 변환", exact=True).click()
        expect(speech.locator("audio")).to_be_visible()
        page.wait_for_function(
            "document.querySelector('.preview-panel .spell-audio audio').readyState>=1"
        )
        assert tts_inputs[-1]["text"] == "아엘"
        speech.get_by_label("음성 변환 범위", exact=True).select_option("full")
        full = area.input_value()
        assert "별빛이여 깨어나라" in full and "아엘 루메나" in full
        speech.get_by_role("button", name="읽을 내용 전체 변환", exact=True).click()
        expect(speech.locator("audio")).to_be_visible()
        assert tts_inputs[-1]["text"] == full
        page.screenshot(
            path=str(root / "eval/results/kharakteres-audio-conlang.png"),
            full_page=True,
        )
        page.get_by_role("button", name="편집하고 저장하기 →", exact=True).click()
        expect(page.locator("#edit-ipa")).to_have_value("")
        page.get_by_role("button", name="서고에 저장", exact=True).click()
        expect(page.locator(".spell-card")).to_have_count(1)
        page.reload()
        page.locator(".spell-card").click()
        expect(page.get_by_text("지정 발음 · 아엘 루메나", exact=True)).to_be_visible()
        page.get_by_role("button", name="닫기", exact=True).click()
        page.get_by_role("button", name="새 주문 만들기", exact=False).first.click()
        page.locator("#language-kind").select_option("constructed")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert not errors, errors
        browser.close()
        return {
            "ui": "conlang without IPA/save/reload/mocked microphone/file upload/STT apply/selected and full TTS/mobile PASS",
            "stt_uploads": stt_sizes,
            "tts_requests": len(tts_inputs),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
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
            "SPEECH_BACKEND": "openai" if args.live else "disabled",
            "SPELL_DB_PATH": tmp + "/spell.sqlite",
            "LANGCHAIN_PROJECT": "kharakteres-audio-feedback",
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
                audio = sample_wav()
                result = {}
                if args.live:
                    with httpx.Client(base_url=base, timeout=250) as client:
                        response = client.post(
                            "/api/audio/speech",
                            json={
                                "text": "빛이여, 작은 방을 밝혀라.",
                                "voice": "coral",
                            },
                        )
                        assert response.status_code == 200, response.text[:250]
                        audio = response.content
                        with wave.open(io.BytesIO(audio), "rb") as decoded:
                            result["audio_seconds"] = round(
                                decoded.getnframes() / decoded.getframerate(), 2
                            )
                            assert decoded.getnframes() > 0
                        transcript = client.post(
                            "/api/audio/transcribe?language=ko",
                            content=audio,
                            headers={"content-type": "audio/wav"},
                        )
                        assert transcript.status_code == 200, transcript.text
                        assert "빛" in transcript.json()["text"], transcript.json()
                        result["live_transcript"] = transcript.json()["text"]
                        (root / "eval/results/kharakteres-audio-live.wav").write_bytes(
                            audio
                        )
                result.update(exercise(base, audio))
                if args.live:
                    (root / "eval/results/kharakteres-audio-live.json").write_text(
                        json.dumps(result, ensure_ascii=False, indent=2)
                    )
                print(json.dumps(result, ensure_ascii=False))
            except BaseException:
                log.flush()
                log.seek(0)
                print(log.read()[-2500:])
                raise
            finally:
                stop(process)
