"""Resolve explicit targets before any monitoring or LLM planning call."""

import asyncio
import json
import re
from pathlib import Path
from langsmith import traceable

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = re.compile(
    r"(?<![a-zA-Z0-9_-])[a-zA-Z][a-zA-Z0-9_]*(?:-[a-zA-Z0-9_]+)+(?![a-zA-Z0-9_-])"
)
INCIDENT = re.compile(
    r"장애|진단|다운|지연|급증|느[려리]|저하|타임아웃|메모리|디스크|응답|CPU|모니터링|상태|공통 원인|incident|timeout",
    re.I,
)


def catalog():
    return json.loads((ROOT / "data/monitoring.json").read_text())


def extract_targets(query):
    known = catalog()
    explicit = list(dict.fromkeys(IDENTIFIER.findall(query)))
    # Complete identifier boundaries prevent auth-service-extra matching auth-service.
    found = [
        s
        for s in known
        if re.search(r"(?<![a-zA-Z0-9_-])" + re.escape(s) + r"(?![a-zA-Z0-9_-])", query)
    ]
    found.sort(key=query.index)
    return found, [s for s in explicit if s not in known]


@traceable(name="target.resolve")
async def target_node(state, deps):
    query = state["query"]
    pending = deps.session_store.get_pending(state["thread_id"])
    if query.strip() in {"취소", "진단 취소"}:
        deps.session_store.set_pending(state["thread_id"], None)
        return {
            "clarification": True,
            "final": "진단 요청을 취소했습니다.",
            "route": "clarify",
            "events": state.get("events", []) + [{"type": "ClarificationCancelled"}],
        }
    targets, unknown = extract_targets(query)
    selection = bool(pending and targets and not INCIDENT.search(query))
    effective = pending + "\n진단 대상: " + query if selection else query
    if selection:
        targets, unknown = extract_targets(query)
    is_incident = bool(
        targets
        or INCIDENT.search(query)
        or any(re.search(r"-service(?:-|$)|-\d+$", name) for name in unknown)
    )
    if is_incident and (unknown or not targets):
        # Keep symptom intent, but exclude the unregistered identifier on follow-up.
        intent = pending if pending and not INCIDENT.search(query) else query
        deps.session_store.set_pending(state["thread_id"], intent)
        reason = (
            "등록되지 않은 시스템: " + ", ".join(unknown)
            if unknown
            else "진단할 시스템이 지정되지 않았습니다."
        )
        choices = list(catalog())
        final = (
            reason
            + "\n어느 시스템을 진단할까요? 시스템명을 선택하거나 입력해 주세요.\n"
            + ", ".join(choices)
        )
        return {
            "targets": targets,
            "unknown_targets": unknown,
            "clarification": True,
            "route": "clarify",
            "final": final,
            "events": state.get("events", [])
            + [
                {
                    "type": "ClarificationRequired",
                    "choices": choices,
                    "unknown": unknown,
                }
            ],
        }
    if is_incident:
        deps.session_store.set_pending(state["thread_id"], None)
    return {
        "targets": targets,
        "unknown_targets": [],
        "clarification": False,
        "effective_query": effective,
        "route": "incident" if is_incident else "chat",
        "events": state.get("events", [])
        + [{"type": "TargetsResolved", "targets": targets}],
    }


@traceable(name="plan_node")
async def plan_node(state, deps):
    server = await deps.mcp.find_prompt("incident_analysis_prompt")
    procedure = await deps.mcp.get_prompt(
        "incident_analysis_prompt",
        {
            "system_name": ", ".join(state["targets"]),
            "symptom": state["effective_query"],
        },
        server=server,
    )
    warnings = list(state.get("warnings", []))
    try:
        result, usage = await asyncio.to_thread(
            deps.fast_llm.plan, state["effective_query"], procedure
        )
    except Exception as exc:
        result, usage = {"tasks": []}, {"usd": 0}
        warnings.append(
            f"LLM 계획 생성 실패 ({type(exc).__name__}); 명시된 대상의 표준 조사만 수행했습니다."
        )
    # Exact user-selected targets override missing, hallucinated or extra LLM tasks.
    tasks = [
        {
            "id": f"monitor-{s}",
            "agent": "research",
            "kind": "monitoring",
            "target": s,
            "status": "pending",
        }
        for s in state["targets"]
    ]
    needs_analysis = len(state["targets"]) > 1
    return {
        "tasks": tasks,
        "needs_analysis": needs_analysis,
        "warnings": warnings,
        "cost_usd": state.get("cost_usd", 0) + usage.get("usd", 0),
        "events": state["events"]
        + [
            {
                "type": "PlanCreated",
                "targets": state["targets"],
                "task_count": len(tasks),
                "model_task_count": len(result.get("tasks", [])),
            }
        ],
    }
