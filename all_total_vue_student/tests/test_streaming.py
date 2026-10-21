"""SSE ordering, provider deltas, safety, cancellation and request isolation."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from auth_support import authenticated_client

from kharakteres.api import app, lifespan, generate_stream
from kharakteres.generation import GenerationError
from kharakteres.models import GenerateRequest
from kharakteres.safety import ContentBlocked
from kharakteres.streaming import event_sink, stream_model, STAGES

REQUEST = {"prompt": "작은 상처를 빛으로 치유", "language": "ko", "elements": ["light"]}


def events(text):
    result = []
    for frame in text.split("\n\n"):
        lines = frame.splitlines()
        kind = next((s[7:] for s in lines if s.startswith("event: ")), None)
        body = "\n".join(s[6:] for s in lines if s.startswith("data: "))
        if kind and body:
            result.append((kind, json.loads(body)))
    return result


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("CONTENT_FILTER_MODE", "rules")
    monkeypatch.setenv("SPELL_VECTOR_ENABLED", "0")
    monkeypatch.setenv("SPELL_DB_PATH", str(tmp_path / "spells.sqlite"))
    with authenticated_client(app) as client:
        yield client


def test_stream_matches_post_without_saving_or_fake_tokens(api):
    post = api.post("/api/generate", json=REQUEST).json()
    response = api.post("/api/generate/stream", json=REQUEST)
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    output = events(response.text)
    assert output[0][0] == "accepted" and output[-1][0] == "done"
    assert not output[0][1]["token_stream"]
    assert not any(kind == "token" for kind, _ in output)
    stages = [(e["stage"], e["status"]) for kind, e in output if kind == "stage"]
    assert stages == [(key, state) for key in STAGES for state in ["running", "completed"]]
    for field in ["draft", "conflicts", "steps", "model"]:
        if field == "draft":
            post[field]["verification"].pop("checked_at")
            output[-1][1][field]["verification"].pop("checked_at")
        assert output[-1][1][field] == post[field]
    assert api.get("/api/spells").json()["items"] == []
    assert any(e.get("draft") for kind, e in output if kind == "stage")


def test_stream_validation_and_blocked_input(api):
    assert api.post("/api/generate/stream", json={}).status_code == 422
    output = events(api.post("/api/generate/stream", json={**REQUEST, "prompt": "씨발 주문"}).text)
    assert output[-1][0] == "error"
    assert output[-1][1]["code"] == "content_blocked"
    assert output[-1][1]["clear_preview"]
    assert not any(e.get("draft") or kind == "done" for kind, e in output)


def test_error_after_partial_draft_clears_preview_and_does_not_complete(api, monkeypatch):
    async def fail(*args, **kwargs):
        raise GenerationError("출처 처리 실패")

    monkeypatch.setattr("kharakteres.generation.verify_language", fail)
    output = events(api.post("/api/generate/stream", json=REQUEST).text)
    assert any(e.get("draft") for kind, e in output if kind == "stage")
    assert output[-1] == ("error", {"code": "generation_failed", "message": "출처 처리 실패", "clear_preview": True})
    assert api.get("/api/spells").json()["items"] == []


def test_constructed_language_stream_has_no_model_tokens(api):
    output = events(api.post("/api/generate/stream", json={
        **REQUEST, "language_kind": "constructed", "language": "별의 언어",
        "author_incantation": "Aru-na", "author_pronunciation": "아루나",
        "author_meaning": "빛이 이어진다", "author_ipa": "",
    }).text)
    assert output[-1][0] == "done"
    draft = output[-1][1]["draft"]
    assert draft["incantation"] == "Aru-na" and draft["ipa"] == ""
    assert not any(kind == "token" for kind, _ in output)


class Pieces(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(0)
            yield chunk

    async def aclose(self):
        self.closed = True


def mock_provider(monkeypatch, chunks, backend="openai"):
    stream = Pieces(chunks)
    seen = []

    async def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, stream=stream)

    original = httpx.AsyncClient
    monkeypatch.setattr("kharakteres.streaming.httpx.AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handle)))
    if backend == "ollama":
        from agent.runtime_llm import InteractiveOllamaQualityLLM
        model = InteractiveOllamaQualityLLM("test", .005)
    else:
        model = SimpleNamespace(api_key="test", model="test", name="openai:test", usd_per_1k=.005)
    return model, seen, stream


def openai_chunks(pieces, reason="stop"):
    records = [{"choices": [{"delta": {"content": piece}}]} for piece in pieces]
    records += [{"choices": [{"delta": {}, "finish_reason": reason}]}, {"choices": [], "usage": {"total_tokens": 42}}]
    return [b": comment\r\n\r\n"] + [
        ("data: " + json.dumps(record, ensure_ascii=False) + "\r\n\r\n").encode() for record in records
    ] + [b"data: [DONE]\r\n\r\n"]


def test_real_openai_delta_order_and_usage(monkeypatch):
    model, seen, response = mock_provider(monkeypatch, openai_chunks(['{"name":"', '빛', '의 서약"}']))

    async def check():
        received = []
        async def sink(event):
            assert not response.closed  # Delivered while the provider response is still open.
            received.append(event)
        token = event_sink.set(sink)
        try:
            raw, usage = await stream_model("openai", model, "JSON", "input", {})
        finally:
            event_sink.reset(token)
        assert raw == '{"name":"빛의 서약"}'
        assert ''.join(e["text"] for e in received) == raw
        assert len(received) == 3 and usage["tokens"] == 42
        assert seen[0]["stream"] and seen[0]["stream_options"]["include_usage"]
        assert seen[0]["response_format"] == {"type": "json_object"}
        assert response.closed
    asyncio.run(check())


def test_ollama_stream_keeps_schema_and_ignores_thinking(monkeypatch):
    records = [
        {"message": {"thinking": "private"}},
        {"message": {"content": '{"name":"'}},
        {"message": {"content": '빛"}'}, "done": True, "done_reason": "stop", "eval_count": 4, "prompt_eval_count": 6},
    ]
    model, seen, _ = mock_provider(monkeypatch, [(json.dumps(r)+'\n').encode() for r in records], "ollama")

    async def check():
        output = []
        async def sink(e): output.append(e)
        token = event_sink.set(sink)
        try:
            raw, usage = await stream_model("ollama", model, "sys", "user", {"type": "object"})
        finally: event_sink.reset(token)
        assert raw == '{"name":"빛"}' and usage["tokens"] == 10
        assert "private" not in str(output)
        assert seen[0]["format"] == {"type": "object"} and seen[0]["stream"]
    asyncio.run(check())


@pytest.mark.parametrize("pieces,reason,error", [
    (['{"name":"씨', '발"}'], "stop", ContentBlocked),
    (['{"name":"\\uc528', '\\ubc1c"}'], "stop", ContentBlocked),
    (['{"name":"light'], "length", ValueError),
])
def test_unsafe_or_truncated_output_never_finishes(monkeypatch, pieces, reason, error):
    model, _, response = mock_provider(monkeypatch, openai_chunks(pieces, reason))
    with pytest.raises(error):
        asyncio.run(stream_model("openai", model, "JSON", "input", {}))
    assert response.closed


def test_disconnect_cancels_request_work(monkeypatch, tmp_path):
    monkeypatch.setenv("SPELL_DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("CONTENT_FILTER_MODE", "rules")
    monkeypatch.setenv("SPELL_VECTOR_ENABLED", "0")
    monkeypatch.setenv("LLM_BACKEND", "fake")

    class Request:
        async def is_disconnected(self): return False

    async def check():
        cancelled = asyncio.Event()
        started = asyncio.Event()
        async with lifespan(app):
            async def hang(data):
                started.set()
                try: await asyncio.Future()
                finally: cancelled.set()
            monkeypatch.setattr(app.state.generator, "generate", hang)
            response = await generate_stream(GenerateRequest(**REQUEST), Request())
            iterator = response.body_iterator
            assert "accepted" in await anext(iterator)
            await asyncio.wait_for(started.wait(), timeout=2)
            await iterator.aclose()
            assert cancelled.is_set()
    asyncio.run(check())


def test_parallel_request_sinks_are_isolated():
    from kharakteres.streaming import emit

    async def check():
        async def job(label):
            output = []
            async def sink(e): output.append(e)
            token = event_sink.set(sink)
            try:
                for i in range(3):
                    await asyncio.sleep(0)
                    await emit("token", text=label)
            finally: event_sink.reset(token)
            return output
        left, right = await asyncio.gather(job("A"), job("B"))
        assert {x["text"] for x in left} == {"A"}
        assert {x["text"] for x in right} == {"B"}
    asyncio.run(check())
