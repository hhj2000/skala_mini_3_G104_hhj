"""Compiled Research subgraph: metrics -> runbooks -> service docs.

Each specialist has a bounded responsibility; no synthetic log-analysis agent is
claimed because the base project has no log data source.
"""

import asyncio
import time
from functools import partial
from langgraph.graph import StateGraph, END
from langsmith import traceable
from ..state import AgentState
from ..retry import with_retry


@traceable(name="research.metrics")
async def metrics_node(state, deps):
    async def one(target):
        try:
            data, retries = await with_retry(
                deps.mcp.call_tool, "get_monitoring_status", {"system_name": target}
            )
            return (
                {
                    "source": "monitoring",
                    "target": target,
                    "uri": f"monitoring://{target}",
                    "data": data,
                },
                retries,
                None,
            )
        except Exception as exc:
            return None, 0, f"{target}: 모니터링 조회 실패 ({type(exc).__name__})"

    started = time.perf_counter()
    results = await asyncio.gather(*(one(t) for t in state["targets"]))
    collected = [r[0] for r in results if r[0]]
    warnings = list(state.get("warnings", [])) + [r[2] for r in results if r[2]]
    return {
        "collected": collected,
        "warnings": warnings,
        "retry_count": sum(r[1] for r in results),
        "parallel_elapsed": round(time.perf_counter() - started, 4),
        "events": state["events"]
        + [
            {
                "type": "MetricsCollected",
                "targets": [c["target"] for c in collected],
                "failures": warnings,
            }
        ],
    }


@traceable(name="research.runbooks")
async def runbooks_node(state, deps):
    collected = list(state.get("collected", []))
    warnings = list(state.get("warnings", []))
    events = list(state["events"])
    for c in list(collected):
        if c["source"] != "monitoring":
            continue
        d = c["data"]
        if d.get("status") in {"healthy", "unknown"} and not d.get("alerts"):
            events.append(
                {
                    "type": "RunbookSkipped",
                    "target": c["target"],
                    "reason": "관측된 이상 징후 없음",
                }
            )
            continue
        # Search each system's observations, never concatenate other systems' symptoms.
        search_query = " ".join(d.get("alerts", [])) or d.get("status", "")
        try:
            result = await deps.mcp.call_tool(
                "search_runbooks", {"query": search_query, "top_k": 2}
            )
            hits = result["hits"]
            for hit in hits:
                collected.append(
                    {
                        "source": "runbook",
                        "target": c["target"],
                        "uri": hit["uri"],
                        "incident_type": hit["incident_type"],
                        "score": hit["score"],
                        "embedding_model": hit["embedding_model"],
                        "data": hit["content"],
                    }
                )
            if not hits:
                warnings.append(
                    c["target"]
                    + ": 검색 임계값을 넘는 매뉴얼이 없습니다. 추가 조사가 필요합니다."
                )
            events.append(
                {
                    "type": "RunbooksRetrieved",
                    "target": c["target"],
                    "query": search_query,
                    "hits": [{"uri": h["uri"], "score": h["score"]} for h in hits],
                }
            )
        except Exception as exc:
            warnings.append(f"{c['target']}: RAG 검색 실패 ({type(exc).__name__})")
    return {"collected": collected, "warnings": warnings, "events": events}


@traceable(name="research.docs")
async def docs_node(state, deps):
    collected = list(state.get("collected", []))
    warnings = list(state.get("warnings", []))
    events = list(state["events"])
    try:
        server, template = await deps.mcp.find_resource_template("get_service_doc")
        for target in state["targets"]:
            try:
                uri = template.format(system_name=target)
                text = await deps.mcp.read_resource(uri, server=server)
                if text.startswith("# Doc Not Found"):
                    warnings.append(f"{target}: 서비스 문서 없음")
                    continue
                collected.append(
                    {"source": "docs", "target": target, "uri": uri, "data": text}
                )
                events.append(
                    {
                        "type": "ServiceDocRetrieved",
                        "target": target,
                        "uri": uri,
                        "server": server,
                    }
                )
            except Exception as exc:
                warnings.append(
                    f"{target}: 서비스 문서 조회 실패 ({type(exc).__name__})"
                )
    except Exception as exc:
        warnings.append(f"docs 서버 탐색 실패 ({type(exc).__name__})")
    return {"collected": collected, "warnings": warnings, "events": events}


def build_research_graph(deps):
    g = StateGraph(AgentState)
    for name, fn in [
        ("metrics", metrics_node),
        ("runbooks", runbooks_node),
        ("service_docs", docs_node),
    ]:
        g.add_node(name, partial(fn, deps=deps))
    g.set_entry_point("metrics")
    g.add_edge("metrics", "runbooks")
    g.add_edge("runbooks", "service_docs")
    g.add_edge("service_docs", END)
    return g.compile(name="research_specialists")
