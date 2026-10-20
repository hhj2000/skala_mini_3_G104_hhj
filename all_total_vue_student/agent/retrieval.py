"""Local multilingual dense retrieval. SQLite persists vectors and document metadata.

No keyword incident classifier is used. A single runbook is one chunk because the
six documents are short. Content/model fingerprints invalidate cached embeddings.
"""

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

import numpy as np
from langsmith import traceable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class RunbookIndex:
    def __init__(self, directory=None, db_path=None, model_name=None, embedder=None):
        self.directory = Path(directory or ROOT / "data/runbooks")
        self.db_path = Path(
            db_path or os.getenv("RAG_INDEX_PATH", str(ROOT / ".cache/runbooks.sqlite"))
        )
        self.model_name = model_name or os.getenv("RAG_EMBEDDING_MODEL", DEFAULT_MODEL)
        self.embedder = embedder
        self.lock = threading.RLock()
        self.docs = []
        self.vectors = None

    def _embed(self, texts):
        if self.embedder is None:
            from fastembed import TextEmbedding

            self.embedder = TextEmbedding(model_name=self.model_name, threads=2)
        matrix = np.asarray(list(self.embedder.embed(texts)), dtype=np.float32)
        return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)

    def build(self):
        with self.lock:
            metadata = json.loads((self.directory / "index.json").read_text())
            docs = [
                {
                    "incident_type": p.stem,
                    "uri": f"runbook://incident-response/{p.stem}",
                    "title": p.read_text().splitlines()[0].lstrip("# "),
                    "content": p.read_text(),
                    "search_text": metadata.get(p.stem, "") + "\n" + p.read_text(),
                }
                for p in sorted(self.directory.glob("*.md"))
            ]
            if not docs:
                raise ValueError("Runbook corpus is empty")
            fingerprint = hashlib.sha256(
                (self.model_name + json.dumps(docs, ensure_ascii=False)).encode()
            ).hexdigest()
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS corpus (fingerprint TEXT PRIMARY KEY, docs TEXT, vectors TEXT)"
                )
                row = conn.execute(
                    "SELECT docs, vectors FROM corpus WHERE fingerprint=?",
                    (fingerprint,),
                ).fetchone()
                if row:
                    self.docs, values = json.loads(row[0]), json.loads(row[1])
                    self.vectors = np.asarray(values, dtype=np.float32)
                else:
                    vectors = self._embed([d["search_text"] for d in docs])
                    conn.execute("DELETE FROM corpus")
                    conn.execute(
                        "INSERT INTO corpus VALUES (?,?,?)",
                        (
                            fingerprint,
                            json.dumps(docs, ensure_ascii=False),
                            json.dumps(vectors.tolist()),
                        ),
                    )
                    self.docs, self.vectors = docs, vectors
            return {
                "documents": len(self.docs),
                "model": self.model_name,
                "fingerprint": fingerprint,
            }

    @traceable(run_type="retriever", name="runbook.vector_search")
    def search(self, query, top_k=2, min_score=None):
        with self.lock:
            if self.vectors is None:
                self.build()
            threshold = (
                float(os.getenv("RAG_MIN_SCORE", "0.30"))
                if min_score is None
                else min_score
            )
            scores = self.vectors @ self._embed([query])[0]
            ranked = np.argsort(-scores)[: max(1, min(int(top_k), len(self.docs)))]
            # A relative margin avoids treating a much weaker second hit as evidence.
            best = float(scores[ranked[0]])
            return [
                {
                    **{k: v for k, v in self.docs[i].items() if k != "search_text"},
                    "score": round(float(scores[i]), 4),
                    "embedding_model": self.model_name,
                }
                for i in ranked
                if scores[i] >= threshold and scores[i] >= best - 0.08
            ]
