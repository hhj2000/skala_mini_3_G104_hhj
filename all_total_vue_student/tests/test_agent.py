import asyncio
import json
from pathlib import Path
import pytest
from agent.deps import SupervisorDeps
from agent.fake_llm import FastLLM, QualityLLM
from agent.graph import build_graph
from agent.nodes.targeting import extract_targets
from agent.session_store import SqliteSessionStore

ROOT = Path(__file__).resolve().parents[1]


class StubMCP:
    def __init__(self, failed=None, no_hits=False):
        self.calls = []
        self.failed = failed
        self.no_hits = no_hits

    async def find_prompt(self, name):
        return "ops"

    async def get_prompt(self, *args, **kwargs):
        return "진단 절차"

    async def find_resource_template(self, name):
        return "docs", "docs://services/{system_name}"

    async def read_resource(self, uri, server):
        self.calls.append(("docs", uri))
        return "# 서비스 설계 문서 (실습용)"

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_monitoring_status":
            target = arguments["system_name"]
            if target == self.failed:
                raise RuntimeError("unavailable")
            d = json.loads((ROOT / "data/monitoring.json").read_text())[target]
            return {
                "system_name": target,
                "status": d["status"],
                "cpu_percent": d["cpu_base"],
                "memory_percent": d["memory_base"],
                "last_checked": "fixed",
                "alerts": d["alerts"],
            }
        if self.no_hits:
            return {"hits": []}
        # Fixture focuses graph behavior; dense retrieval has a separate real test.
        query = arguments["query"]
        incident = "memory-leak" if "heap" in query else "cpu-spike"
        return {
            "hits": [
                {
                    "incident_type": incident,
                    "uri": f"runbook://incident-response/{incident}",
                    "score": 0.9,
                    "embedding_model": "test-fixture",
                    "content": (ROOT / f"data/runbooks/{incident}.md").read_text(),
                }
            ]
        }


def setup(tmp_path, mcp=None, writer=None):
    store = SqliteSessionStore(tmp_path / "test.db")
    deps = SupervisorDeps(
        FastLLM("fake", 0.00015),
        writer or QualityLLM("fake", 0.005),
        mcp or StubMCP(),
        store,
        "v2",
    )
    return deps, build_graph(deps)


def invoke(graph, q, thread="test"):
    return asyncio.run(
        graph.ainvoke(
            {
                "query": q,
                "thread_id": thread,
                "history": [],
                "events": [],
                "cost_usd": 0,
            }
        )
    )


@pytest.mark.parametrize(
    "query",
    [
        "로그인 응답이 느려요",
        "billing-service 장애 진단",
        "auth-service-extra 장애",
        "auth-service와 billing-service 진단",
    ],
)
def test_clarification_does_not_call_monitoring(tmp_path, query):
    deps, g = setup(tmp_path)
    try:
        r = invoke(g, query)
        assert r["clarification"] and not deps.mcp.calls
        assert "어느 시스템" in r["final"]
    finally:
        deps.session_store.close()


def test_followup_preserves_intent_and_selected_target_after_restart(tmp_path):
    deps, g = setup(tmp_path)
    invoke(g, "billing-service 응답 지연 진단")
    deps.session_store.close()
    deps, g = setup(tmp_path)
    try:
        r = invoke(g, "cache-service")
        assert r["targets"] == ["cache-service"]
        assert "응답 지연" in r["effective_query"]
        assert {c["target"] for c in r["collected"] if c["source"] == "monitoring"} == {
            "cache-service"
        }
        assert deps.session_store.get_pending("test") is None
    finally:
        deps.session_store.close()


def test_multisystem_mapping_and_docs(tmp_path):
    deps, g = setup(tmp_path)
    try:
        r = invoke(g, "payments-service와 cache-service 장애 진단")
        pairs = {
            (c["target"], c["incident_type"])
            for c in r["collected"]
            if c["source"] == "runbook"
        }
        assert pairs == {
            ("payments-service", "cpu-spike"),
            ("cache-service", "memory-leak"),
        }
        assert len([c for c in r["collected"] if c["source"] == "docs"]) == 2
        assert r["validation_ok"] and "원인 미확정" in r["final"]
        assert r["validation_attempts"] == 2
        assert any(e["source"] == "monitoring" for e in r["evidence"])
    finally:
        deps.session_store.close()


def test_partial_failure_and_empty_retrieval_are_explicit(tmp_path):
    deps, g = setup(tmp_path, StubMCP(failed="payments-service", no_hits=True))
    try:
        r = invoke(g, "payments-service와 cache-service 진단")
        assert any("조회 실패" in w for w in r["warnings"])
        assert any("매뉴얼이 없습니다" in w for w in r["warnings"])
        assert not any(
            e["target"] == "payments-service" and e["source"] == "monitoring"
            for e in r["evidence"]
        )
    finally:
        deps.session_store.close()


