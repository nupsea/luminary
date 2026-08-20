"""Schemas for the Progress surface.

Every number the Progress page renders arrives as a `Metric`: the value, the sample
it was computed from, and the sentence that defines it. A metric that could not be
computed carries `value=None` and says why in `basis`; the UI renders an em dash.

Nothing here may default an uncomputable number to zero. That is the surface
analogue of I-32, and it is the defect this router exists to close: the page used
to average `accuracy_pct` over recent sessions and call it "mastery", so a single
10-card session at 90% rendered as 90% mastery of the whole library.
"""

from pydantic import BaseModel


class Metric(BaseModel):
    """One number, with everything needed to defend it.

    `value` is None when the metric could not be computed -- no data, or a sample
    too small to mean anything. `basis` then says which, in the same words the UI
    shows the user.
    """

    value: float | None
    unit: str  # percent | count | days | minutes
    sample_size: int
    definition: str
    basis: str


class ProgressSummaryResponse(BaseModel):
    """Every headline number on the Progress page, computed server-side.

    Named fields rather than a list so the contract is checkable and the frontend
    cannot silently render a metric that was removed.
    """

    retention_30d: Metric
    mastery: Metric
    mature_cards: Metric
    due_today: Metric
    current_streak: Metric
    longest_streak: Metric
    reviews_30d: Metric
    gaps_closed: Metric
    # Named for what is measured, not for what a reader would like it to mean.
    time_on_luminary: Metric
    active_days: Metric
    documents: Metric
    notes: Metric


class NotesTimelinePoint(BaseModel):
    month: str  # YYYY-MM, the user's local month
    count: int


class NotesTimelineResponse(BaseModel):
    """Notes created per month, grouped in SQL.

    The page used to build this by downloading every note -- bodies included --
    and bucketing them in the browser.
    """

    points: list[NotesTimelinePoint]
    total_notes: int
