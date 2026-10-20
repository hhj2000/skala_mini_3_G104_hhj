"""Service entry point. Kharakteres is default; SERVICE_MODE=incident preserves the base."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
from agent.model_factory import _build_llms  # compatibility for existing evaluation scripts

if os.getenv("SERVICE_MODE", "spells") == "incident":
    from incident_server import app
else:
    from kharakteres.api import app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8100")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
