"""Evidence is rendered from tool output; model prose is explicitly a hypothesis."""

import asyncio
import re
from langsmith import traceable
from ..fake_llm import QualityLLM


@traceable(run_type="llm", name="improved_fake.write")
async def fake_write(llm, state, attempt):
    if attempt == 1:
        draft = "확인 중입니다."
    else:
        lines = ["1) 수집한 시스템별 지표와 알림을 먼저 확인하세요."]
        for c in state.get("collected", []):
            if c["source"] == "runbook":
                title = c["data"].splitlines()[0].lstrip("# ")
                lines.append(
                    f"- {c['target']}: {title}를 참고해 증상과 적용 조건을 점검하세요."
                )
        lines += [
            "2) 서비스 문서는 설계 참고 자료이며 현재 장애의 원인을 입증하지 않습니다.",
            "3) 원인은 미확정입니다. 추가 로그와 지표 추세를 확보한 뒤 담당자가 조치 여부를 결정하세요.",
        ]
        draft = "\n".join(lines)
    return draft, llm._usage(
        state["effective_query"] + str(state.get("collected", [])), draft
    )


@traceable(name="analysis_node")
async def analysis_node(state, deps):
    if not state.get("needs_analysis"):
        return {}
    # A coincident degradation alone does not establish a shared cause.
    try:
        summary, usage = await asyncio.to_thread(
            deps.fast_llm.analyze, state["collected"]
        )
    except Exception as exc:
        return {
            "warnings": state.get("warnings", [])
            + [f"비교 분석 실패 ({type(exc).__name__})"],
            "events": state["events"]
            + [{"type": "AnalysisSkipped", "reason": "model failure"}],
        }
    return {
        "collected": state["collected"]
        + [{"source": "analysis", "data": "미확정 가설 (인과관계 미입증): " + summary}],
        "cost_usd": state.get("cost_usd", 0) + usage.get("usd", 0),
        "events": state["events"] + [{"type": "AnalysisCompleted"}],
    }


@traceable(name="write_node")
async def write_node(state, deps):
    attempt = state.get("validation_attempts", 0) + 1
    # Existing writers understand monitoring/runbook/analysis; docs are supplied as
    # reference text, with explicit provenance. The canonical evidence remains intact.
    material = []
    for c in state.get("collected", []):
        if c["source"] == "docs":
            material.append(
                {
                    "source": "runbook",
                    "data": f"참고 서비스 문서 [{c['uri']}] (설계 설명이며 관측 사실 아님):\n{c['data']}",
                }
            )
        else:
            material.append(c)
    instruction = (
        state["effective_query"]
        + "\n답변은 미확정 원인 가설과 권장 점검 절차로 작성하세요. "
        "수집되지 않은 수치를 만들지 마세요. 공통 원인은 입증되지 않았습니다. "
        "조치는 제안만 하며 자동 실행하지 않습니다."
    )
    if not any(c["source"] == "monitoring" for c in state.get("collected", [])):
        return {
            "draft": "",
            "validation_attempts": 2,
            "events": state["events"]
            + [{"type": "WriteSkipped", "reason": "no monitoring evidence"}],
        }
    try:
        if isinstance(deps.quality_llm, QualityLLM):
            draft, usage = await fake_write(deps.quality_llm, state, attempt)
        else:
            draft, usage = await deps.quality_llm.write(
                instruction,
                material,
                attempt,
                state.get("validation_feedback"),
                on_token=None,
            )
    except Exception as exc:
        return {
            "draft": "",
            "validation_attempts": 2,
            "warnings": state.get("warnings", [])
            + [f"AI 보고서 작성 실패 ({type(exc).__name__})"],
            "events": state["events"]
            + [{"type": "WriteFailed", "error_type": type(exc).__name__}],
        }
    # Unvalidated drafts are not streamed to the user.
    return {
        "draft": draft,
        "last_prompt": usage.get("prompt"),
        "cost_usd": state.get("cost_usd", 0) + usage.get("usd", 0),
        "events": state["events"]
        + [{"type": "DraftWritten", "attempt": attempt, "length": len(draft)}],
    }


