"""Content-policy boundaries and persistent vector retrieval regression."""

import asyncio
import json
import sqlite3

import numpy as np
import pytest
from fastapi.testclient import TestClient
from auth_support import authenticated_client

from kharakteres.api import app
from kharakteres.safety import (
    ContentGuard,
    ContentBlocked,
    SafetyUnavailable,
    rule_category,
)
from kharakteres.retrieval import SpellVectorIndex, SpellRetrieval
from kharakteres.store import SpellStore
from kharakteres.models import GenerateRequest
from test_spells import spell


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SPELL_DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.delenv("CONTENT_FILTER_MODE", raising=False)
    with authenticated_client(app) as client:
        yield client


@pytest.mark.parametrize(
    "text,category",
    [
        ("씨\u200b발", "profanity"),
        ("ㅅ ㅂ", "profanity"),
        ("f.u.c.k", "profanity"),
        ("김치녀를 모욕하는 주문", "hate"),
        ("국민의 힘에 투표하라는 주문", "politics"),
    ],
)
def test_rules_normalize_evasion(text, category):
    assert rule_category(text) == category


@pytest.mark.parametrize(
    "text",
    [
        "별빛 왕국의 왕위 계승 선거",
        "화염으로 악당을 공격하는 주문",
        "시발점을 밝히는 빛",
        "욕설을 하지 않도록 마음을 진정시키는 마법",
    ],
)
def test_fiction_and_benign_mentions_allowed(text):
    assert rule_category(text) is None


def test_block_cannot_be_bypassed_by_manual_save_edit_or_tts(api):
    assert (
        api.post("/api/generate", json={"prompt": "씨발이라는 주문을 만들어"}).json()[
            "detail"
        ]["code"]
        == "content_blocked"
    )
    assert (
        api.post(
            "/api/spells", json=spell(notes="국민의힘을 지지하는 주문")
        ).status_code
        == 422
    )
    record = api.post("/api/spells", json=spell()).json()["spell"]
    response = api.put(
        "/api/spells/" + record["id"], json={**spell(notes="김치녀"), "version": 1}
    )
    assert response.status_code == 422
    assert api.get("/api/spells/" + record["id"]).json()["version"] == 1
    assert (
        api.post("/api/audio/speech", json={"text": "씨발"}).json()["detail"]["stage"]
        == "tts_input"
    )
    assert api.post("/api/language", json={"message": "씨발 한국어"}).status_code == 422


def test_generated_output_and_stt_are_checked(api, monkeypatch):
    class BadOutput:
        name = "test"

        def _chat(self, *args, **kwargs):
            return json.dumps(
                {
                    "name": "씨발",
                    "incantation": "빛이여 깨어나라",
                    "literal_meaning": "빛을 부른다",
                    "effect": "밝힌다",
                    "hangul_pronunciation": "빛이여",
                    "ipa": "/test/",
                    "pronunciation_note": "추정",
                }
            ), {}

    app.state.generator.backend = "openai"
    app.state.generator.model = BadOutput()
    response = api.post("/api/generate", json={"prompt": "작은 방을 밝히는 마법"})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["stage"] == "generated_output"
    assert api.get("/api/spells").json()["total"] == 0
    monkeypatch.setattr(app.state.speech, "require_enabled", lambda: None)

    async def bad_stt(*args):
        return {"text": "씨발", "model": "test"}

    monkeypatch.setattr(app.state.speech, "transcribe", bad_stt)
    assert (
        api.post(
            "/api/audio/transcribe",
            content=b"audio",
            headers={"content-type": "audio/wav"},
        ).json()["detail"]["stage"]
        == "stt_output"
    )


