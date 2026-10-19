"""A looping model answer is stopped, trimmed to its first copy, and flagged on done."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.repetition import repetition_cut

# The 128-word cycle qwen3.5:4b streamed for six minutes in answer to a story request.
_OBSERVED_CYCLE = (
    "becoming creation evolution transformation regeneration renewal restoration recovery "
    "healing growth development progress improvement advancement breakthrough innovation "
    "discovery revelation enlightenment awakening liberation freedom independence autonomy "
    "self-reliance responsibility accountability obligation duty task job work effort labor "
    "exertion activity exercise engagement participation involvement contribution assistance "
    "support help aid service utility value worth merit excellence superiority "
    "outstandingness perfection completeness wholeness integrity honesty authenticity "
    "genuineness sincerity truthfulness transparency openness vulnerability exposure risk "
    "danger threat hazard challenge obstacle barrier blockage hindrance struggle difficulty "
    "problem issue matter affair concern topic subject theme focus center heart core essence "
    "spirit soul mind body structure organization system function operation mechanism process "
    "method technique strategy plan scheme approach angle perspective viewpoint outlook vision "
    "goal objective target aim purpose mission destiny fate karma dharma samsara maya illusion "
    "reality existence being"
)
_STORY = "Once upon a time in Adventure Bay the moon glowed a strange colour. " * 3


def test_observed_loop_is_cut_after_its_first_copy():
    text = _STORY + " ".join([_OBSERVED_CYCLE] * 5)
    cut = repetition_cut(text)
    assert cut is not None
    kept = text[:cut].rstrip()
    assert kept.startswith(_STORY.strip())
    assert len(kept.split()) == len(_STORY.split()) + len(_OBSERVED_CYCLE.split())


def test_refrain_sung_three_times_is_not_a_loop():
    refrain = " ".join(f"row{i}" for i in range(50))  # 3 x 50 = 150 words, under the floor
    assert repetition_cut(_STORY + " ".join([refrain] * 3)) is None


def test_single_word_stutter_fires_at_the_floor():
    assert repetition_cut(_STORY + " no" * 199) is None
    assert repetition_cut(_STORY + " no" * 200) is not None


def test_ordinary_prose_is_not_a_loop():
    prose = " ".join(f"Sentence {i} says something new about chapter {i % 7}." for i in range(300))
    assert repetition_cut(prose) is None


@pytest.mark.asyncio
async def test_stream_stops_a_looping_answer_and_flags_it():
    from app.runtime.qa_stream import get_qa_service  # noqa: PLC0415

    words = (_STORY + " ".join([_OBSERVED_CYCLE] * 40)).split()
    yielded = 0

    async def _looping(*_args, **_kwargs):
        nonlocal yielded
        for word in words:
            yielded += 1
            yield word + " "

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=_looping)
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(
        return_value={
            "answer": "",
            "confidence": "medium",
            "citations": [],
            "chunks": [],
            "section_context": "",
            "intent": "factual",
            "_llm_prompt": "Tell me a story.",
            "_system_prompt": "You are a helpful assistant.",
        }
    )

    qa = get_qa_service()
    with (
        patch("app.runtime.qa_stream.get_llm_service", return_value=mock_llm),
        patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph),
        patch.object(qa, "_store_qa", AsyncMock(return_value="qa-1")) as store,
    ):
        events = [e async for e in qa.stream_answer("Tell me a story.", [], "all", None)]

    done = json.loads(events[-1][len("data: ") :])
    assert done["stopped"] == "repetition"
    assert done["answer"].split() == _STORY.split() + _OBSERVED_CYCLE.split()
    assert store.call_args.args[1] == done["answer"]
    assert yielded < len(words) / 10, "the stream kept generating after the loop was found"
