import json
import pytest
from fastapi.testclient import TestClient
from incident_server import app


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    import os

    os.environ["SESSION_DB_PATH"] = str(tmp_path_factory.mktemp("api") / "session.db")
    with TestClient(app) as client:
        yield client
    del os.environ["SESSION_DB_PATH"]


def events(text):
    return [
        json.loads(s[6:])
        for s in text.splitlines()
        if s.startswith("data: ") and s != "data: [DONE]"
    ]


def test_post_and_sse_equivalence_and_persistence(api):
    q = "cache-service 메모리 장애 진단"
    post = api.post("/chat", json={"message": q, "thread_id": "post"})
    assert post.status_code == 200
    stream = api.get("/chat/stream", params={"message": q, "thread_id": "sse"})
    ev = events(stream.text)
    assert stream.text.endswith("data: [DONE]\n\n")
    assert ev[-1]["reply"] == post.json()["reply"]
    assert ev[-1]["evidence"] == post.json()["evidence"]
    assert ev[-1]["metadata"]["context"]["strategy"] == "raw"
    assert len(app.state.deps.session_store.load("sse")) == 2
    assert any(e["type"] == "ServiceDocRetrieved" for e in ev)
    assert not any(e["type"] == "AnswerToken" for e in ev)


def test_sse_clarification_and_post_followup(api):
    response = api.get(
        "/chat/stream",
        params={"message": "로그인 응답이 느려요", "thread_id": "selection"},
    )
    assert any(e["type"] == "ClarificationRequired" for e in events(response.text))
    result = api.post(
        "/chat", json={"message": "auth-service", "thread_id": "selection"}
    ).json()
    assert result["metadata"]["targets"] == ["auth-service"]
    assert result["evidence"]


def test_input_validation_and_catalog(api):
    assert api.post("/chat", json={"message": ""}).status_code == 422
    assert api.get("/chat/stream", params={"message": ""}).status_code == 422
    assert len(api.get("/systems").json()["systems"]) == 6


def test_request_deadline_returns_actionable_errors(api, monkeypatch):
    import asyncio
    import incident_server as server

    async def slow_execute(message, thread_id):
        await asyncio.sleep(0.2)
        yield {"type": "FinalAnswer", "reply": "late"}

    monkeypatch.setattr(server, "_execute", slow_execute)
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "0.02")
    response = api.post("/chat", json={"message": "test"})
    assert response.status_code == 504
    assert "제한 시간" in response.json()["detail"]
    response = api.get("/chat/stream", params={"message": "test"})
    data = events(response.text)
    assert data[0]["type"] == "RequestStarted"
    assert any(e["type"] == "Error" and "제한 시간" in e["message"] for e in data)
    assert response.text.endswith("data: [DONE]\n\n")
