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

# "missing" is not a failure: the component simply has not been installed yet,
# and there is an action for it. Reporting that as failed put a warning icon and
# a raw exception in front of a user whose install was working correctly.
State = Literal[
    "pending", "downloading", "loading", "ready", "failed", "skipped", "missing"
]

# `required` decides what the user waits for. Everything else finishes in the
# background while they use the app: the entity model alone is 1.1GB, and
# holding a setup screen open for it means minutes of staring at a progress bar
# before a library that would already have worked.
#
# Labels are what a person reads on the setup screen, so they name the outcome
# rather than the artifact.
_PHASES: tuple[tuple[str, str, bool], ...] = (
    ("db", "Preparing your library", True),
    ("embedder", "Learning to read your documents", True),
    ("ollama_server", "Starting the local engine", False),
    ("chat_model", "Chat and flashcard model", False),
    # Not a default (6GB). Listed so "not installed" is said once with an
    # install action, not discovered later as a failed enrichment.
    ("vision_model", "Figure and diagram reading", False),
    ("ner", "Concept extraction", False),
    ("reranker", "Answer ranking", False),
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
        self._offline = False

    def set_offline(self, offline: bool) -> None:
        """Record that the hub was unreachable.

        An explicit flag, because inferring it from message text matched
        "APIConnectionError" and told users with working internet that they had
        none.
        """
        with self._lock:
            self._offline = offline

    def has_phase(self, key: str) -> bool:
        return key in self._phases

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
            failed = [p.key for p in self._phases.values() if p.state == "failed"]
            missing = [p.key for p in self._phases.values() if p.state == "missing"]
            # Nothing left in flight, even if optional pieces are uninstalled.
            settled = all(
                p.state in (*_SATISFIED, "missing") for p in self._phases.values()
            )
            busy = any(p.state in ("downloading", "loading") for p in self._phases.values())
            db_ready = self._phases["db"].state in _SATISFIED
            offline = self._offline
            elapsed = time.time() - self._started_at

        if settled and not failed:
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
            # Whether the user should be held on the setup screen at all. Only
            # required phases count, so optional downloads never block the app.
            "blocking": not required_ready,
            "failed": failed,
            # Installable, not broken. The UI offers an action rather than an error.
            "missing": missing,
            "offline": offline,
            "elapsed_seconds": round(elapsed, 1),
            "phases": phases,
        }


_status = StartupStatus()


def get_startup_status() -> StartupStatus:
    return _status
