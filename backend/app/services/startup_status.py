"""Process-wide record of how far startup has actually got.

``/health`` answers 200 the moment the lifespan yields, which on a cold install
is many minutes before the app can do anything useful -- encoder weights and a
chat model may still be downloading. Launch scripts already work around this by
polling ``/documents`` instead of ``/health``. This registry is the honest
answer, and it is what the desktop setup screen renders.

Updated from executor threads during warmup, so every mutation takes the lock.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

State = Literal["pending", "downloading", "loading", "ready", "failed", "skipped"]

# A phase that is not `required` may fail without holding back overall
# readiness: cloud LLM routing works with no local model at all, and the user
# can turn reranking off.
_PHASES: tuple[tuple[str, str, bool], ...] = (
    ("db", "Library database", True),
    ("ollama_server", "Local model server", False),
    ("chat_model", "Chat model", False),
    ("embedder", "Embedding model", True),
    ("ner", "Entity model", False),
    ("reranker", "Reranking model", False),
)

_SATISFIED = ("ready", "skipped")


@dataclass
class Phase:
    key: str
    label: str
    required: bool
    state: State = "pending"
    detail: str = ""
    completed_bytes: int = 0
    total_bytes: int = 0
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        percent: float | None = None
        if self.state == "ready":
            percent = 100.0
        elif self.total_bytes > 0:
            percent = round(min(self.completed_bytes / self.total_bytes, 1.0) * 100, 1)
        return {
            "key": self.key,
            "label": self.label,
            "required": self.required,
            "state": self.state,
            "detail": self.detail,
            "completed_bytes": self.completed_bytes,
            "total_bytes": self.total_bytes,
            "percent": percent,
        }


class StartupStatus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._phases = {
            key: Phase(key=key, label=label, required=required)
            for key, label, required in _PHASES
        }
        self._started_at = time.time()

    def set_state(self, key: str, state: State, detail: str = "") -> None:
        with self._lock:
            phase = self._phases.get(key)
            if phase is None:
                return
            phase.state = state
            phase.detail = detail
            phase.updated_at = time.time()
            if state == "ready" and phase.total_bytes:
                phase.completed_bytes = phase.total_bytes

    def set_progress(self, key: str, completed: int, total: int, detail: str = "") -> None:
        with self._lock:
            phase = self._phases.get(key)
            if phase is None:
                return
            phase.state = "downloading"
            phase.completed_bytes = max(completed, 0)
            phase.total_bytes = max(total, 0)
            if detail:
                phase.detail = detail
            phase.updated_at = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            phases = [p.as_dict() for p in self._phases.values()]
            required_ready = all(
                p.state in _SATISFIED for p in self._phases.values() if p.required
            )
            all_ready = all(p.state in _SATISFIED for p in self._phases.values())
            failed = [p.key for p in self._phases.values() if p.state == "failed"]
            busy = any(p.state in ("downloading", "loading") for p in self._phases.values())
            db_ready = self._phases["db"].state in _SATISFIED
            elapsed = time.time() - self._started_at

        if all_ready and not failed:
            status = "ready"
        elif failed and required_ready:
            status = "degraded"
        elif busy:
            status = "provisioning"
        else:
            status = "starting"

        return {
            "status": status,
            # Everything the app needs is in place.
            "ready": required_ready and not failed,
            # The library opens and browsing works; model-backed features may not.
            "usable": db_ready,
            "failed": failed,
            "elapsed_seconds": round(elapsed, 1),
            "phases": phases,
        }


_status = StartupStatus()


def get_startup_status() -> StartupStatus:
    return _status
