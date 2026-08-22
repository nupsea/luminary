"""Regenerating a deck must not return the questions it just deleted.

The shipped symptom: "Regenerate (replace)" produced the same five questions.
Nothing was cached -- the cause was that every input was identical. Window
sampling is deterministic (measured: the same six window starts on three
consecutive runs), the deck is deleted before the new run begins, and the
`avoid` list only ever held questions accepted *within* the current run. So the
model saw the same passages with nothing to steer away from.
"""

import pytest

from app.services.flashcard_generators import _collect_with_backfill


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_the_previous_deck_is_passed_to_the_first_batch() -> None:
    """Not just to the retries. The first pass is the one that repeated."""
    seen_avoid: list[list[str]] = []

    async def _batch(want: int, avoid: list[str]) -> list[dict]:
        seen_avoid.append(list(avoid))
        return [{"question": f"fresh {i}", "answer": "a"} for i in range(want)]

    await _collect_with_backfill(3, _batch, exclude=["old one", "old two"])

    assert seen_avoid[0] == ["old one", "old two"], (
        "the first batch saw an empty avoid list, which is the bug"
    )


@pytest.mark.anyio
async def test_retries_carry_the_previous_deck_and_this_run_s_questions() -> None:
    calls: list[list[str]] = []

    async def _batch(want: int, avoid: list[str]) -> list[dict]:
        calls.append(list(avoid))
        # One usable card per pass, so a retry is required to reach the count.
        return [{"question": f"q{len(calls)}", "answer": "a"}]

    await _collect_with_backfill(3, _batch, exclude=["previous"])

    assert calls[0] == ["previous"]
    assert calls[1] == ["previous", "q1"], "a retry must know both"


@pytest.mark.anyio
async def test_exclude_steers_but_never_filters() -> None:
    """A short document whose every good question was already asked must still
    produce a deck. Filtering on the excluded list would return nothing, and
    delivering nothing is worse than delivering something familiar."""

    async def _batch(want: int, avoid: list[str]) -> list[dict]:
        return [{"question": "the only sensible question", "answer": "a"}]

    cards = await _collect_with_backfill(2, _batch, exclude=["the only sensible question"])

    assert len(cards) == 1
    assert cards[0]["question"] == "the only sensible question"


@pytest.mark.anyio
async def test_no_exclusions_behaves_as_before() -> None:
    calls: list[list[str]] = []

    async def _batch(want: int, avoid: list[str]) -> list[dict]:
        calls.append(list(avoid))
        return [{"question": f"q{len(calls)}", "answer": "a"} for _ in range(want)]

    await _collect_with_backfill(2, _batch)

    assert calls[0] == []