def test_context_classifier_and_fail_closed(monkeypatch):
    monkeypatch.setenv("CONTENT_FILTER_MODE", "model")

    class Model:
        name = "test"

        def _chat(self, *args, **kwargs):
            return '{"allowed":false,"category":"hate"}', {}

    guard = ContentGuard("openai", Model())
    with pytest.raises(ContentBlocked):
        asyncio.run(guard.check("저 집단은 모두 사라져야 한다"))
    guard.model._chat = lambda *a, **k: ("not json", {})
    with pytest.raises(SafetyUnavailable):
        asyncio.run(guard.check("다른 입력"))


class SemanticEmbedder:
    """Deterministic test fixture; production uses the actual ONNX model."""

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        texts = list(texts)
        self.calls += texts
        for text in texts:
            yield np.array(
                [1.0, 0.0]
                if any(word in text for word in ["상처", "회복", "치유"])
                else [0.0, 1.0]
            )


def test_vectors_persist_update_delete_and_keep_world_boundaries(tmp_path):
    store = SpellStore(tmp_path / "spells.sqlite")
    embedder = SemanticEmbedder()
    path = tmp_path / "vectors.sqlite"
    a = store.create(spell())
    b = store.create(
        spell(
            name="불꽃",
            incantation="타올라라",
            effect="적을 불로 공격한다",
            world="다른 세계",
        )
    )
    index = SpellVectorIndex(path, model_name="test-dense", embedder=embedder)
    assert index.rank("다친 사람의 회복", store.all(), {a["id"]})[0]["id"] == a["id"]
    assert len(embedder.calls) == 3
    reloaded = SpellVectorIndex(path, model_name="test-dense", embedder=embedder)
    reloaded.rank("회복", store.all(), {a["id"]})
    assert len(embedder.calls) == 4  # only query, persisted documents reused
    store.update(
        a["id"],
        spell(
            name="불꽃",
            incantation="타올라라",
            effect="적을 불로 공격한다",
            literal_meaning="불타올라",
            tags=["불"],
            notes="화염",
            school="attack",
        ),
        1,
    )
    assert reloaded.rank("회복", store.all(), {a["id"]}) == []
    store.delete(b["id"], 1)
    reloaded.rank("불", store.all(), {a["id"]})
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM spell_vectors").fetchone()[0] == 1
    store.close()


def test_semantic_api_and_generation_receive_vector_context(api):
    row = api.post("/api/spells", json=spell()).json()["spell"]
    retrieval = app.state.retrieval
    retrieval.enabled = True
    retrieval.index.embedder = SemanticEmbedder()
    retrieval.index.model_name = "test-dense"
    response = api.get(
        "/api/spells", params={"q": "다친 사람의 회복", "search_mode": "semantic"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["search_mode"] == "semantic"
    assert response.json()["items"][0]["id"] == row["id"]
    result = api.post(
        "/api/generate",
        json={"prompt": "다친 사람의 회복을 돕는 마법", "world": "달의 서고"},
    )
    assert result.json()["retrieval"]["mode"] == "vector"
    # Changing a constraint is embedded before the next query.
    assert (
        api.get(
            "/api/spells",
            params={"q": "회복", "search_mode": "semantic", "world": "다른 세계"},
        ).json()["items"]
        == []
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_vector_failure_or_disable_reports_fallback(api, monkeypatch, enabled):
    api.post("/api/spells", json=spell())
    app.state.retrieval.enabled = enabled

    def fail(*args, **kwargs):
        raise RuntimeError("offline model")

    monkeypatch.setattr(app.state.retrieval.index, "rank", fail)
    response = api.get("/api/spells", params={"q": "치유", "search_mode": "semantic"})
    assert response.status_code == 200
    assert response.json()["search_mode"] == "text_fallback"
    assert response.json()["retrieval"]["reason"]
    assert len(response.json()["items"]) == 1
    assert api.get("/health").status_code == 200


def test_explicit_real_group_denigration_rule():
    assert (
        rule_category("현실의 특정 민족은 모두 열등하니 쫓아내야 한다는 주문") == "hate"
    )
    assert rule_category("별빛 왕국의 엘프와 드워프가 선거하는 설정") is None
