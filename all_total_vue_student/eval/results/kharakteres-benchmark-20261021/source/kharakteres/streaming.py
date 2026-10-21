"""Request-local SSE events and cancellable structured model streaming."""

import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
import re

import httpx
from langsmith.run_helpers import get_current_run_tree

from .safety import ContentBlocked, rule_category

event_sink = ContextVar("spell_event_sink", default=None)

STAGES = {
    "input_safety": "요청 내용 확인",
    "retrieve_lexicon": "기존 주문 검색",
    "compose_spell": "주문 작성·콘텐츠 검사",
    "verify_language_sources": "언어·발음 출처 확인",
    "review_consistency": "기존 주문과 충돌 검토",
}


async def emit(event, **data):
    sink = event_sink.get()
    if sink is not None:
        await sink({"event": event, **data})


def trace_event(event, **data):
    run = get_current_run_tree()
    if run is not None:
        run.add_event({
            "name": event, "time": datetime.now(timezone.utc).isoformat(),
            "kwargs": data,
        })


async def sse_data(response):
    """Parse complete SSE messages, including comments and multi-line data."""
    lines = []
    async for line in response.aiter_lines():
        if not line:
            if lines:
                yield "\n".join(lines)
                lines = []
        elif line.startswith("data:"):
            lines.append(line[5:].removeprefix(" "))
    if lines:
        yield "\n".join(lines)


async def stream_model(backend, model, system, user, schema):
    """Use actual provider deltas; never replay a completed answer as tokens."""
    from agent.runtime_llm import ollama_base_url

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if backend == "openai":
        if not model.api_key:
            raise RuntimeError("Missing OpenAI API key")
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": "Bearer " + model.api_key}
        payload = {
            "model": model.model, "messages": messages, "temperature": 0,
            "response_format": {"type": "json_object"}, "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": int(getattr(model, "num_predict", 1536)),
        }
    elif backend == "ollama":
        url = ollama_base_url() + "/api/chat"
        headers = {}
        payload = model._payload(system, user, True, schema)
    else:
        raise ValueError("Unsupported streaming backend")

    chunks, size, tokens, complete = [], 0, 0, False
    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "90"))
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5)) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                iterator = sse_data(response) if backend == "openai" else response.aiter_lines()
                async for line in iterator:
                    if not line or line == "[DONE]":
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise RuntimeError("Provider stream failed")
                    if backend == "openai":
                        tokens = (data.get("usage") or {}).get("total_tokens", tokens)
                        choice = next(iter(data.get("choices", [])), {})
                        reason = choice.get("finish_reason")
                        if reason is not None:
                            if reason != "stop":
                                raise ValueError("Incomplete or refused generation")
                            complete = True
                        piece = choice.get("delta", {}).get("content") or ""
                    else:
                        piece = data.get("message", {}).get("content", "")
                        if data.get("done"):
                            if data.get("done_reason", "stop") != "stop":
                                raise ValueError("Incomplete generation")
                            complete = True
                            tokens = (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0)
                    if piece:
                        chunks.append(piece)
                        size += len(piece)
                        if size > 64000:
                            raise ValueError("Generation too large")
                        # Catch known terms across chunk boundaries before emitting this delta.
                        raw = "".join(chunks)
                        decoded = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), raw)
                        category = rule_category(raw + "\n" + decoded)
                        if category:
                            raise ContentBlocked(category, "stream_output")
                        await emit("token", text=piece, preview=True)
                        trace_event("new_token", token=piece)
    if not complete or not chunks:
        raise ValueError("Provider stream ended without a complete answer")
    return "".join(chunks), {
        "model": model.name, "tokens": tokens,
        "usd": round(tokens / 1000 * model.usd_per_1k, 6),
    }
