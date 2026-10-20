"""Reproducible graph comparison with real MCP tools and an explicit LLM backend.

Default fake is a pipeline regression, NOT an LLM quality benchmark. --trace
uploads traces and evaluation feedback to the user's configured LangSmith.
"""

import argparse
import asyncio
import csv
import json
import os
import statistics
import sys
import tempfile
import time
from uuid import uuid4
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def score(case, result):
    collected = result.get("collected", [])
    targets = sorted(
        c["data"]["system_name"] for c in collected if c["source"] == "monitoring"
    )
    clarification = bool(result.get("clarification"))
    if case["clarify"]:
        target_ok = clarification and not targets
    elif case["chat"]:
        target_ok = result.get("route") == "chat" and not targets
    else:
        target_ok = sorted(case["targets"]) == targets and not clarification
    retrieved = {
        c.get("incident_type") or c.get("data", "").splitlines()[0]
        for c in collected
        if c["source"] == "runbook"
    }
    # Baseline sources lack URI metadata: recover IDs from exact corpus content.
    content_ids = {p.read_text(): p.stem for p in (ROOT / "data/runbooks").glob("*.md")}
    retrieved = {
        c.get("incident_type") or content_ids.get(c["data"], "unknown")
        for c in collected
        if c["source"] == "runbook"
    }
    expected = set(case["runbooks"])
    recall = (
        len(expected & retrieved) / len(expected) if expected else float(not retrieved)
    )
    precision = (
        len(expected & retrieved) / len(retrieved) if retrieved else float(not expected)
    )
    return {
        "target_correct": int(target_ok),
        "runbook_recall": recall,
        "runbook_precision": precision,
        "targets": targets,
        "runbooks": sorted(retrieved),
        "clarified": clarification,
    }