@traceable(name="validate_node")
async def validate_node(state, deps):
    draft = state["draft"]
    errors = []
    if len(draft) < 30 or "1)" not in draft:
        errors.append("30자 이상, 1) 2) 번호로 점검 절차를 작성하세요.")
    # A bounded numerical check, not a claim of general hallucination detection.
    allowed = set()
    for c in state.get("collected", []):
        if c["source"] == "monitoring":
            allowed.update(
                float(c["data"][k]) for k in ("cpu_percent", "memory_percent")
            )
            allowed.update(
                float(x)
                for x in re.findall(
                    r"(\d+(?:\.\d+)?)%", " ".join(c["data"].get("alerts", []))
                )
            )
        elif c["source"] == "runbook":
            allowed.update(float(x) for x in re.findall(r"(\d+(?:\.\d+)?)%", c["data"]))
    invented = [
        x for x in re.findall(r"(\d+(?:\.\d+)?)%", draft) if float(x) not in allowed
    ]
    if invented:
        errors.append("근거에 없는 백분율을 제거하세요: " + ", ".join(invented))
    attempts = state.get("validation_attempts", 0) + 1
    ok = not errors
    return {
        "validation_attempts": attempts,
        "validation_ok": ok,
        "validation_feedback": " ".join(errors) if errors else None,
        "events": state["events"]
        + [
            {
                "type": "Validation",
                "attempt": attempts,
                "verdict": "합격"
                if ok
                else ("실패(최대 시도 도달)" if attempts >= 3 else "불합격"),
                "errors": errors,
            }
        ],
    }


@traceable(name="finalize_node")
async def finalize_node(state, deps):
    evidence = []
    lines = ["[확인된 사실 · 시뮬레이션 모니터링]"]
    for c in state.get("collected", []):
        if c["source"] == "analysis":
            continue
        item = {
            k: c[k]
            for k in (
                "source",
                "target",
                "uri",
                "incident_type",
                "score",
                "embedding_model",
            )
            if k in c
        }
        item["id"] = f"E{len(evidence) + 1}"
        item["data"] = c["data"]
        evidence.append(item)
        if c["source"] == "monitoring":
            d = c["data"]
            lines.append(
                f"[{item['id']}] {c['target']}: 상태={d['status']}, CPU={d['cpu_percent']}%, 메모리={d['memory_percent']}%, 조회={d['last_checked']}; 알림={'; '.join(d.get('alerts', [])) or '없음'}"
            )
    lines.append("\n[참고 문서 · 관측 사실과 구분]")
    for e in evidence:
        if e["source"] != "monitoring":
            lines.append(
                f"[{e['id']}] {e['target']} → {e['uri']}"
                + (f" (유사도={e['score']})" if "score" in e else "")
            )
    lines.append("\n[AI 해석·권장 점검 · 원인 미확정]")
    lines.append(
        state["draft"]
        if state.get("validation_ok")
        else "답변 검증에 실패하여 AI 초안은 제공하지 않습니다. 위 근거를 바탕으로 담당자가 추가 조사해 주세요."
    )
    warnings = list(state.get("warnings", []))
    if not any(e["source"] == "monitoring" for e in evidence):
        warnings.append("확보된 모니터링 근거가 없어 진단을 확정할 수 없습니다.")
    lines.append(
        "\n[한계] 문서 검색 점수는 원인 확률이 아닙니다. 현재 데이터로 인과관계를 확정할 수 없으며, 조치는 자동 실행하지 않습니다."
    )
    if warnings:
        lines.append("\n[추가 확인 필요] " + " / ".join(warnings))
    reply = "\n".join(lines)
    return {
        "final": reply,
        "evidence": evidence,
        "warnings": warnings,
        "events": state["events"]
        + [
            {"type": "EvidenceReady", "count": len(evidence)},
            {"type": "Finalize", "pipeline": "incident-improved"},
        ],
    }


@traceable(name="chat_answer_node")
async def chat_answer_node(state, deps):
    reply, usage = await deps.fast_llm.chat(
        state["query"], state.get("history", []), on_token=None
    )
    return {
        "final": reply,
        "cost_usd": state.get("cost_usd", 0) + usage.get("usd", 0),
        "events": state.get("events", [])
        + [{"type": "Finalize", "pipeline": "chat-direct"}],
    }
