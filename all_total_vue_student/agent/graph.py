"""Improved supervisor. Use AGENT_MODE=baseline for the preserved v2 graph."""

from functools import partial
from langgraph.graph import StateGraph, END
from .state import AgentState
from .nodes.targeting import target_node, plan_node
from .nodes.research import build_research_graph
from .nodes.reporting import (
    analysis_node,
    write_node,
    validate_node,
    finalize_node,
    chat_answer_node,
)


def after_target(state):
    if state.get("clarification"):
        return END
    return "plan" if state["route"] == "incident" else "chat_answer"


def after_validation(state):
    return (
        "finalize"
        if state.get("validation_ok") or state.get("validation_attempts", 0) >= 3
        else "write"
    )


def build_graph(deps):
    g = StateGraph(AgentState)
    for name, fn in [
        ("target", target_node),
        ("plan", plan_node),
        ("analysis", analysis_node),
        ("write", write_node),
        ("validate", validate_node),
        ("finalize", finalize_node),
        ("chat_answer", chat_answer_node),
    ]:
        g.add_node(name, partial(fn, deps=deps))
    g.add_node("research", build_research_graph(deps))
    g.set_entry_point("target")
    g.add_conditional_edges(
        "target", after_target, {END: END, "plan": "plan", "chat_answer": "chat_answer"}
    )
    g.add_edge("chat_answer", END)
    for a, b in [
        ("plan", "research"),
        ("research", "analysis"),
        ("analysis", "write"),
        ("write", "validate"),
        ("finalize", END),
    ]:
        g.add_edge(a, b)
    g.add_conditional_edges(
        "validate", after_validation, {"write": "write", "finalize": "finalize"}
    )
    return g.compile(name="incident_supervisor")
