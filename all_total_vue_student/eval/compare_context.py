"""Reproducible extractive-context measurement, without LLM calls."""

import json
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.session_store import SqliteSessionStore

with tempfile.TemporaryDirectory() as tmp:
    store = SqliteSessionStore(Path(tmp) / "memory.db")
    store.append("context", "user", "제 이름은 민수입니다")
    for i in range(15):
        store.append(
            "context",
            "user",
            f"질문 {i}: " + "장애 증상과 점검 요청에 관한 과거 대화입니다. " * 20,
        )
        store.append("context", "assistant", "이전 진단 보고서입니다. " * 60)
    original = store.load("context")
    history, metrics = store.load_context("context")
    metrics["identity_retained"] = "제 이름은 민수입니다" in history[0]["content"]
    metrics["raw_messages_retained"] = len(store.load("context")) == len(original)
    metrics["baseline_adapter_last10_chars"] = sum(
        len(m["content"]) for m in original[-10:]
    )
    metrics["improved_adapter_last10_chars"] = sum(
        len(m["content"]) for m in history[-10:]
    )
    store.close()
out = ROOT / "eval/results/context.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
print(
    json.dumps(
        {k: v for k, v in metrics.items() if k != "summary"},
        ensure_ascii=False,
        indent=2,
    )
)
