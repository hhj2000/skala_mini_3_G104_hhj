"""Durable SQLite lexicon. Atomic version checks prevent overwriting newer edits."""

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class StaleVersion(Exception):
    pass


class SpellStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS spells (id TEXT PRIMARY KEY, payload TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS revisions (spell_id TEXT, version INTEGER, payload TEXT, changed_at TEXT, PRIMARY KEY(spell_id,version))"
        )
        self.db.commit()

    @staticmethod
    def unpack(row):
        return {
            "language_kind": "natural",
            "hangul_pronunciation": "",
            "ipa": "",
            "pronunciation_note": "",
            "verification": None,
            **json.loads(row["payload"]),
            "id": row["id"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def all(self):
        with self.lock:
            return [
                self.unpack(row)
                for row in self.db.execute(
                    "SELECT * FROM spells ORDER BY updated_at DESC, id"
                )
            ]

    def get(self, spell_id):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM spells WHERE id=?", (spell_id,)
            ).fetchone()
            return self.unpack(row) if row else None

    def create(self, payload):
        now = datetime.now(UTC).isoformat()
        spell_id = str(uuid4())
        text = json.dumps(payload, ensure_ascii=False)
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO spells VALUES (?,?,?,?,?)", (spell_id, text, 1, now, now)
            )
            self.db.execute(
                "INSERT INTO revisions VALUES (?,?,?,?)", (spell_id, 1, text, now)
            )
        return self.get(spell_id)

    def update(self, spell_id, payload, version):
        now = datetime.now(UTC).isoformat()
        text = json.dumps(payload, ensure_ascii=False)
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT version FROM spells WHERE id=?", (spell_id,)
            ).fetchone()
            if row is None:
                return None
            if row["version"] != version:
                raise StaleVersion()
            self.db.execute(
                "UPDATE spells SET payload=?,version=?,updated_at=? WHERE id=?",
                (text, version + 1, now, spell_id),
            )
            self.db.execute(
                "INSERT INTO revisions VALUES (?,?,?,?)",
                (spell_id, version + 1, text, now),
            )
        return self.get(spell_id)

    def delete(self, spell_id, version=None):
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT version FROM spells WHERE id=?", (spell_id,)
            ).fetchone()
            if row is None:
                return False
            if version is not None and row["version"] != version:
                raise StaleVersion()
            self.db.execute("DELETE FROM revisions WHERE spell_id=?", (spell_id,))
            self.db.execute("DELETE FROM spells WHERE id=?", (spell_id,))
            return True

    def close(self):
        self.db.close()
