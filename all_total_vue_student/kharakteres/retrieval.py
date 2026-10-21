"""계정별 주문의 로컬 다국어 dense 검색: SQLite 벡터 캐시 + NumPy cosine.

주문 본문은 외부 임베딩 API에 전송하지 않는다. 모델 파일은 처음 내려받을 수 있다.
문서/모델 지문으로 변경 내용을 재색인하고 삭제된 벡터는 다음 검색에서 제거한다.
유사도는 관련성 순위 점수이며 정답 확률이 아니다. 모델 오류 시 서비스는 대체 조회를
표시한다. 검색 P/R·무정답 오검색의 실측 범위는 doc/EVALUATION.md를 참고한다.
"""

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np
from langsmith import traceable
from .models import ELEMENTS, SCHOOLS, language_name
from .safety import rule_category, spell_content, strings

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def document(spell):
    return "\n".join(
        [
            spell["name"],
            spell["incantation"],
            spell["effect"],
            spell.get("literal_meaning", ""),
            spell.get("limitations", ""),
            spell.get("notes", ""),
            spell["world"],
            language_name(spell["language"]),
            " ".join(ELEMENTS[e] for e in spell["elements"]),
            SCHOOLS[spell["school"]],
            " ".join(spell.get("tags", [])),
        ]
    )


class SpellVectorIndex:
    def __init__(self, path, model_name=None, embedder=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.model_name = model_name or os.getenv(
            "SPELL_EMBEDDING_MODEL", DEFAULT_MODEL
        )
        self.embedder = embedder
        self.lock = threading.RLock()
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS spell_vectors (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, vector TEXT NOT NULL)"
            )

    def forget(self, spell_id):
        # Small cache-only mutation; never load a model or delay a saved user edit
        # behind a long embedding operation. A locked cache is synced on next rank.
        try:
            with sqlite3.connect(self.path, timeout=0.2) as db:
                db.execute("DELETE FROM spell_vectors WHERE id=?", (spell_id,))
        except sqlite3.OperationalError:
            pass

    def embed(self, texts):
        if self.embedder is None:
            from fastembed import TextEmbedding

            self.embedder = TextEmbedding(model_name=self.model_name, threads=2)
        matrix = np.asarray(list(self.embedder.embed(texts)), dtype=np.float32)
        if (
            matrix.ndim != 2
            or len(matrix) != len(texts)
            or not np.isfinite(matrix).all()
        ):
            raise ValueError("Invalid embedding output")
        return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)

    @traceable(run_type="retriever", name="spells.vector_search")
    def rank(self, query, all_rows, eligible_ids, limit=12, min_score=0.25):
        with self.lock, sqlite3.connect(self.path) as db:
            present = {row["id"]: row for row in all_rows}
            cached = {
                row[0]: (row[1], json.loads(row[2]))
                for row in db.execute("SELECT id,fingerprint,vector FROM spell_vectors")
            }
            for removed in cached.keys() - present.keys():
                db.execute("DELETE FROM spell_vectors WHERE id=?", (removed,))
            fingerprints = {
                key: hashlib.sha256(
                    (self.model_name + "\n" + document(row)).encode()
                ).hexdigest()
                for key, row in present.items()
            }
            changed = [
                key
                for key in present
                if key not in cached or cached[key][0] != fingerprints[key]
            ]
            if changed:
                vectors = self.embed([document(present[key]) for key in changed])
                for key, vector in zip(changed, vectors):
                    cached[key] = (fingerprints[key], vector.tolist())
                    db.execute(
                        "INSERT OR REPLACE INTO spell_vectors VALUES (?,?,?)",
                        (key, fingerprints[key], json.dumps(vector.tolist())),
                    )
            candidates = [key for key in present if key in eligible_ids]
            if not candidates:
                return []
            matrix = np.asarray(
                [cached[key][1] for key in candidates], dtype=np.float32
            )
            scores = matrix @ self.embed([query])[0]
            ranked = np.argsort(-scores)
            return [
                {
                    **present[candidates[i]],
                    "_retrieval_score": round(float(scores[i]), 4),
                }
                for i in ranked
                if scores[i] >= min_score
            ][:limit]


class SpellRetrieval:
    def __init__(self, store, enabled=True, index=None):
        self.store = store
        self.enabled = enabled
        self.index = index or SpellVectorIndex(str(store.path) + ".vectors.sqlite")
        self.running = None
        self.retry_at = 0

    async def search(self, query, eligible, limit=12):
        # Existing legacy records containing known blocked terms are not RAG context.
        safe = lambda row: (
            not any(rule_category(t) for t in strings(spell_content(row)))
        )
        eligible = [r for r in eligible if safe(r)]
        all_rows = [r for r in self.store.all() if safe(r)]
        result = {"mode": "vector", "model": self.index.model_name, "reason": None}
        if not eligible:
            return [], {**result, "mode": "empty"}
        if not self.enabled:
            return eligible[:limit], {
                **result,
                "mode": "metadata_fallback",
                "reason": "벡터 검색 비활성화",
            }
        if self.running is not None and not self.running.done():
            return eligible[:limit], {
                **result,
                "mode": "metadata_fallback",
                "reason": "임베딩 모델 준비 또는 검색 진행 중",
            }
        if time.monotonic() < self.retry_at:
            return eligible[:limit], {
                **result,
                "mode": "metadata_fallback",
                "reason": "임베딩 오류 후 재시도 대기",
            }
        try:
            self.running = asyncio.create_task(
                asyncio.to_thread(
                    self.index.rank,
                    query,
                    all_rows,
                    {r["id"] for r in eligible},
                    limit,
                    float(os.getenv("SPELL_RAG_MIN_SCORE", "0.25")),
                )
            )
            # Retrieve exceptions even if the request timed out while loading a model.
            self.running.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
            rows = await asyncio.wait_for(
                asyncio.shield(self.running),
                float(os.getenv("SPELL_RETRIEVAL_TIMEOUT_SECONDS", "25")),
            )
            return rows, result
        except Exception:
            self.retry_at = time.monotonic() + 60
            return eligible[:limit], {
                **result,
                "mode": "metadata_fallback",
                "reason": "벡터 검색 준비 지연 또는 실패 · 기본 조회로 대체",
            }
