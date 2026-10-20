import asyncio
import socket
import threading
import time
import subprocess
import sys
import httpx
import pytest
from agent.launch import StartupError, check_port, check_openai, check_ollama
from agent.runtime_llm import InteractiveOllamaFastLLM, InteractiveOpenAIQualityLLM
from server import _build_llms


def test_spell_runtime_does_not_import_incident_server():
    result = subprocess.run(
        [sys.executable, "-c", (
            "import sys; import kharakteres.api; import agent.model_factory; "
            "assert 'incident_server' not in sys.modules; "
            "assert 'agent.mcp_client' not in sys.modules"
        )],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_spell_dependencies_do_not_require_mcp(monkeypatch):
    from agent import launch

    monkeypatch.setattr(
        launch.importlib.util, "find_spec",
        lambda name: None if name in {"mcp", "fastmcp"} else object(),
    )
    monkeypatch.setenv("SERVICE_MODE", "spells")
    launch.check_dependencies()
    monkeypatch.setenv("SERVICE_MODE", "incident")
    with pytest.raises(StartupError, match="mcp"):
        launch.check_dependencies()


def test_occupied_port_reports_conflict_without_stopping_listener():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(StartupError, match="하나만 실행"):
            check_port(port)
        assert listener.getsockname()[1] == port


def test_ollama_missing_model_has_pull_instructions(monkeypatch):
    monkeypatch.setenv("OLLAMA_FAST_MODEL", "missing-model:1")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"models": []})
        )
    ) as client:
        with pytest.raises(StartupError, match="ollama pull missing-model:1"):
            check_ollama(client)


def test_ollama_unavailable_does_not_start_daemon_in_check_mode():
    def offline(req):
        raise httpx.ConnectError("offline", request=req)

    with httpx.Client(transport=httpx.MockTransport(offline)) as client:
        with pytest.raises(StartupError, match="ollama serve"):
            check_ollama(client, allow_start=False)


def test_openai_bad_key_error_does_not_echo_secret(monkeypatch):
    secret = "test-secret-never-print"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(401, json={"error": {"message": secret}})
        )
    ) as client:
        with pytest.raises(StartupError) as exc:
            check_openai(client)
        assert "401" in str(exc.value) and secret not in str(exc.value)


def test_model_checks_are_metadata_gets_only(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    seen = []

    def respond(req):
        seen.append(req)
        return httpx.Response(200, json={"id": "model"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        check_openai(client)
    assert seen and all(
        req.method == "GET" and "/models/" in str(req.url) for req in seen
    )


def test_interactive_payload_disables_thinking_and_bounds_generation(monkeypatch):
    monkeypatch.delenv("OLLAMA_THINK", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_PREDICT", raising=False)
    model = InteractiveOllamaFastLLM("qwen3:0.6b", 0)
    payload = model._payload("system", "user", False, {"type": "object"})
    assert payload["think"] is False
    assert payload["options"]["num_predict"] == 768
    assert payload["format"] == {"type": "object"}
    monkeypatch.setenv("OLLAMA_THINK", "true")
    assert model._payload("s", "u", True)["think"] is True


def test_baseline_keeps_original_adapter(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    from agent.ollama_llm import OllamaFastLLM

    assert type(_build_llms(mode="baseline")[1]) is OllamaFastLLM
    assert type(_build_llms(mode="improved")[1]) is InteractiveOllamaFastLLM


def test_openai_write_does_not_block_event_loop(monkeypatch):
    started = threading.Event()

    def slow_chat(self, *args, **kwargs):
        started.set()
        time.sleep(0.1)
        return "1) 점검 절차입니다. 충분한 내용입니다.", {"usd": 0}

    from agent.openai_llm import OpenAILLM

    monkeypatch.setattr(OpenAILLM, "_chat", slow_chat)

    async def check():
        model = InteractiveOpenAIQualityLLM("test", 0)
        task = asyncio.create_task(model.write("query", [], 1, None))
        for i in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set() and not task.done()
        await task

    asyncio.run(check())
