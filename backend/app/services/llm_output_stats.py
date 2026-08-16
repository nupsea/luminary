"""Counters for what a model's output needed before it could be used.

Nothing in this codebase distinguished a model that emits clean JSON from one
whose output is repaired into shape. Two tolerant parsers, a key-alias lookup
and a retry-to-backfill loop mean fenced, mis-keyed or truncated output produces
byte-identical downstream objects -- so a weaker model costs latency and call
count, and every quality metric reads the same. That is why swapping models has
never moved a number.

Process-wide and monotonic. An eval snapshots before and after a run and takes
the difference: no reset endpoint, because a reset is a mutation two concurrent
readers can lose.

Cheap by construction -- integer increments under a lock, on paths that have
just finished waiting on a model.
"""

from __future__ import annotations

import threading
from typing import Any

# Repair kinds. `key_alias` is recorded by the reader that accepts alternate key
# names, not by the parser: the JSON was valid, the shape was not.
FENCED = "fenced"
BAD_ESCAPE = "bad_escape"
TRUNCATED = "truncated"
KEY_ALIAS = "key_alias"
# Not a repair -- the JSON was clean, the top-level shape was not the one the
# prompt asked for (a bare array where an object was specified, or the reverse).
# Counted separately so it cannot be confused with output that needed rewriting.
SHAPE_DEVIATION = "shape_deviation"

_lock = threading.Lock()
_counts: dict[str, int] = {}


def _bump(key: str, amount: int = 1) -> None:
    if amount <= 0:
        return
    with _lock:
        _counts[key] = _counts.get(key, 0) + amount


def record_parse(*, ok: bool, repairs: frozenset[str]) -> None:
    """One attempt to read structured output from a completion.

    `first_pass` means strict JSON parsed with nothing repaired -- the number
    that separates a model that follows the format from one that is carried.
    """
    _bump("parses")
    if not ok:
        _bump("parse_failures")
        return
    if repairs:
        _bump("parses_repaired")
        for kind in repairs:
            _bump(f"repair_{kind}")
    else:
        _bump("parses_first_pass")


def record_shape_deviation() -> None:
    """The completion parsed cleanly but in the other top-level shape."""
    _bump("shape_deviations")


def record_card_gate(kind: str | None) -> None:
    """One generated card through the deterministic quality gate.

    `cards_gated` counts every card the model produced; `card_reject_<kind>`
    counts the ones the gate dropped. Together they give a reject rate that
    needs no judge and moves with the model -- the gate checks exactly what the
    prompt forbids (deictic questions, one-word answers, empty fields), so a
    model that ignores those instructions scores worse without anyone grading
    style.
    """
    _bump("cards_gated")
    if kind:
        _bump(f"card_reject_{kind}")
        _bump("cards_rejected")


def record_key_alias() -> None:
    """A field read under an alternate name the prompt did not ask for."""
    _bump("repair_key_alias")


def record_generation(*, requested: int, delivered: int, attempts: int) -> None:
    """One generation that had to produce N items.

    Retries are how quality becomes latency here: a weaker model is rejected
    more often and retried, so the delivered count matches and only the call
    count moves.
    """
    _bump("generations")
    _bump("items_requested", requested)
    _bump("items_delivered", delivered)
    _bump("generation_attempts", max(attempts, 0))
    if attempts > 1:
        _bump("generations_retried")
    if delivered < requested:
        _bump("generations_short")


def record_items_deduped(count: int) -> None:
    """Items a model produced that a later filter removed.

    Counted apart from generation because it is not a fact about the model: the
    near-duplicate filter compares against what the document already holds, so
    the same passage generated twice yields fewer cards the second time and
    eventually none. Without this, that library-state effect arrives inside a
    delivery rate and reads as a weaker model.
    """
    _bump("items_deduped", count)


def snapshot() -> dict[str, Any]:
    """Every counter, plus the two rates that are read most often.

    Rates are None rather than 0.0 when nothing has been counted: a first-pass
    rate of 0.0 on zero parses reads as a model that never emits clean JSON.
    """
    with _lock:
        counts = dict(_counts)
    parses = counts.get("parses", 0)
    generations = counts.get("generations", 0)
    return {
        "counts": counts,
        "first_pass_rate": (counts.get("parses_first_pass", 0) / parses) if parses else None,
        "attempts_per_generation": (
            (counts.get("generation_attempts", 0) / generations) if generations else None
        ),
    }


def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What happened between two snapshots, in the same shape."""
    before_counts = before.get("counts", {})
    after_counts = after.get("counts", {})
    counts = {
        key: after_counts.get(key, 0) - before_counts.get(key, 0)
        for key in set(before_counts) | set(after_counts)
        if after_counts.get(key, 0) - before_counts.get(key, 0)
    }
    parses = counts.get("parses", 0)
    generations = counts.get("generations", 0)
    return {
        "counts": counts,
        "first_pass_rate": (counts.get("parses_first_pass", 0) / parses) if parses else None,
        "attempts_per_generation": (
            (counts.get("generation_attempts", 0) / generations) if generations else None
        ),
    }
