"""Wave 12 — 프로세스 밖(SQLite 파일)에 두는 세션 저장소.

서버가 재시작돼도(새 프로세스, 새 인스턴스) 같은 session.db 파일을 다시 열므로
대화 이력이 유지된다. in-memory dict였다면 재시작 즉시 소실됐을 상태다.
"""

import sqlite3
import os
import re
from langsmith import traceable
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "session.db"


class SqliteSessionStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.conn = sqlite3.connect(
            os.getenv("SESSION_DB_PATH", str(db_path)), check_same_thread=False
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            " thread_id TEXT, role TEXT, content TEXT, created TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS thread_state (thread_id TEXT PRIMARY KEY, pending TEXT, summary TEXT)"
        )
        self.conn.commit()

    def load(self, thread_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM messages WHERE thread_id=? ORDER BY rowid",
            (thread_id,),
        ).fetchall()
        return [{"role": r, "content": c} for r, c in rows]

    def append(self, thread_id: str, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?)",
            (thread_id, role, content, datetime.now().isoformat()),
        )
        self.conn.commit()

    def get_pending(self, thread_id):
        row = self.conn.execute(
            "SELECT pending FROM thread_state WHERE thread_id=?", (thread_id,)
        ).fetchone()
        return row[0] if row else None

    def set_pending(self, thread_id, query):
        self.conn.execute(
            "INSERT INTO thread_state(thread_id,pending) VALUES (?,?) ON CONFLICT(thread_id) DO UPDATE SET pending=excluded.pending",
            (thread_id, query),
        )
        self.conn.commit()

    @traceable(name="context.compact")
    def load_context(self, thread_id, enabled=True, summarizer=None):
        history = self.load(thread_id)
        original_chars = sum(len(m["content"]) for m in history)
        threshold = max(8, int(os.getenv("CONTEXT_SUMMARY_AFTER_MESSAGES", "20")))
        recent_count = 6
        strategy = os.getenv("CONTEXT_SUMMARY_STRATEGY", "extractive").lower()
        summary = ""
        used_strategy = "raw"
        if enabled and len(history) > threshold:
            older, recent = history[:-recent_count], history[-recent_count:]
            # Retain explicit user identity statements across both extractive and llm strategies.
            identities = list(
                dict.fromkeys(
                    match.group(0)
                    for m in older
                    if m["role"] == "user"
                    for match in re.finditer(r"제 이름은 \S+?입니다", m["content"])
                )
            )
            budget = 1000
            pieces = []
            for text in identities:
                if sum(map(len, pieces)) + len(text) <= budget:
                    pieces.append(text)
            llm_summary = ""
            if strategy == "llm" and summarizer is not None:
                try:
                    transcript = "\n".join(
                        f"{m['role']}: {m['content'][:200]}" for m in older[-12:]
                    )
                    llm_text = summarizer(transcript)
                    if llm_text and isinstance(llm_text, str):
                        llm_summary = llm_text.strip()[:600]
                except Exception:
                    llm_summary = ""
            if llm_summary:
                header = "[과거 대화 요약 (LLM 압축) · 사용자 진술 포함]"
                body = ("\n".join(pieces) + "\n" if pieces else "") + llm_summary
                summary = f"{header}\n{body}"
                used_strategy = "llm"
            else:
                # Extractive summary, no extra LLM cost. Identity is retained before
                # recent user statements; raw turns remain available in messages.
                for m in reversed(older):
                    if m["role"] != "user":
                        continue
                    text = m["content"][:160]
                    if text not in pieces and sum(map(len, pieces)) + len(text) <= budget:
                        pieces.append(text)
                summary = (
                    "[과거 대화 발췌 요약 · 사용자 진술이며 검증된 관측 아님]\n"
                    + "\n".join(pieces)
                )
                used_strategy = "extractive"
            compressed = [{"role": "system", "content": summary}] + recent
            if sum(len(m["content"]) for m in compressed) < original_chars:
                history = compressed
            else:
                summary = ""
                used_strategy = "raw"
            self.conn.execute(
                "INSERT INTO thread_state(thread_id,summary) VALUES (?,?) ON CONFLICT(thread_id) DO UPDATE SET summary=excluded.summary",
                (thread_id, summary),
            )
            self.conn.commit()
        chars = sum(len(m["content"]) for m in history)
        return history, {
            "strategy": used_strategy if summary else "raw",
            "original_chars": original_chars,
            "context_chars": chars,
            "reduction_ratio": round(1 - chars / original_chars, 4)
            if original_chars
            else 0,
            "estimated_tokens_before": (original_chars + 3) // 4,
            "estimated_tokens_after": (chars + 3) // 4,
            "token_estimate_note": "characters/4 approximation, not provider billing",
            "summary": summary,
        }

    def close(self) -> None:
        self.conn.close()
