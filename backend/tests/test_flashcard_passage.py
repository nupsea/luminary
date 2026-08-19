"""A card records the passage it was written from, not the first chunk of its scope.

`chunk_id` holds the first chunk of the generation scope. Reading it as the card's
source showed a judge a passage without the card's own quote in it 56 times out of
60, and the resulting 0.3333 measured the reconstruction rather than the cards.

`source_chunk_ids` is the fix, and it carries three distinguishable states:
a recorded passage, NULL (never recorded, or a path with no chunks), and []
(supplied text, not reconstructible from the library). None of the three may be
read as either of the others.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, FlashcardModel
from app.services.flashcard import _CHUNK_CHAR_LIMIT, _build_text
from app.services.flashcard_grounding import passage_for_card


def _chunk(index: int, text: str) -> ChunkModel:
    return ChunkModel(
        id=f"chunk-{index}",
        document_id="doc-1",
        section_id=None,
        text=text,
        token_count=10,
        page_number=1,
        chunk_index=index,
    )


class TestBuildTextReportsWhatItUsed:
    def test_every_chunk_is_named_when_all_of_them_fit(self):
        chunks = [_chunk(i, f"passage {i}") for i in range(3)]
        _, first, used = _build_text(chunks)
        assert used == ["chunk-0", "chunk-1", "chunk-2"]
        assert first == "chunk-0"

    def test_only_the_sampled_chunks_are_named_when_the_text_is_truncated(self):
        """Over the limit this samples beginning/middle/end and drops the rest.

        Naming every chunk of the scope would claim the model saw text it never
        did, which is the same lie `chunk_id` was telling in a different shape.
        """
        big = "x" * 2000
        chunks = [_chunk(i, big) for i in range(_CHUNK_CHAR_LIMIT // 2000 + 20)]
        combined, _, used = _build_text(chunks)
        assert "[...]" in combined, "this case must actually trigger the sampling branch"
        assert 0 < len(used) < len(chunks)
        assert len(used) == len(set(used)), "a chunk must not be recorded twice"

    def test_no_chunks_records_nothing(self):
        assert _build_text([]) == ("", "", [])


@pytest.fixture()
async def factory(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'passage.db'}")
    await create_all_tables(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _card(**kw) -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id="doc-1",
        question="q",
        answer="a",
        source_excerpt="",
        difficulty="medium",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        reps=0,
        lapses=0,
        **kw,
    )


@pytest.mark.asyncio
async def test_the_passage_is_rebuilt_in_reading_order(factory):
    """A quote spanning a seam is real; rebuilding out of order calls it invented."""
    async with factory() as session:
        session.add(_chunk(0, "the first half of a sentence"))
        session.add(_chunk(1, "and the second half"))
        card = _card(chunk_id="chunk-0", source_chunk_ids=["chunk-0", "chunk-1"])
        session.add(card)
        await session.commit()

        passage = await passage_for_card(card, session)
    assert passage.index("first half") < passage.index("second half")


@pytest.mark.asyncio
async def test_a_card_with_a_recorded_passage_is_not_checked_against_the_whole_book(factory):
    """The card saw chunk-0. A quote from chunk-9 cannot have come from it."""
    async with factory() as session:
        session.add(_chunk(0, "the passage the model was shown"))
        session.add(_chunk(9, "a page four hundred pages later"))
        card = _card(chunk_id="chunk-0", source_chunk_ids=["chunk-0"])
        session.add(card)
        await session.commit()

        passage = await passage_for_card(card, session)
    assert "four hundred pages later" not in passage


@pytest.mark.asyncio
async def test_an_unrecorded_passage_falls_back_to_the_document_not_to_chunk_id(factory):
    """The fallback is deliberately permissive; `chunk_id` would be wrong, not lax."""
    async with factory() as session:
        session.add(_chunk(0, "first chunk of the scope"))
        session.add(_chunk(1, "the chunk this card actually came from"))
        card = _card(chunk_id="chunk-0", source_chunk_ids=None)
        session.add(card)
        await session.commit()

        passage = await passage_for_card(card, session)
    assert "actually came from" in passage


@pytest.mark.asyncio
async def test_chunks_that_no_longer_exist_yield_no_passage(factory):
    """Re-ingestion replaces chunk ids. An unrebuildable passage must not silently
    become the whole document, or a card would be judged against text it never saw."""
    async with factory() as session:
        card = _card(chunk_id="gone", source_chunk_ids=["gone-1", "gone-2"])
        session.add(card)
        await session.commit()

        assert await passage_for_card(card, session) == ""
