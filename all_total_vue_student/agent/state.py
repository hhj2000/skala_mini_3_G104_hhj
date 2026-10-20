"""Shared graph state. Evidence is request-local; conversation state lives in SQLite."""

from typing import TypedDict


class AgentState(TypedDict, total=False):
    query: str
    effective_query: str
    thread_id: str
    history: list[dict]
    route: str
    targets: list[str]
    unknown_targets: list[str]
    clarification: bool
    needs_analysis: bool
    tasks: list[dict]
    collected: list[dict]
    evidence: list[dict]
    warnings: list[str]
    events: list[dict]
    context_metrics: dict
    cost_usd: float
    retry_count: int
    parallel_elapsed: float
    draft: str
    final: str
    validation_attempts: int
    validation_feedback: str | None
    validation_ok: bool
    last_prompt: str
