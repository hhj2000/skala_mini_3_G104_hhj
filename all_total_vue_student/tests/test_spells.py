import json
import pytest
from fastapi.testclient import TestClient
from kharakteres.api import app
from kharakteres.models import SpellInput
from kharakteres.store import SpellStore, StaleVersion
from kharakteres.lexicon import review


def spell(**changes):
    return {
        "name": "새벽의 봉합",
        "incantation": "여명아, 흩어진 빛을 이어라.",
        "language": "ko",
        "elements": ["light"],
        "school": "healing",
        "romanization": "",
        "literal_meaning": "흩어진 빛을 이어 상처를 감싼다.",
        "effect": "작은 상처를 달빛으로 치유한다.",
        "target": "한 사람",
        "limitations": "밤에만 시전 가능",
        "world": "달의 서고",
        "notes": "창작 주문",
        "tags": ["회복"],
        "language_status": "author_edited",
        "origin": "manual",
        **changes,
    }


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SPELL_DB_PATH", str(tmp_path / "spells.sqlite"))
    monkeypatch.setenv("LLM_BACKEND", "fake")
    with TestClient(app) as client:
        yield client


def test_generate_does_not_save_and_preserves_constraints(api):
    response = api.post(
        "/api/generate",
        json={
            "prompt": "달빛으로 작은 상처를 치유하는 주문",
            "language": "grc",
            "elements": ["light"],
            "world": "달의 서고",
            "limitations": "밤에만 사용",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["draft"]["language"] == "grc"
    assert data["draft"]["language_status"] == "demo_untranslated"
    assert data["draft"]["school"] == "healing"
    assert "밤에만 사용" in data["draft"]["limitations"]
    assert len(data["steps"]) == 4
    assert data["draft"]["verification"]["status"] == "demo"
    assert api.get("/api/spells").json()["total"] == 0


def test_crud_search_filters_export(api):
    created = api.post("/api/spells", json=spell())
    assert created.status_code == 201
    record = created.json()["spell"]
    assert record["version"] == 1
    assert (
        api.get(
            "/api/spells",
            params={
                "q": "상처 치유",
                "element": "light",
                "language": "ko",
                "school": "healing",
            },
        ).json()["total"]
        == 1
    )
    assert api.get("/api/spells", params={"element": "fire"}).json()["total"] == 0
    assert api.get("/api/spells", params={"q": "존재하지않음"}).json()["total"] == 0
    updated = api.put(
        "/api/spells/" + record["id"], json={**spell(name="수정한 주문"), "version": 1}
    )
    assert updated.status_code == 200
    assert updated.json()["spell"]["version"] == 2
    stale = api.put("/api/spells/" + record["id"], json={**spell(), "version": 1})
    assert stale.status_code == 409
    exported = api.get("/api/spells/export").json()
    assert exported["spells"][0]["name"] == "수정한 주문"
    assert (
        api.delete("/api/spells/" + record["id"], params={"version": 1}).status_code
        == 409
    )
    assert (
        api.delete("/api/spells/" + record["id"], params={"version": 2}).status_code
        == 204
    )
    assert api.get("/api/spells/" + record["id"]).status_code == 404


def test_collision_requires_acknowledgment_and_world_scope(api):
    assert api.post("/api/spells", json=spell()).status_code == 201
    collision = api.post("/api/spells", json=spell(elements=["fire"], school="attack"))
    assert collision.status_code == 409
    assert any(
        i["kind"] == "definition_mismatch"
        for i in collision.json()["detail"]["conflicts"]["issues"]
    )
    assert (
        api.post("/api/spells", json=spell(acknowledge_conflicts=True)).status_code
        == 201
    )
    assert api.post("/api/spells", json=spell(world="다른 세계관")).status_code == 201
    assert api.get("/api/spells").json()["stats"]["worlds"] == 2


def test_review_excludes_self_and_fake_ai_is_explicit(api):
    record = api.post("/api/spells", json=spell()).json()["spell"]
    result = api.post(
        "/api/review", json={**spell(), "exclude_id": record["id"], "use_ai": True}
    ).json()
    assert result["issues"] == []
    assert "fake" in result["ai_review"]["note"]


def test_validation_and_untrusted_text_are_plain_data(api):
    assert api.post("/api/spells", json=spell(elements=["bad"])).status_code == 422
    assert api.post("/api/spells", json=spell(name=" ")).status_code == 422
    assert (
        api.post(
            "/api/generate", json={"prompt": "x", "elements": ["light"]}
        ).status_code
        == 422
    )
    name = '<img src=x onerror="alert(1)">'
    record = api.post("/api/spells", json=spell(name=name)).json()["spell"]
    assert record["name"] == name
    assert api.get("/health").json()["service"] == "kharakteres"
    assert api.get("/assets/vue.global.prod.js").status_code == 200


def test_store_survives_restart_and_prevents_lost_updates(tmp_path):
    path = tmp_path / "durable.sqlite"
    store = SpellStore(path)
    record = store.create(spell())
    store.close()
    store = SpellStore(path)
    try:
        assert store.get(record["id"])["name"] == "새벽의 봉합"
        store.update(record["id"], spell(name="새 이름"), 1)
        with pytest.raises(StaleVersion):
            store.update(record["id"], spell(), 1)
        assert store.get(record["id"])["name"] == "새 이름"
    finally:
        store.close()


def test_indic_vowel_signs_do_not_collapse_different_spells():
    from kharakteres.lexicon import normalize

    assert normalize("शक्ति") != normalize("शक्त")
    assert normalize(" Lux, esto! ") == normalize("lux esto")


def test_wrong_classical_script_is_not_presented_as_translation(api):
    class WrongScriptModel:
        name = "wrong-script-test"

        def _chat(self, *args, **kwargs):
            return json.dumps(
                {
                    "name": "Incorrect script",
                    "incantation": "Only Latin letters",
                    "literal_meaning": "빛을 비춘다",
                    "effect": "주변을 밝힌다",
                    "school": "utility",
                }
            ), {"usd": 0}

    app.state.generator.backend = "openai"
    app.state.generator.model = WrongScriptModel()
    response = api.post(
        "/api/generate",
        json={
            "prompt": "어두운 방을 비추는 주문",
            "language": "grc",
            "elements": ["light"],
        },
    )
    assert response.status_code == 502
    assert "원문 문자" in response.json()["detail"]
    assert api.get("/api/spells").json()["total"] == 0
