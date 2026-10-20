"""Interactive runtime settings. Original adapters remain intact for baseline replay."""

import asyncio
import json
import os
import httpx
from .ollama_llm import OllamaFastLLM, OllamaQualityLLM
from .openai_llm import OpenAIFastLLM, OpenAIQualityLLM


def ollama_base_url():
    return os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


class BoundedOllama:
    def _payload(self, system, user, stream, schema=None):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": stream,
            "think": os.getenv("OLLAMA_THINK", "false").lower() in {"1", "true", "yes"},
            "options": {
                "temperature": 0.0,
                "num_predict": int(
                    getattr(self, "num_predict", os.getenv("OLLAMA_NUM_PREDICT", "768"))
                ),
            },
            "keep_alive": "10m",
        }
        if schema is not None:
            payload["format"] = schema
        return payload

    def _usage(self, data):
        tokens = (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0)
        return {
            "model": self.name,
            "tokens": tokens,
            "usd": round(tokens / 1000 * self.usd_per_1k, 6),
        }

    def _chat(self, system, user, schema=None):
        timeout = httpx.Timeout(
            float(os.getenv("LLM_TIMEOUT_SECONDS", "90")), connect=5
        )
        response = httpx.post(
            ollama_base_url() + "/api/chat",
            json=self._payload(system, user, False, schema),
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"], self._usage(data)

    async def _chat_stream(self, system, user, on_token=None):
        chunks = []
        usage = {"model": self.name, "tokens": 0, "usd": 0.0}
        timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "90"))
        # Wall-clock bound includes thinking and token streaming, not just idle reads.
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=5)
            ) as client:
                async with client.stream(
                    "POST",
                    ollama_base_url() + "/api/chat",
                    json=self._payload(system, user, True),
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("error"):
                            raise RuntimeError("Ollama generation failed")
                        piece = data.get("message", {}).get("content", "")
                        if piece:
                            chunks.append(piece)
                            if on_token is not None:
                                on_token(piece)
                        if data.get("done"):
                            usage = self._usage(data)
        usage["prompt"] = f"[SYSTEM]\n{system}\n\n[USER]\n{user}"
        if not chunks:
            raise RuntimeError(
                "Ollama returned no answer; check thinking/output budget"
            )
        return "".join(chunks), usage


class InteractiveOllamaFastLLM(BoundedOllama, OllamaFastLLM):
    pass


class InteractiveOllamaQualityLLM(BoundedOllama, OllamaQualityLLM):
    pass


class InteractiveOpenAIFastLLM(OpenAIFastLLM):
    async def chat(self, *args, **kwargs):
        # The original async adapter calls synchronous httpx.post internally.
        # Offload the entire operation so /health and SSE stay responsive.
        method = super().chat
        async with asyncio.timeout(float(os.getenv("LLM_TIMEOUT_SECONDS", "90"))):
            return await asyncio.to_thread(lambda: asyncio.run(method(*args, **kwargs)))


class InteractiveOpenAIQualityLLM(OpenAIQualityLLM):
    async def write(self, *args, **kwargs):
        method = super().write
        async with asyncio.timeout(float(os.getenv("LLM_TIMEOUT_SECONDS", "90"))):
            return await asyncio.to_thread(lambda: asyncio.run(method(*args, **kwargs)))
