"""Isolated browser fixture: real SSE path with a delayed mock provider, no API charges."""

import asyncio
from contextlib import asynccontextmanager
import json

import httpx

from kharakteres.api import app, lifespan
from kharakteres import generation, streaming
from kharakteres.verification import verify_language


TEXT = json.dumps({
    "name": "새벽의 치유", "incantation": "빛이여, 작은 상처를 이어라.",
    "romanization": "Bichiyeo", "hangul_pronunciation": "비치여, 자근 상처를 이어라",
    "ipa": "/pitɕʰi.jʌ/", "pronunciation_note": "현대 한국어 근사 발음",
    "literal_meaning": "작은 상처를 빛으로 치유한다.", "effect": "작은 상처를 치유한다.",
    "limitations": "밤에만 사용한다.", "notes": "지연된 모의 모델 응답입니다.",
    "tags": ["빛"], "school": "healing",
}, ensure_ascii=False)


class Model:
    name, model, api_key, usd_per_1k = "mock-stream", "mock", "test-only", 0

    def _chat(self, *args, **kwargs):
        return json.dumps({"resolved": True, "language": "ko", "reply": "한국어로 준비했습니다."}), {}


class ProviderStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        for i in range(0, len(TEXT), 14):
            await asyncio.sleep(.06)
            yield ("data: " + json.dumps({"choices": [{"delta": {"content": TEXT[i:i+14]}}]}) + "\n\n").encode()
        yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        yield b'data: [DONE]\n\n'


@asynccontextmanager
async def fixture_lifespan(instance):
    async with lifespan(instance):
        instance.state.generator.backend = "openai"
        instance.state.generator.model = Model()
        instance.state.backend = "openai"
        original_client = httpx.AsyncClient

        async def handle(request):
            return httpx.Response(200, stream=ProviderStream())

        async def verify(draft, **kwargs):
            await asyncio.sleep(.8)
            return await verify_language(draft, demo=True)

        streaming.httpx.AsyncClient = lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handle))
        generation.verify_language = verify
        try:
            yield
        finally:
            streaming.httpx.AsyncClient = original_client
            generation.verify_language = verify_language


app.router.lifespan_context = fixture_lifespan
