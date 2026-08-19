"""Which datasets may be tuned on, and which are only ever measured.

`RERANK_MODEL` and `RERANK_BLEND_ALPHA` were chosen by a sweep over the goldens
that gate, on constraints naming specific datasets — best mean HR@5, "no dataset
more than one question below no-rerank" (which `time_machine` decided), and
lifting `hamlet` from .567 to .667. That is documented model selection, not a
hidden favour. The defect is narrower: with no held-out data, nothing
distinguishes a retrieval improvement from a fit to twelve documents.

**Today's holdout is provisional and this must not be forgotten.** The sweep ran
over all twelve manifest documents, so every dataset below was visible to it.
The split freezes from here: sweeps may read TUNE, and HOLDOUT is measured and
recorded but never used to choose a value. A genuinely clean holdout needs a
dataset built from a document no sweep has seen — the next one generated after
this file was written is the first that can claim it.
"""

from __future__ import annotations

# Sweeps, ablations and threshold searches read these.
TUNE: frozenset[str] = frozenset(
    {
        "book",
        "book_time_machine",
        "paper",
        "legal",
        "play",
        "study",
        "d2l",
    }
)

# Measured on every gated run, never used to select a value. A change that
# improves TUNE and not these is a fit, and that is the only thing this split
# can tell you.
HOLDOUT: frozenset[str] = frozenset(
    {
        "book_alice",
        "book_frankenstein",
        "odyssey",
        "notes",
        "conversation",
    }
)


def split_of(dataset: str) -> str:
    """`tune`, `holdout`, or `unassigned` for datasets that are neither."""
    if dataset in TUNE:
        return "tune"
    if dataset in HOLDOUT:
        return "holdout"
    return "unassigned"


def refuse_if_holdout(dataset: str, what: str) -> str | None:
    """The reason to refuse *what* on *dataset*, or None when it is allowed.

    Returned rather than raised so a caller can print it and exit with its own
    code; the point is that tuning against a holdout stops, not that it crashes.
    """
    if dataset in HOLDOUT:
        return (
            f"{dataset} is holdout: {what} selects a value, and a value selected "
            "on the holdout leaves nothing to detect a fit with. Run it on a "
            f"tune dataset ({', '.join(sorted(TUNE))}) and measure holdout after."
        )
    return None
