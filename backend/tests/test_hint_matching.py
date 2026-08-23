"""How a hint is matched, and what a miss actually means.

Hit rate is a substring test on an 80-character normalised prefix. Two things
about that are load-bearing and neither is visible in the number itself: the
normalisation must be the same one the offline integrity check uses, and a miss
can be a chunk boundary rather than a passage retrieval never found.
"""

# ruff: noqa: E402, I001

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.lib.retrieval_metrics import _norm, arm_metrics, compute_hit_rate_5, count_boundary_misses


def _sample(hint: str, *chunks: str) -> dict:
    return {"context_hint": hint, "contexts": list(chunks)}


def test_entities_and_nbsp_normalise_the_same_on_both_sides():
    """A scraped chunk carries `&amp;` and \\xa0 where the golden carries the
    characters. Before this, such a hint passed the offline integrity check and
    could never match at runtime."""
    assert _norm("Bell &amp; Howell") == _norm("Bell & Howell")
    assert _norm("one\xa0two") == _norm("one two")
    assert _norm("“quoted”") == _norm('"quoted"')


def test_a_hint_inside_one_chunk_is_a_hit():
    hint = "the machine was a thing of brass and ivory and quartz that shimmered oddly"
    assert compute_hit_rate_5([_sample(hint, f"prelude {hint} coda")]) == 1.0


def test_a_hint_split_across_two_chunks_is_not_a_hit():
    """Both halves came back at ranks 1 and 2 and the question still scores 0 --
    the property that makes HR@5 move when chunk size changes."""
    hint = "the machine was a thing of brass and ivory and quartz that shimmered oddly"
    left, right = hint[:40], hint[40:]
    samples = [_sample(hint, f"prelude {left}", f"{right} coda")]
    assert compute_hit_rate_5(samples) == 0.0
    assert count_boundary_misses(samples) == 1


def test_a_genuinely_absent_hint_is_not_a_boundary_miss():
    """Not retrieved is a retrieval failure and must not be excused as chunking."""
    samples = [_sample("a passage that was never retrieved at all", "something else entirely")]
    assert compute_hit_rate_5(samples) == 0.0
    assert count_boundary_misses(samples) == 0


def test_a_hit_is_never_counted_as_a_boundary_miss():
    hint = "the machine was a thing of brass and ivory and quartz that shimmered oddly"
    assert count_boundary_misses([_sample(hint, hint)]) == 0


def test_an_ablation_arm_reports_boundary_misses_alongside_its_hit_rate():
    """The ablation is the arm a retrieval change is chosen on, and it reported
    HR@5, MRR and nDCG only. A hint the chunker split scores a miss on every
    strategy and every depth, so without this it reads as a ranking failure the
    funnel could fix -- and the whole point of an arm is attribution."""
    hint = "the machine was a thing of brass and ivory and quartz that shimmered oddly"
    left, right = hint[:40], hint[40:]
    split = [_sample(hint, f"prelude {left}", f"{right} coda")]

    metrics = arm_metrics(split)

    assert set(metrics) == {"hit_rate_5", "mrr", "ndcg_10", "boundary_misses"}
    assert metrics["hit_rate_5"] == 0.0
    assert metrics["boundary_misses"] == 1, "a split hint is a chunking miss, not a ranking one"


def test_an_arm_that_genuinely_missed_reports_no_boundary_miss():
    """Otherwise the column would excuse every miss and could never fail."""
    metrics = arm_metrics([_sample("a passage that was never retrieved at all", "unrelated")])
    assert metrics["hit_rate_5"] == 0.0
    assert metrics["boundary_misses"] == 0
