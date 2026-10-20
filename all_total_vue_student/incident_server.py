"""FastAPI entry point. POST and SSE use the same traced execution/persistence path."""

import asyncio
import json
import os
import logging
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from pydantic import BaseModel, Field
from agent.deps import SupervisorDeps
from agent.model_factory import _build_llms
from agent.graph import build_graph
from agent.baseline_graph import build_graph as build_baseline_graph
from agent.mcp_client import MCPClient
from agent.session_store import SqliteSessionStore
from agent.supervisor_v1 import run_v1

CREATION_COUNT = 0


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    thread_id: str = Field(default="default", min_length=1, max_length=128)




@asynccontextmanager
async def lifespan(app):
    global CREATION_COUNT
    CREATION_COUNT += 1
    mode = os.getenv("AGENT_MODE", "improved")
    if mode not in {"baseline", "improved"}:
        raise ValueError("AGENT_MODE must be baseline or improved")
    mcp = MCPClient(flaky_first_tool_call=os.getenv("MCP_DEMO_FLAKY", "0") == "1")
    store = SqliteSessionStore()
    try:
        logger = logging.getLogger("uvicorn.error")
        logger.info("MCP ops/docs 연결 중…")
        async with asyncio.timeout(
            float(os.getenv("MCP_STARTUP_TIMEOUT_SECONDS", "20"))
        ):
            await mcp.start()
        logger.info("MCP ops/docs 연결 완료. 그래프 구성 중…")
        backend, fast, quality = _build_llms(mode=mode)
        deps = SupervisorDeps(
            fast, quality, mcp, store, os.getenv("SUPERVISOR_VERSION", "v2")
        )
        app.state.deps = deps
        app.state.mode = mode
        app.state.llm_backend = backend
        app.state.locks = WeakValueDictionary()
        builder = build_baseline_graph if mode == "baseline" else build_graph
        app.state.graph = builder(deps) if deps.version == "v2" else None
        logger.info(
            "구성 완료: backend=%s, mode=%s, fast=%s, quality=%s",
            backend,
            mode,
            fast.name,
            quality.name,
        )
        yield
    finally:
        await mcp.stop()
        store.close()
        # traceable's shared client uses background batching; flush before exit.
        from langsmith.run_trees import get_cached_client

        get_cached_client().flush()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    d = app.state.deps
    return {
        "status": "ok",
        "agent_mode": app.state.mode,
        "instance_id": id(d),
        "creation_count": CREATION_COUNT,
        "supervisor_version": d.version,
        "llm_backend": app.state.llm_backend,
        "fast_llm": d.fast_llm.name,
        "quality_llm": d.quality_llm.name,
        "ollama_think": os.getenv("OLLAMA_THINK", "false")
        if app.state.llm_backend == "ollama" and app.state.mode == "improved"
        else None,
    }


@app.get("/version")
async def version():
    return {"supervisor_version": app.state.deps.version, "agent_mode": app.state.mode}


@app.get("/systems")
async def systems():
    from agent.nodes.targeting import catalog

    return {"systems": list(catalog())}


def _metadata(result, run_id):
    return {
        "route": result.get("route"),
        "targets": result.get("targets", []),
        "task_count": len(result.get("tasks", [])),
        "retry_count": result.get("retry_count", 0),
        "validation_attempts": result.get("validation_attempts", 0),
        "validation_ok": result.get("validation_ok"),
        "cost_usd": result.get("cost_usd", 0),
        "cost_note": "educational estimate; not actual billing",
        "llm_backend": app.state.llm_backend,
        "agent_mode": app.state.mode,
        "langsmith_run_id": run_id,
        "context": result.get("context_metrics", {}),
    }


@traceable(name="chat_request")
async def _execute(message, thread_id):
    deps = app.state.deps
    # Serialize turns of one conversation, while allowing unrelated threads.
    lock = app.state.locks.setdefault(thread_id, asyncio.Lock())
    async with lock:
        history, metrics = deps.session_store.load_context(
            thread_id, enabled=app.state.mode == "improved"
        )
        result = {
            "query": message,
            "thread_id": thread_id,
            "history": history,
            "events": [],
            "cost_usd": 0.0,
            "context_metrics": metrics,
        }
        if deps.version != "v2":
            result.update(await run_v1(deps, message, thread_id, history))
            for event in result.get("events", []):
                yield event
        else:
            seen = 0
            async for mode, payload in app.state.graph.astream(
                result, stream_mode=["updates", "custom"]
            ):
                if mode == "custom":
                    # Baseline token behavior is preserved for comparison.
                    yield payload
                    continue
                for node_name, delta in payload.items():
                    if not delta:
                        continue
                    result.update(delta)
                    events = delta.get("events")
                    if events is not None:
                        for ev in events[seen:]:
                            yield {**ev, "node": node_name}
                        seen = len(events)
        deps.session_store.append(thread_id, "user", message)
        deps.session_store.append(thread_id, "assistant", result["final"])
        rt = get_current_run_tree()
        response = {
            "type": "FinalAnswer",
            "reply": result["final"],
            "evidence": result.get("evidence", []),
            "warnings": result.get("warnings", []),
            "metadata": _metadata(result, str(rt.id) if rt else None),
        }
        if os.getenv("DEBUG_PROMPTS") == "1":
            response["prompt"] = result.get("last_prompt")
        yield response


@app.post("/chat")
async def chat(req: ChatRequest):
    events = []
    try:
        async with asyncio.timeout(float(os.getenv("REQUEST_TIMEOUT_SECONDS", "180"))):
            async for event in _execute(req.message, req.thread_id):
                if event["type"] == "FinalAnswer":
                    response = {k: v for k, v in event.items() if k != "type"}
                elif event["type"] != "AnswerToken":
                    events.append(event)
    except TimeoutError:
        raise HTTPException(
            504, "처리 제한 시간을 초과했습니다. 모델 설정과 연결을 확인하세요."
        ) from None
    return {**response, "events": events}


@app.get("/chat/stream")
async def chat_stream(
    message: str = Query(min_length=1, max_length=10000),
    thread_id: str = Query(default="default", min_length=1, max_length=128),
):
    async def gen():
        queue = asyncio.Queue(maxsize=64)
        started = asyncio.get_running_loop().time()

        async def produce():
            try:
                async with asyncio.timeout(
                    float(os.getenv("REQUEST_TIMEOUT_SECONDS", "180"))
                ):
                    async for event in _execute(message, thread_id):
                        await queue.put(event)
            except Exception as exc:
                await queue.put(
                    {
                        "type": "Error",
                        "message": "처리 제한 시간을 초과했습니다. 모델 설정과 연결을 확인하세요."
                        if isinstance(exc, TimeoutError)
                        else "요청을 완료하지 못했습니다. 서버 로그와 연결 설정을 확인하세요.",
                        "error_type": type(exc).__name__,
                    }
                )
            finally:
                if not asyncio.current_task().cancelling():
                    await queue.put(None)

        task = asyncio.create_task(produce())
        try:
            yield "data: " + json.dumps({"type": "RequestStarted"}) + "\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5)
                except TimeoutError:
                    event = {
                        "type": "Heartbeat",
                        "elapsed_s": int(asyncio.get_running_loop().time() - started),
                    }
                if event is None:
                    break
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"
        finally:
            task.cancel()
            # Disconnects cancel request-local work; shared MCP sessions stay alive.
            from contextlib import suppress

            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.getenv("PORT", "8100")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