class BadWriter:
    async def write(self, *args, **kwargs):
        return (
            "1) CPU 999%이므로 재시작하세요. 충분한 길이지만 근거 없는 수치가 포함되었습니다.",
            {"usd": 0},
        )


def test_invalid_answer_is_never_force_passed(tmp_path):
    deps, g = setup(tmp_path, writer=BadWriter())
    try:
        r = invoke(g, "payments-service 장애 진단")
        assert r["validation_attempts"] == 3 and not r["validation_ok"]
        assert "999%" not in r["final"]
        assert "검증에 실패" in r["final"]
        assert r["events"][-3]["verdict"] == "실패(최대 시도 도달)"
    finally:
        deps.session_store.close()


def test_healthy_has_no_spurious_runbook(tmp_path):
    deps, g = setup(tmp_path)
    try:
        r = invoke(g, "web-01 상태 진단")
        assert not [c for c in r["collected"] if c["source"] == "runbook"]
    finally:
        deps.session_store.close()


def test_cancel_clears_pending(tmp_path):
    deps, g = setup(tmp_path)
    try:
        invoke(g, "로그인 응답이 느려요")
        assert invoke(g, "취소")["final"] == "진단 요청을 취소했습니다."
        assert deps.session_store.get_pending("test") is None
    finally:
        deps.session_store.close()


def test_context_compaction_retains_identity_and_raw_messages(tmp_path):
    store = SqliteSessionStore(tmp_path / "memory.db")
    try:
        store.append("a", "user", "제 이름은 민수입니다")
        for i in range(15):
            store.append("a", "user", f"요청 {i}: " + "과거의 상세한 질문입니다. " * 30)
            store.append("a", "assistant", "이전 답변입니다. " * 80)
        history, m = store.load_context("a")
        assert (
            m["strategy"] == "extractive" and m["context_chars"] < m["original_chars"]
        )
        assert "제 이름은 민수입니다" in history[0]["content"]
        assert len(store.load("a")) == 31 and store.load("b") == []
        answer, _ = asyncio.run(FastLLM("fake", 0).chat("제 이름이 뭐였죠?", history))
        assert "민수" in answer
    finally:
        store.close()


def test_context_compaction_llm_strategy_and_fallback(tmp_path, monkeypatch):
    store = SqliteSessionStore(tmp_path / "memory_llm.db")
    try:
        monkeypatch.setenv("CONTEXT_SUMMARY_STRATEGY", "llm")
        store.append("llm-thread", "user", "제 이름은 민수입니다")
        for i in range(15):
            store.append("llm-thread", "user", f"요청 {i}: " + "과거의 상세한 질문입니다. " * 30)
            store.append("llm-thread", "assistant", "이전 답변입니다. " * 80)
        history, m = store.load_context(
            "llm-thread", summarizer=lambda t: "사용자가 과거 여러 장애 증상을 문의함."
        )
        assert m["strategy"] == "llm" and m["context_chars"] < m["original_chars"]
        assert "제 이름은 민수입니다" in history[0]["content"]
        assert "사용자가 과거 여러 장애 증상을 문의함." in history[0]["content"]
    finally:
        store.close()


def test_no_substring_target_match():
    assert extract_targets("auth-service-extra 장애") == ([], ["auth-service-extra"])


def test_hyphenated_general_chat_is_not_a_system_request(tmp_path):
    deps, g = setup(tmp_path)
    try:
        result = invoke(g, "안녕, multi-agent란 뭔가요?")
        assert result["route"] == "chat" and not result["clarification"]
        assert not deps.mcp.calls
    finally:
        deps.session_store.close()


class FailingPlanner(FastLLM):
    def plan(self, *args):
        raise ValueError("invalid model output")


def test_planning_model_failure_keeps_exact_targets(tmp_path):
    deps, _ = setup(tmp_path)
    deps.fast_llm = FailingPlanner("failing", 0)
    try:
        r = invoke(build_graph(deps), "cache-service 장애 진단")
        assert r["targets"] == ["cache-service"]
        assert any("계획 생성 실패" in w for w in r["warnings"])
        assert r["validation_ok"]
    finally:
        deps.session_store.close()


def test_total_monitoring_failure_suppresses_diagnosis(tmp_path):
    deps, g = setup(tmp_path, StubMCP(failed="payments-service"))
    try:
        r = invoke(g, "payments-service 진단")
        assert not r["validation_ok"]
        assert "초안은 제공하지 않습니다" in r["final"]
        assert "모니터링 근거가 없어" in r["final"]
    finally:
        deps.session_store.close()
