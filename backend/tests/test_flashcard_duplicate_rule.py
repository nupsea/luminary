"""One call, asking the same thing twice.

A reader replaced a document's deck and got three cards back, two of which asked
the same thing: "Why does rambling while prompting provide more value to an AI
than concise input?" beside "What advantage does providing continuous context
via ramble offer compared to a linear list of instructions?" -- one fact in two
dresses, written by one call. The question-similarity test saw them at 0.8014
and let them through, because its bar is 0.85. Across 221 real generation calls
in this library (549 cards) that bar has caught a within-call repeat zero times.

The ANSWER is the second axis, and the scope is the measured part of it: within
one call the joint rule costs 21 of those 549 cards (3.8%); applied to the whole
existing deck instead it refuses a median of 19.1% of every document's cards,
including plainly distinct ones. A deck accumulates similar-but-different cards
over months of runs. One call reading one passage does not.
"""

from __future__ import annotations

import math
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel, FlashcardModel
from app.services.flashcard import (
    FlashcardService,
    _is_near_duplicate,
    _repeats_this_call,
)


def _at(cosine: float) -> list[float]:
    """A unit vector whose cosine similarity with [1, 0] is exactly *cosine*."""
    return [cosine, math.sqrt(max(0.0, 1.0 - cosine * cosine))]


_BASE = np.array([[1.0, 0.0]])


def test_a_repeat_of_the_question_alone_is_a_duplicate():
    """Above 0.85 on the question, the answer is not consulted."""
    assert _repeats_this_call(np.array(_at(0.90)), np.array(_at(0.10)), _BASE, _BASE)


def test_the_same_fact_in_different_words_repeats_the_call():
    """The card that shipped: q=0.8014, a=0.7614, and it must not be written."""
    assert _repeats_this_call(np.array(_at(0.8014)), np.array(_at(0.7614)), _BASE, _BASE)


def test_a_neighbouring_question_from_the_same_passage_is_kept():
    """The other bracket, also real: "Why do massive-scale corpora require hard
    choices regarding storage costs?" against "Why are lexical search and dense
    retrieval considered complementary?" -- q=0.7890, a=0.7410, two facts from
    one passage. Both bars have to be cleared, so this survives."""
    assert not _repeats_this_call(np.array(_at(0.7890)), np.array(_at(0.7410)), _BASE, _BASE)


def test_a_similar_question_with_a_different_answer_is_kept():
    """Questions phrased alike carry the corpus's false positives -- 698 pairs
    clear 0.80 on the question while their answers sit below 0.70."""
    assert not _repeats_this_call(np.array(_at(0.84)), np.array(_at(0.65)), _BASE, _BASE)


def test_the_deck_is_still_compared_on_the_question_alone():
    """The second axis is scoped to one call and must not reach the deck: the
    same bars applied there refuse a median 19.1% of a document's cards,
    "Why is it necessary to define a label for the nodes in an abstract syntax
    tree?" against "How does the `_backward` method enable automatic
    differentiation" among them at 0.785/0.809."""
    assert not _is_near_duplicate(np.array(_at(0.8014)), _BASE)
    assert _is_near_duplicate(np.array(_at(0.86)), _BASE)


# The first generation on a document is the one with an empty pool


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


_PASSAGE = (
    "Therefore, the key idea behind replication is that copies of data are kept on "
    "multiple nodes. As a result, if one node fails, the system can still serve reads "
    "from the remaining replicas. The principle enables fault tolerance."
)

_TWO_WAYS_OF_ASKING = (
    '[{"question": "Why is data replication important in distributed systems?", '
    '"answer": "It enables fault tolerance by keeping copies on multiple nodes.", '
    '"source_excerpt": "copies of data are kept on multiple nodes"}, '
    '{"question": "What does keeping copies of data on several nodes buy you?", '
    '"answer": "Fault tolerance: reads still work when one node fails.", '
    '"source_excerpt": "the system can still serve reads from the remaining replicas"}]'
)


class _PairedEmbedder:
    """Every question 0.80 from its neighbour, every answer 0.76 -- the shipped pair."""

    def encode(self, texts):
        out = []
        for text in texts:
            first = "Why is data replication" in text or "It enables fault tolerance" in text
            if first:
                out.append([1.0, 0.0])
            elif "several nodes" in text:
                out.append(_at(0.8014))
            else:
                out.append(_at(0.7614))
        return out


@pytest.mark.asyncio
async def test_a_first_batch_is_checked_against_itself(test_db):
    """No existing deck is not a reason to skip the check.

    The candidate encode used to be gated on there being cards to compare
    against, so the run with an empty pool -- the first one on a document -- was
    the only run that could deliver the same question twice.
    """
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Distributed Systems Engineering",
                format="pdf",
                content_type="book",
                word_count=500,
                page_count=10,
                file_path="/tmp/ddia.pdf",
                stage="complete",
            )
        )
        for index, text in enumerate(["Introduction to distributed systems.", _PASSAGE]):
            session.add(
                ChunkModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    section_id=None,
                    text=text,
                    token_count=len(text.split()),
                    page_number=1,
                    chunk_index=index,
                )
            )
        await session.commit()

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_TWO_WAYS_OF_ASKING)

    import app.services.embedder as embedder_module

    with (
        patch("app.services.flashcard.get_llm_service", return_value=mock_llm),
        patch.object(embedder_module, "get_embedding_service", lambda: _PairedEmbedder()),
    ):
        async with factory() as session:
            cards = await FlashcardService().generate(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=2,
                session=session,
            )

    assert len(cards) == 1, (
        f"the second card asks the first one again: {[c.question for c in cards]}"
    )
    async with factory() as session:
        stored = (
            await session.execute(
                select(FlashcardModel).where(FlashcardModel.document_id == doc_id)
            )
        ).scalars().all()
    assert len(stored) == 1
