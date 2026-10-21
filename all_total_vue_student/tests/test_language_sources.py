"""Network-free regressions for real source parsing and stale evidence."""

import asyncio
import json

import httpx
from fastapi.testclient import TestClient
from auth_support import authenticated_client

from kharakteres.api import app
from kharakteres.models import SpellInput
from kharakteres.verification import fingerprint, verify_language, words


def draft(**changes):
    return SpellInput(
        name="빛의 서약",
        incantation="Lux, esto!",
        language="la",
        elements=["light"],
        effect="방 안을 밝힌다",
        hangul_pronunciation="룩스 에스토",
        ipa="/luːks ˈes.toː/",
        **changes,
    ).model_dump()


def test_search_checks_language_section_and_pins_revision():
    def handle(request):
        params = request.url.params
        assert request.url.host == "en.wiktionary.org"
        if params.get("list") == "search":
            return httpx.Response(
                200, json={"query": {"search": [{"title": "lux", "pageid": 1}]}}
            )
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "revisions": [
                                {
                                    "revid": 123,
                                    "slots": {
                                        "main": {
                                            "content": "==English==\n# wrong language\n==Latin==\n===Pronunciation===\n* {{IPA|la|/luːks/}}\n# [[light]]\n==French==\n# wrong meaning\n"
                                        }
                                    },
                                }
                            ]
                        }
                    ]
                }
            },
        )

    result = asyncio.run(
        verify_language(draft(), transport=httpx.MockTransport(handle))
    )
    assert result["status"] == "references_found"
    assert len(result["sources"]) == 1
    source = result["sources"][0]
    assert source["excerpt"] == "light"
    assert source["ipa"] == ["/luːks/"]
    assert source["url"].endswith("oldid=123#Latin")
    assert "미검증" in result["note"]


def test_wrong_language_not_counted_and_network_failure_is_explicit():
    def wrong_language(request):
        if request.url.params.get("list"):
            return httpx.Response(
                200, json={"query": {"search": [{"title": "lux", "pageid": 1}]}}
            )
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "revisions": [
                                {
                                    "revid": 1,
                                    "slots": {
                                        "main": {"content": "==English==\n# light\n"}
                                    },
                                }
                            ]
                        }
                    ]
                }
            },
        )

    assert (
        asyncio.run(
            verify_language(draft(), transport=httpx.MockTransport(wrong_language))
        )["status"]
        == "not_found"
    )
    failed = asyncio.run(
        verify_language(
            draft(), transport=httpx.MockTransport(lambda _: httpx.Response(503))
        )
    )
    assert failed["status"] == "unavailable"
    assert failed["sources"] == []
    demo = asyncio.run(
        verify_language(
            draft(),
            demo=True,
            transport=httpx.MockTransport(
                lambda _: (_ for _ in ()).throw(AssertionError("network in demo"))
            ),
        )
    )
    assert demo["status"] == "demo"


def test_unicode_search_preserves_sanskrit_marks_and_limits_queries():
    assert words("शक्ति, शक्ति! अग्नि जल वायु पृथ्वी") == ["शक्ति", "अग्नि", "जल", "वायु"]


def test_api_persists_pronunciation_and_invalidates_changed_evidence(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SPELL_DB_PATH", str(tmp_path / "spell.sqlite"))
    with authenticated_client(app) as client:
        body = draft()
        body["verification"] = asyncio.run(verify_language(body, demo=True))
        record = client.post("/api/spells", json=body).json()["spell"]
        assert record["ipa"] == body["ipa"]
        assert record["hangul_pronunciation"] == body["hangul_pronunciation"]
        assert record["verification"]["fingerprint"] == fingerprint(body)
        updated = client.put(
            "/api/spells/" + record["id"],
            json={**body, "ipa": "/edited/", "version": 1},
        ).json()["spell"]
        assert updated["verification"]["status"] == "stale"
        assert updated["verification"]["sources"] == []
        assert client.post("/api/verify-language", json=body).json()["status"] == "demo"


def test_language_conversation_uses_selected_model_and_history(tmp_path, monkeypatch):
    class Model:
        name = "selected-quality-model"

        def __init__(self):
            self.seen = []

        def _chat(self, system, user, **kwargs):
            self.seen.append(json.loads(user))
            return json.dumps(
                {
                    "resolved": True,
                    "language": "Ancient Greek",
                    "reply": "고전 그리스어로 준비했습니다.",
                }
            ), {}

    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SPELL_DB_PATH", str(tmp_path / "spell.sqlite"))
    with authenticated_client(app) as client:
        model = Model()
        app.state.generator.backend = "openai"
        app.state.generator.model = model
        result = client.post(
            "/api/language",
            json={
                "message": "고전으로 해 줘",
                "history": [
                    {"role": "user", "text": "그리스어"},
                    {"role": "assistant", "text": "현대인가요 고전인가요?"},
                ],
            },
        )
        assert result.status_code == 200
        assert result.json()["language"] == "grc"
        assert model.seen[0]["history"][0]["text"] == "그리스어"


def test_incomplete_real_pronunciation_response_is_not_saved(tmp_path, monkeypatch):
    class MissingPronunciation:
        name = "test-quality"

        def _chat(self, *args, **kwargs):
            return json.dumps(
                {
                    "name": "Light",
                    "incantation": "Light arise.",
                    "literal_meaning": "빛이 솟아라",
                    "effect": "방을 밝힌다",
                }
            ), {}

    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SPELL_DB_PATH", str(tmp_path / "test.sqlite"))
    with authenticated_client(app) as client:
        app.state.generator.backend = "openai"
        app.state.generator.model = MissingPronunciation()
        result = client.post(
            "/api/generate", json={"language": "en", "prompt": "방 안을 밝히는 주문"}
        )
        assert result.status_code == 502
        assert "한글 전사 또는 IPA" in result.json()["detail"]
        assert client.get("/api/spells").json()["total"] == 0
