"""The ingestion fidelity leg: what it measures and what must fail it.

Retrieval scores what was indexed and cannot report what never arrived, so a
document mangled at parse time leaves every downstream metric looking healthy.
This eval is the ceiling those metrics sit under.
"""

# ruff: noqa: E402, I001

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))
sys.path.insert(0, str(REPO_ROOT))

from evals.run_ingest_eval import THRESHOLDS, measure

_SOURCE = (
    "The Time Traveller produced the machine and set the levers. "
    "Filby doubted every word of it. "
    "The company dined and argued until the candles burned low."
)


def test_full_retention_when_every_sentence_is_chunked():
    retention, dup = measure(_SOURCE, [_SOURCE])
    assert retention == 1.0
    assert dup == pytest.approx(1.0)


def test_overlapping_chunks_do_not_read_as_duplication_loss():
    """Chunking overlaps on purpose, so duplication above 1.0 is expected and must
    not be mistaken for furniture repeated into the index."""
    halves = [
        "The Time Traveller produced the machine and set the levers. "
        "Filby doubted every word of it.",
        "Filby doubted every word of it. "
        "The company dined and argued until the candles burned low.",
    ]
    retention, dup = measure(_SOURCE, halves)
    assert retention == 1.0
    assert 1.0 < dup < THRESHOLDS["max_duplication"]


def test_dropped_half_of_a_document_is_visible_as_lost_retention():
    """The defect this leg exists to catch: text that never became a chunk is
    unreachable by any query, and no retrieval metric can report it."""
    retention, _ = measure(
        _SOURCE, ["The Time Traveller produced the machine and set the levers."]
    )
    assert retention < 0.6


def test_repeated_furniture_inflates_duplication():
    """Scraped site chrome indexed once per page is how `paper` came to carry 17
    questions about navigation blocks."""
    furniture = ["Skip to main content. Navigation. Copyright notice."] * 40
    _, dup = measure(_SOURCE, [_SOURCE, *furniture])
    assert dup > THRESHOLDS["max_duplication"]


def test_empty_source_scores_zero_rather_than_dividing_by_nothing():
    assert measure("", ["anything"]) == (0.0, 0.0)


def test_thresholds_sit_below_every_measured_document():
    """Floors are collapse detectors. Measured 2026-08-14 over the 12 manifest
    documents: retention 95.7%-100%, duplication 0.96-1.14."""
    assert THRESHOLDS["min_retention"] < 0.957
    assert THRESHOLDS["max_duplication"] > 1.14
