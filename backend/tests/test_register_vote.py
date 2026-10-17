"""The register is a majority of body windows, not one sample (#286)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.workflows.ingestion_nodes import _shared

STORY = "Roderick led me down the stair, and the lamp shook in his hand. " * 100
REFLECTION = "Terror is a property of the mind, and the mind explains its own fear. " * 100


def _book(middle: str) -> str:
    """Five equal parts, so the 30/50/70% windows land in parts 2, 3 and 4."""
    return STORY + STORY + middle + STORY + STORY


def _judge(prompt: str, **_kw) -> str:
    return "explain" if "Terror is a property" in prompt else "story"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "register"),
    [
        (_book(STORY), "narrative"),
        # The one reflective window at 50% cannot flip a story.
        (_book(REFLECTION), "narrative"),
        # The check firing: when most windows explain, the book is expository.
        (REFLECTION * 2 + STORY + REFLECTION * 2, "expository"),
    ],
    ids=["story", "story-with-one-reflection", "essay"],
)
async def test_one_window_cannot_decide_the_register(text: str, register: str) -> None:
    llm = AsyncMock()
    llm.generate.side_effect = _judge
    with patch("app.services.llm.get_llm_service", return_value=llm):
        assert await _shared.detect_register(text) == register
    assert all(c.kwargs["temperature"] == 0 for c in llm.generate.call_args_list)


@pytest.mark.asyncio
async def test_two_agreeing_windows_settle_it_without_a_third_call() -> None:
    llm = AsyncMock()
    llm.generate.return_value = "story"
    with patch("app.services.llm.get_llm_service", return_value=llm):
        assert await _shared.detect_register(_book(STORY)) == "narrative"
    assert llm.generate.await_count == 2


@pytest.mark.asyncio
async def test_no_majority_is_undecided() -> None:
    llm = AsyncMock()
    llm.generate.side_effect = ["story", "explain", "maybe"]
    with patch("app.services.llm.get_llm_service", return_value=llm):
        assert await _shared.detect_register(_book(REFLECTION)) is None
