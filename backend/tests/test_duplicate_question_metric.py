"""A question the model produced twice must be counted, not just dropped.

`_collect_with_backfill` tells each retry which questions were already accepted
and skips any that come back anyway. It skipped them silently, so `cards_generated`
absorbed the repeat -- llama3.2 lost 1 card and gemma3 lost 2 in the 2026-08-16
matrix run with nothing reporting it.

This exists because the metric read 0.0000 on both arms of the run it was added
for, and a rate pinned at 0.0000 is a bug hypothesis until it has been made to
move on purpose.
"""

import pytest

from app.services import llm_output_stats
from app.services.flashcard_generators import _collect_with_backfill


def _count() -> int:
    return llm_output_stats.snapshot()["counts"].get("duplicate_questions", 0)


@pytest.mark.asyncio
async def test_a_repeated_question_is_counted():
    before = _count()

    async def always_the_same(want: int, avoid: list[str]) -> list[dict]:
        # The retry prompt carries `avoid`; a model that returns the same question
        # anyway is ignoring its own context, which is the thing being measured.
        return [{"question": "What is a B-tree?", "answer": "An index structure."}]

    delivered = await _collect_with_backfill(3, always_the_same)

    assert len(delivered) == 1, "the repeat must not reach the deck"
    assert _count() > before, (
        "the repeat was dropped without being counted -- which is exactly how "
        "cards_generated absorbed it before"
    )


@pytest.mark.asyncio
async def test_distinct_questions_are_not_counted_as_repeats():
    """The other direction: a model that does its job must not be penalised."""
    before = _count()
    pool = iter([
        [{"question": "What is a B-tree?", "answer": "An index structure."}],
        [{"question": "What is a hash index?", "answer": "A lookup structure."}],
    ])

    async def distinct(want: int, avoid: list[str]) -> list[dict]:
        return next(pool, [])

    delivered = await _collect_with_backfill(2, distinct)

    assert len(delivered) == 2
    assert _count() == before
