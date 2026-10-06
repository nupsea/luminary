"""scripts/mem_profile.py's timeline: the stage, card and queue times a release report quotes."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "mem_profile", Path(__file__).resolve().parents[2] / "scripts" / "mem_profile.py"
)
mem_profile = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mem_profile)

MB = 1024 * 1024


def _s(t, stage, *, gpu=None, active=False, with_cards=0, cards=0, avail=8000):
    return {
        "t": t,
        "stage": stage,
        "gpu_pct": gpu,
        "queue": {"active": active},
        "chapters": 5,
        "chapters_with_cards": with_cards,
        "cards": cards,
        "available": avail * MB,
    }


def test_each_time_is_the_first_sample_that_shows_it():
    samples = [
        _s(0, "parsing", gpu=10),
        _s(2, "embedding", gpu=40),
        _s(4, "complete", gpu=95, active=True),
        _s(6, "complete", gpu=97, active=True, with_cards=1, cards=12, avail=3000),
        _s(8, "complete", gpu=98, active=True, with_cards=2, cards=25),
        _s(10, "complete", gpu=5, with_cards=2, cards=25),
    ]
    got = mem_profile._timeline(samples)
    assert got["stage_first_seen_s"] == {"parsing": 0, "embedding": 2, "complete": 4}
    assert (got["first_chapter_cards_s"], got["second_chapter_cards_s"]) == (6, 8)
    assert got["queue_drained_s"] == 10
    assert got["cards_final"] == 25
    assert got["gpu_saturated_share"] == 0.5
    assert got["min_available_mb"] == 3000


def test_a_queue_idle_before_complete_is_not_drained():
    """The queue is empty while parsing; only a quiet queue after `complete` means done."""
    samples = [_s(0, "parsing"), _s(2, "complete", active=True)]
    got = mem_profile._timeline(samples)
    assert got["queue_drained_s"] is None
    assert got["first_chapter_cards_s"] is None


def test_no_gpu_reading_is_none_not_zero():
    """A host the reader cannot see must not report an idle GPU."""
    got = mem_profile._timeline([_s(0, "complete")])
    assert got["gpu_mean_pct"] is None
    assert got["gpu_saturated_share"] is None
