"""Persistent and per-session disposable spell workspaces."""

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import tempfile

from .generation import SpellGenerator
from .retrieval import SpellRetrieval
from .store import SpellStore

active_workspace = ContextVar("kharakteres_workspace", default=None)


@dataclass
class Workspace:
    store: SpellStore
    retrieval: SpellRetrieval
    generator: SpellGenerator
    temporary: tempfile.TemporaryDirectory | None = None

    def close(self):
        self.store.close()
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None


def create_workspace(path, backend, model, guard, retrieval_enabled, temporary=None):
    store = SpellStore(path)
    retrieval = SpellRetrieval(store, enabled=retrieval_enabled)
    generator = SpellGenerator(backend, model, store, guard=guard, retrieval=retrieval)
    return Workspace(store, retrieval, generator, temporary)


def create_secret_workspace(backend, model, guard, retrieval_enabled):
    temporary = tempfile.TemporaryDirectory(prefix="kharakteres-secret-")
    try:
        path = Path(temporary.name) / "spells.sqlite"
        return create_workspace(path, backend, model, guard, retrieval_enabled, temporary)
    except Exception:
        temporary.cleanup()
        raise


def create_user_workspace(root, user_id, backend, model, guard, retrieval_enabled):
    path = Path(root) / "users" / str(user_id) / "spells.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_workspace(path, backend, model, guard, retrieval_enabled)
