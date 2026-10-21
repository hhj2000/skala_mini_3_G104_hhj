"""Author-owned languages and audio integration, without network/API charges."""

import asyncio
import io
import json
import wave

import httpx
import pytest
from fastapi.testclient import TestClient
from auth_support import authenticated_client

from kharakteres.api import app
from kharakteres.speech import SpeechService, SpeechRequest, split_speech


def wave_sample(frames=b"\x00\x00" * 48):
    result = io.BytesIO()
    with wave.open(result, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(frames)
    return result.getvalue()


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SPELL_DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.delenv("SPEECH_BACKEND", raising=False)
    with authenticated_client(app) as client:
        yield client


def conlang(**changes):
    return dict(
        prompt="어두운 방에 작은 빛을 불러온다",
        language_kind="constructed",
        language="별의 언어",
        author_incantation="Æl lumena",
        author_pronunciation="아엘 루메나",
        author_meaning="별빛이여 깨어나라",
        **changes,
    )


def test_conlang_preserves_author_text_and_optional_ipa_without_model_or_web(
    api, monkeypatch
):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Author-defined language must not be invented by an LLM")

    monkeypatch.setattr(app.state.generator, "call_model", forbidden)
    response = api.post("/api/generate", json=conlang())
    assert response.status_code == 200, response.text
    draft = response.json()["draft"]
    assert draft["incantation"] == "Æl lumena"
    assert draft["hangul_pronunciation"] == "아엘 루메나"
    assert draft["literal_meaning"] == "별빛이여 깨어나라"
    assert draft["ipa"] == ""
    assert draft["verification"]["status"] == "author_defined"
    saved = api.post("/api/spells", json=draft)
    assert saved.status_code == 201, saved.text
    row = saved.json()["spell"]
    assert row["verification"]["status"] == "author_defined"
    assert api.get("/api/spells/" + row["id"]).json()["ipa"] == ""
    response = api.post("/api/generate", json=conlang(author_ipa="/ael lumena/"))
    assert response.json()["draft"]["ipa"] == "/ael lumena/"


def test_conlang_requires_meaning_and_pronunciation(api):
    request = conlang()
    request["author_pronunciation"] = ""
    assert api.post("/api/generate", json=request).status_code == 422
    request = conlang()
    request["author_meaning"] = ""
    assert api.post("/api/generate", json=request).status_code == 422


def test_disabled_audio_never_returns_example_or_fake_sound(api):
    assert not api.get("/api/catalog").json()["audio"]["enabled"]
    assert (
        api.post(
            "/api/audio/transcribe",
            content=b"abc",
            headers={"content-type": "audio/wav"},
        ).status_code
        == 503
    )
    assert api.post("/api/audio/speech", json={"text": "빛이여"}).status_code == 503


def install_audio(monkeypatch, handler):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    app.state.speech = SpeechService(transport=httpx.MockTransport(handler))


def test_stt_upload_is_multipart_and_returns_actual_provider_text(api, monkeypatch):
    def handler(request):
        assert request.url.path == "/v1/audio/transcriptions"
        assert "multipart/form-data" in request.headers["content-type"]
        assert b"whisper-1" in request.content
        assert b"spell_audio.wav" in request.content
        assert b"test.wav" not in request.content
        return httpx.Response(200, json={"text": "빛이여 깨어나라"})

    install_audio(monkeypatch, handler)
    response = api.post(
        "/api/audio/transcribe?language=ko",
        content=wave_sample(),
        headers={"content-type": "audio/wav"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "빛이여 깨어나라"
    assert (
        api.post(
            "/api/audio/transcribe", content=b"", headers={"content-type": "audio/wav"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/audio/transcribe",
            content=b"text",
            headers={"content-type": "text/plain"},
        ).status_code
        == 415
    )
    assert (
        api.post(
            "/api/audio/transcribe",
            content=b"x" * (10 * 1024 * 1024 + 1),
            headers={"content-type": "audio/wav"},
        ).status_code
        == 413
    )


def test_long_tts_keeps_tail_and_combines_all_audio_frames(api, monkeypatch):
    seen = []

    def handler(request):
        value = json.loads(request.content)
        seen.append(value["input"])
        assert value["model"] == "gpt-4o-mini-tts"
        assert value["voice"] == "coral"
        assert value["response_format"] == "wav"
        return httpx.Response(
            200, content=wave_sample(), headers={"content-type": "audio/wav"}
        )

    install_audio(monkeypatch, handler)
    text = "별빛이여! " * 900 + "마지막 구절"
    response = api.post("/api/audio/speech", json={"text": text})
    assert response.status_code == 200, response.text[:100]
    assert "".join(seen) == text
    assert len(seen) > 1
    with wave.open(io.BytesIO(response.content), "rb") as audio:
        assert audio.getnframes() == 48 * len(seen)
    assert response.headers["cache-control"] == "no-store"
    assert api.post("/api/audio/speech", json={"text": " "}).status_code == 422


def test_audio_provider_failure_is_explicit_and_does_not_leak_secrets(api, monkeypatch):
    install_audio(
        monkeypatch, lambda _: httpx.Response(429, json={"error": "private details"})
    )
    response = api.post("/api/audio/speech", json={"text": "빛이여"})
    assert response.status_code == 502
    assert "한도" in response.text
    assert "private details" not in response.text
    assert "unit-test-key" not in response.text


def test_utf8_chunk_bound_preserves_all_characters():
    text = "𓂀 별빛 Æl! " * 1200
    chunks = split_speech(text)
    assert "".join(chunks) == text
    assert all(len(c.encode()) <= 1800 and len(c) <= 4096 for c in chunks)


def test_empty_transcription_does_not_return_notebook_example(api, monkeypatch):
    install_audio(monkeypatch, lambda _: httpx.Response(200, json={"text": ""}))
    response = api.post(
        "/api/audio/transcribe",
        content=wave_sample(),
        headers={"content-type": "audio/wav"},
    )
    assert response.status_code == 422
    assert "인식하지 못했습니다" in response.json()["detail"]
    assert api.get("/api/spells").json()["total"] == 0
