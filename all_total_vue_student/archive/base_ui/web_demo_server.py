"""Archived Base incident UI proxy. Not used by Kharakteres.

Run with: bash archive/base_ui/run_frontend.sh
Backend: SERVICE_MODE=incident bash sh/run_agent.sh --backend fake
"""

from pathlib import Path
import os

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

BACKEND = os.getenv("BACKEND_URL", "http://127.0.0.1:8100")
HERE = Path(__file__).resolve().parents[2]

app = FastAPI()

from fastapi.staticfiles import StaticFiles

app.mount("/assets", StaticFiles(directory=HERE / "assets"), name="assets")


@app.get("/")
async def index():
    return FileResponse(HERE / "archive/base_ui/incident_web_chat.html")


@app.get("/health")
async def proxy_health():
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BACKEND}/health")
    return JSONResponse(r.json(), status_code=r.status_code)


@app.post("/chat")
async def proxy_chat(req: Request):
    body = await req.body()
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{BACKEND}/chat",
            content=body,
            headers={"content-type": "application/json"},
        )
    return JSONResponse(r.json(), status_code=r.status_code)


@app.get("/chat/stream")
async def proxy_stream(message: str, thread_id: str = "web-demo"):
    async def relay():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET",
                f"{BACKEND}/chat/stream",
                params={"message": message, "thread_id": thread_id},
            ) as upstream:
                async for chunk in upstream.aiter_bytes():
                    yield chunk

    return StreamingResponse(relay(), media_type="text/event-stream")


if __name__ == "__main__":
    print(
        "브라우저에서 http://localhost:8600 을 열어보세요 (server.py가 8100에 떠 있어야 합니다)"
    )
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("FRONTEND_PORT", "8600")))