async def run(args):
    os.environ["MONITORING_FIXED"] = "1"
    os.environ["LLM_BACKEND"] = args.backend
    os.environ["LANGCHAIN_TRACING_V2"] = "true" if args.trace else "false"
    os.environ["LANGSMITH_TRACING"] = "true" if args.trace else "false"
    os.environ["LANGCHAIN_PROJECT"] = f"mini-project-evaluation-{args.backend}"
    os.environ["LANGSMITH_PROJECT"] = os.environ["LANGCHAIN_PROJECT"]
    from agent.baseline_graph import build_graph as baseline
    from agent.graph import build_graph as improved
    from agent.deps import SupervisorDeps
    from agent.session_store import SqliteSessionStore
    from agent.mcp_client import MCPClient
    from server import _build_llms
    from langsmith import traceable, Client

    cases = json.loads((ROOT / "eval/cases.json").read_text())
    if args.case_ids:
        requested = set(args.case_ids.split(","))
        cases = [c for c in cases if c["id"] in requested]
        if len(cases) != len(requested):
            raise ValueError("Unknown case id")
    client = Client() if args.trace else None
    project_id = None
    if client:
        try:
            project_id = client.read_project(
                project_name=os.environ["LANGCHAIN_PROJECT"]
            ).id
        except Exception:
            project_id = client.create_project(
                project_name=os.environ["LANGCHAIN_PROJECT"]
            ).id
    batch_id = str(uuid4())
    records = []
    mcp = MCPClient(flaky_first_tool_call=False)
    try:
        await mcp.start()
        # Warm model/index outside timed requests; report separately.
        start = time.perf_counter()
        await mcp.call_tool("search_runbooks", {"query": "CPU saturation", "top_k": 1})
        warmup = time.perf_counter() - start
        with tempfile.TemporaryDirectory() as tmp:
            for repeat in range(args.repeats):
                for case in cases:
                    # Alternate order to reduce a systematic warm-cache advantage.
                    modes = [("baseline", baseline), ("improved", improved)]
                    if repeat % 2:
                        modes.reverse()
                    for mode, builder in modes:
                        backend, fast, quality = _build_llms(mode=mode)
                        store = SqliteSessionStore(
                            Path(tmp) / f"{repeat}-{case['id']}-{mode}.db"
                        )
                        deps = SupervisorDeps(fast, quality, mcp, store, "v2")
                        graph = builder(deps)

                        @traceable(
                            name=f"eval.{mode}",
                            metadata={
                                "case_id": case["id"],
                                "repeat": repeat,
                                "backend": backend,
                                "batch_id": batch_id,
                            },
                        )
                        async def invoke():
                            return await graph.ainvoke(
                                {
                                    "query": case["query"],
                                    "thread_id": case["id"],
                                    "history": [],
                                    "events": [],
                                    "cost_usd": 0.0,
                                }
                            )

                        started = time.perf_counter()
                        try:
                            run_id = uuid4()
                            result = await invoke(
                                langsmith_extra={
                                    "run_id": run_id,
                                    "tags": [mode, backend, case["id"]],
                                }
                            )
                            row = {
                                "case_id": case["id"],
                                "mode": mode,
                                "repeat": repeat,
                                "backend": backend,
                                "latency_s": round(time.perf_counter() - started, 4),
                                **score(case, result),
                                "cost_usd_estimate": result.get("cost_usd", 0),
                                "validation_attempts": result.get(
                                    "validation_attempts", 0
                                ),
                                "retry_count": result.get("retry_count", 0),
                                "validation_ok": result.get("validation_ok"),
                                "reply": result.get("final"),
                                "evidence": result.get("evidence", []),
                                "warnings": result.get("warnings", []),
                                "error": None,
                            }
                            if client:
                                for metric in [
                                    "target_correct",
                                    "runbook_recall",
                                    "runbook_precision",
                                ]:
                                    client.create_feedback(
                                        run_id=run_id,
                                        trace_id=run_id,
                                        session_id=project_id,
                                        key=metric,
                                        score=row[metric],
                                    )
                                row["langsmith_run_id"] = str(run_id)
                        except Exception as exc:
                            row = {
                                "case_id": case["id"],
                                "mode": mode,
                                "repeat": repeat,
                                "backend": backend,
                                "error": type(exc).__name__ + ": " + str(exc),
                                "latency_s": round(time.perf_counter() - started, 4),
                                "target_correct": 0,
                                "runbook_recall": 0,
                                "runbook_precision": 0,
                            }
                        finally:
                            store.close()
                        records.append(row)
                        print(
                            f"{mode:8} {case['id']:20} target={row['target_correct']} recall={row['runbook_recall']:.2f} {row['latency_s']:.3f}s"
                            + (" ERROR" if row["error"] else ""),
                            flush=True,
                        )
    finally:
        await mcp.stop()
    summary = {
        "batch_id": batch_id,
        "backend": args.backend,
        "repeats": args.repeats,
        "cases": len(cases),
        "warmup_s": round(warmup, 4),
        "monitoring_fixed": True,
        "trace_enabled": args.trace,
        "notes": [
            "fake results measure control flow, not real LLM reasoning quality",
            "baseline contains an intentional 0.35-second/task delay; latency is not solely a RAG comparison",
            "cost is an educational token estimate, not actual billing",
            "runbook metrics are case-level type coverage, not proof of per-system citation correctness",
        ],
        "modes": {},
    }
    for mode in ["baseline", "improved"]:
        rows = [x for x in records if x["mode"] == mode]
        summary["modes"][mode] = {
            "target_accuracy": round(
                statistics.mean(x["target_correct"] for x in rows), 4
            ),
            "runbook_recall": round(
                statistics.mean(x["runbook_recall"] for x in rows), 4
            ),
            "runbook_precision": round(
                statistics.mean(x["runbook_precision"] for x in rows), 4
            ),
            "median_latency_s": round(
                statistics.median(x["latency_s"] for x in rows), 4
            ),
            "errors": sum(bool(x["error"]) for x in rows),
        }
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (out / "results.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
    fields = sorted({k for row in records for k in row})
    with (out / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(records)
    lines = [
        "# 개선 전후 평가 결과",
        "",
        f"Backend: {args.backend}; 사례 {len(cases)}개 × {args.repeats}회",
        "",
        "| 모드 | 대상 처리 정확도 | Runbook recall | Runbook precision | 요청 중앙값(초) | 오류 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for mode, m in summary["modes"].items():
        lines.append(
            f"| {mode} | {m['target_accuracy']:.1%} | {m['runbook_recall']:.1%} | {m['runbook_precision']:.1%} | {m['median_latency_s']} | {m['errors']} |"
        )
    lines += [
        "",
        "주의: fake는 제어 흐름 검증입니다. 기준선의 인위적 지연, 사례 구성, 실제 모델 차이를 고려하세요. 지표 정의는 eval/README.md를 참조하세요.",
        "",
        f"Batch ID: {batch_id}",
    ]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if client:
        from langsmith.run_trees import get_cached_client

        get_cached_client().flush()
    if any(row["error"] for row in records):
        raise SystemExit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=["fake", "ollama", "openai"], default="fake")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--trace", action="store_true")
    p.add_argument(
        "--case-ids",
        help="Comma-separated case ids for a smaller real-model smoke test",
    )
    p.add_argument("--output", default=None)
    args = p.parse_args()
    if args.output is None:
        args.output = str(ROOT / "eval/results" / args.backend)
    if args.repeats < 1:
        p.error("--repeats must be positive")
    asyncio.run(run(args))
