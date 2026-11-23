"""Progress for a fetch whose size is learned as it goes (a page tree, a next-link chain)."""

from __future__ import annotations

from luminary_source_sdk.connector import Report


class Progress:
    """Reports a fraction that never goes back, however the estimate of what is left moves,
    and never reaches 1 before the fetch is done."""

    def __init__(self, report: Report, stage: str = "") -> None:
        self._report = report
        self._stage = stage
        self.fraction = 0.0

    def update(self, done: int, remaining: int, stage: str | None = None) -> float:
        total = done + remaining
        estimate = min(0.99, done / total) if total else 0.99
        self.fraction = max(self.fraction, estimate)
        self._report(self.fraction, self._stage if stage is None else stage)
        return self.fraction
