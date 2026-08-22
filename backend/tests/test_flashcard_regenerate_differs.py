"""Regenerating a deck must not return the questions it just deleted.

The shipped symptom, twice: "Regenerate (replace)" returned the same questions,
and the deck shrank from 5 cards to 3 with no explanation.

Nothing was cached. What a run can ask about is decided by the passage in its
prompt, and the passage was identical every time -- the chunk classifier leaves
a 265-chunk tutorial with 10 eligible chunks, all of which fit the prompt
budget, so every run read the same 1,679 characters. Deleting the deck first
made it worse rather than better: the near-duplicate filter compares a new card
against the cards the document already has, so wiping them first left it
comparing against nothing, and a failed run left the user with an empty deck.

The first attempt at this listed the previous questions in the prompt under
"do not repeat these". That is the anti-pattern I-28 names: verbatim questions
are exemplars a small model copies, not a signal it steers away from.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, FlashcardModel, NoteModel
from app.services.flashcard import FlashcardService
from app.services.flashcard_generators import _drop_near_duplicates, _passage_not_yet_used


def _chunk(index: int, text: str = "passage text") -> ChunkModel:
    return ChunkModel(
        id=f"chunk-{index}",
        document_id="doc-1",
        section_id=None,
        text=text,
        token_count=10,
        page_number=1,
        chunk_index=index,
    )


class TestThePassageMoves:
    """The lever is which chunks reach the prompt, not how they are decoded."""

    def test_chunks_the_deck_was_written_from_are_dropped(self):
        preferred = [_chunk(0), _chunk(1), _chunk(2)]
        fresh = _passage_not_yet_used(preferred, preferred, {"chunk-0", "chunk-1"})
        assert [c.id for c in fresh] == ["chunk-2"]

    def test_the_rest_of_the_document_is_read_once_the_eligible_chunks_are_spent(self):
        """The real case. A generation uses every eligible chunk it has, so the
        second run finds none left -- and 255 of the document's 265 chunks have
        still never been questioned."""
        every = [_chunk(i) for i in range(6)]
        eligible = every[:2]
        fresh = _passage_not_yet_used(every, eligible, {"chunk-0", "chunk-1"})
        assert [c.id for c in fresh] == ["chunk-2", "chunk-3"]

    def test_the_replacement_reads_as_much_as_the_deck_it_replaces_did(self):
        """Not as much as the budget allows. Filling it measured worse on both
        counts that matter -- 12/15 past the grounding gate against 14/15, and
        3-5 cards a run against 4-5 -- for questions no less new."""
        every = [_chunk(i, "x" * 100) for i in range(10)]
        eligible = every[:3]  # 300 characters produced the deck being replaced
        fresh = _passage_not_yet_used(every, eligible, {c.id for c in eligible})
        assert sum(len(c.text) for c in fresh) <= 300
        assert [c.id for c in fresh] == ["chunk-3", "chunk-4", "chunk-5"]

    def test_successive_regenerations_move_further_into_the_document(self):
        """Reading order, so the second replacement does not re-read the first's
        passage -- the sweep is what keeps a fourth deck from repeating a second."""
        every = [_chunk(i, "x" * 100) for i in range(10)]
        eligible = every[:2]
        first = _passage_not_yet_used(every, eligible, {c.id for c in eligible})
        spent = {c.id for c in eligible} | {c.id for c in first}
        second = _passage_not_yet_used(every, eligible, spent)
        assert not spent.intersection(c.id for c in second)

    def test_an_exhausted_document_still_produces_a_passage(self):
        """Delivering a familiar deck beats delivering none. The near-duplicate
        filter, not an empty prompt, is what keeps repeats off the screen."""
        every = [_chunk(i) for i in range(3)]
        used = {c.id for c in every}
        assert _passage_not_yet_used(every, every, used) == every


@pytest.fixture()
async def factory(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'regen.db'}")
    await create_all_tables(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _card(question: str, source_chunk_ids: list[str] | None) -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id="doc-1",
        chunk_id="chunk-0",
        question=question,
        answer="a",
        source_excerpt="",
        difficulty="medium",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        reps=0,
        lapses=0,
        source_chunk_ids=source_chunk_ids,
    )


async def _seed_deck(session, questions: list[str]) -> None:
    for q in questions:
        session.add(_card(q, ["chunk-0", "chunk-1"]))
    await session.commit()


@pytest.mark.asyncio
async def test_the_old_deck_is_still_present_while_the_replacement_is_generated(factory):
    """Deleting first is what let a replacement return what it had just removed:
    `generate` de-duplicates against the cards the document already has."""
    seen: dict[str, object] = {}

    async with factory() as session:
        await _seed_deck(session, ["q1", "q2"])
        service = FlashcardService()

        async def fake_generate(**kwargs):
            rows = (
                await session.execute(select(FlashcardModel.question))
            ).all()
            seen["deck_during_generation"] = sorted(r[0] for r in rows)
            seen["excluded"] = kwargs["exclude_chunk_ids"]
            new = _card("fresh", ["chunk-4"])
            session.add(new)
            await session.commit()
            return [new]

        service.generate = fake_generate  # type: ignore[method-assign]
        result = await service.regenerate(session, document_id="doc-1")

    assert seen["deck_during_generation"] == ["q1", "q2"]
    assert seen["excluded"] == {"chunk-0", "chunk-1"}, (
        "the replacement must be told which chunks the deck it replaces was written from"
    )
    assert result.replaced == 2
    assert result.kept_previous is False


@pytest.mark.asyncio
async def test_a_run_that_produces_nothing_leaves_the_deck_alone(factory):
    """An empty deck is a worse answer than a stale one, and the user did not
    ask to lose their cards -- they asked for different ones."""
    async with factory() as session:
        await _seed_deck(session, ["q1", "q2", "q3"])
        service = FlashcardService()

        async def fake_generate(**_kwargs):
            return []

        service.generate = fake_generate  # type: ignore[method-assign]
        result = await service.regenerate(session, document_id="doc-1")

        remaining = (
            await session.execute(select(FlashcardModel.question))
        ).all()

    assert result.kept_previous is True
    assert result.replaced == 0
    assert sorted(r[0] for r in remaining) == ["q1", "q2", "q3"]


@pytest.mark.asyncio
async def test_a_generation_that_raises_leaves_the_deck_alone(factory):
    """Ollama being down is the common case, and it must not cost the deck.
    Deleting first made an unreachable model indistinguishable from a wipe."""
    async with factory() as session:
        await _seed_deck(session, ["q1", "q2"])
        service = FlashcardService()

        async def fake_generate(**_kwargs):
            raise RuntimeError("ollama is not running")

        service.generate = fake_generate  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            await service.regenerate(session, document_id="doc-1")

        remaining = (
            await session.execute(select(FlashcardModel.question))
        ).all()

    assert sorted(r[0] for r in remaining) == ["q1", "q2"]


@pytest.mark.asyncio
async def test_a_short_delivery_is_reported_rather_than_silently_shipped(factory):
    """5 asked for, 3 delivered, no explanation is what the user saw. The count
    the caller asked for survives to the response."""
    async with factory() as session:
        await _seed_deck(session, ["q1", "q2", "q3", "q4", "q5"])
        service = FlashcardService()

        async def fake_generate(**_kwargs):
            cards = [_card(f"new{i}", ["chunk-4"]) for i in range(3)]
            for c in cards:
                session.add(c)
            await session.commit()
            return cards

        service.generate = fake_generate  # type: ignore[method-assign]
        result = await service.regenerate(session, document_id="doc-1")

    assert result.requested == 5, "the deck's own size is what a replacement asks for"
    assert len(result.cards) == 3
    assert result.replaced == 5


def _note_card(question: str, note_id: str | None) -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=None,
        chunk_id=None,
        note_id=note_id,
        source="note",
        question=question,
        answer="a",
        source_excerpt="",
        difficulty="medium",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        reps=0,
        lapses=0,
    )


@pytest.mark.asyncio
async def test_a_repeat_of_the_note_s_own_card_is_rejected(factory, monkeypatch):
    """The whole novelty mechanism for notes. A note is one short text, so there
    is no unread material to move to -- if this does not fire, "replace" returns
    the deck it replaced."""
    vectors = {
        "What is backpressure?": [1.0, 0.0],
        "What does backpressure do?": [1.0, 0.0],   # a repeat, reworded
        "How large should a buffer be?": [0.0, 1.0],
        "A card about some other note": [1.0, 0.0],
    }

    class _Embedder:
        def encode(self, texts):
            return [vectors[t] for t in texts]

    import app.services.embedder as embedder_module

    monkeypatch.setattr(embedder_module, "get_embedding_service", lambda: _Embedder())

    async with factory() as session:
        session.add(_note_card("What is backpressure?", "note-1"))
        session.add(_note_card("A card about some other note", "note-2"))
        await session.commit()

        kept, dropped = await _drop_near_duplicates(
            [
                {"question": "What does backpressure do?"},
                {"question": "How large should a buffer be?"},
            ],
            session,
            note_id="note-1",
        )

    assert dropped == 1
    assert [c["question"] for c in kept] == ["How large should a buffer be?"]


@pytest.mark.asyncio
async def test_a_card_about_another_note_is_not_a_duplicate(factory, monkeypatch):
    """Scoped to the note being replaced. Comparing against the whole library
    would reject a note's first card because some other note asked something
    similar."""

    class _Embedder:
        def encode(self, texts):
            return [[1.0, 0.0] for _ in texts]

    import app.services.embedder as embedder_module

    monkeypatch.setattr(embedder_module, "get_embedding_service", lambda: _Embedder())

    async with factory() as session:
        session.add(_note_card("A card about some other note", "note-2"))
        await session.commit()

        kept, dropped = await _drop_near_duplicates(
            [{"question": "What is backpressure?"}], session, note_id="note-1"
        )

    assert dropped == 0 and len(kept) == 1


@pytest.mark.asyncio
async def test_a_note_deck_is_replaced_the_same_way_a_document_deck_is(factory):
    """Same three steps. A note has no unread material to move to, so what makes
    the replacement different is rejection: the run is told which note it is
    replacing, and its candidates are compared against that note's cards."""
    seen: dict[str, object] = {}

    async with factory() as session:
        for q in ("What does idempotency guarantee?", "What is backpressure?"):
            session.add(_note_card(q, "note-1"))
        await session.commit()
        service = FlashcardService()

        async def fake_notes(**kwargs):
            rows = (
                await session.execute(select(FlashcardModel.question))
            ).all()
            seen["deck_during_generation"] = sorted(r[0] for r in rows)
            seen["replacing_note_id"] = kwargs["replacing_note_id"]
            seen["note_ids"] = kwargs["note_ids"]
            new = _note_card("something else entirely", "note-1")
            session.add(new)
            await session.commit()
            return [new]

        service.generate_from_notes = fake_notes  # type: ignore[method-assign]
        result = await service.regenerate(session, note_id="note-1")

        remaining = (
            await session.execute(select(FlashcardModel.question))
        ).all()

    assert seen["note_ids"] == ["note-1"]
    assert seen["replacing_note_id"] == "note-1", (
        "without it nothing compares the new cards against the ones being replaced"
    )
    assert len(seen["deck_during_generation"]) == 2, "the old cards must outlive the run"
    assert result.replaced == 2
    assert [r[0] for r in remaining] == ["something else entirely"]


@pytest.mark.asyncio
async def test_a_note_run_that_produces_nothing_leaves_its_cards_alone(factory):
    async with factory() as session:
        session.add(_note_card("What is backpressure?", "note-1"))
        await session.commit()
        service = FlashcardService()

        async def fake_notes(**_kwargs):
            return []

        service.generate_from_notes = fake_notes  # type: ignore[method-assign]
        result = await service.regenerate(session, note_id="note-1")

        remaining = (
            await session.execute(select(FlashcardModel.question))
        ).all()

    assert result.kept_previous is True
    assert [r[0] for r in remaining] == ["What is backpressure?"]


@pytest.mark.asyncio
async def test_one_source_per_call(factory):
    """A collection replaces its sources one at a time. Two sources in one call
    would have no honest count to report and no safe order to delete in."""
    async with factory() as session:
        service = FlashcardService()
        with pytest.raises(ValueError):
            await service.regenerate(session, document_id="doc-1", note_id="note-1")
        with pytest.raises(ValueError):
            await service.regenerate(session)


@pytest.mark.asyncio
async def test_a_note_deck_can_be_found_at_all(factory):
    """Cards from the note_ids path carried no note_id, so nothing could scope
    them: `collection_card_filter` matches on it, which is why a collection
    replace stacked a new batch of note cards on top of the old ones instead of
    replacing them. 75 such rows exist in the dev library."""
    async with factory() as session:
        session.add(_note_card("q", None))
        await session.commit()
        service = FlashcardService()

        async def fake_notes(**_kwargs):
            return []

        service.generate_from_notes = fake_notes  # type: ignore[method-assign]
        result = await service.regenerate(session, note_id="note-1")

    assert result.replaced == 0, (
        "a card with no note_id cannot be attributed, and must not be swept up "
        "by a replacement of some other note"
    )


_NOTE_TEXT = "Backpressure is the signal a slow consumer sends upstream to stop."


def _llm_returning_one_card() -> AsyncMock:
    """Concept extraction, then one card whose quote is really in the note --
    anything else is dropped by the grounding gate before it reaches the DB."""
    return AsyncMock(side_effect=[
        '{"domain": "systems", "concepts": [{"concept": "backpressure"}]}',
        '[{"question": "What is backpressure?", "answer": "A stop signal.",'
        ' "source_excerpt": "the signal a slow consumer sends upstream"}]',
    ])


@pytest.mark.asyncio
async def test_a_card_from_one_note_records_which_note(factory):
    """Without it nothing can scope, replace or delete the card by its source:
    `collection_card_filter` matches `note_id`, so a NULL made the card
    invisible to the collection it belongs to."""
    from app.services.flashcard_generators import generate_from_notes

    async with factory() as session:
        session.add(NoteModel(id="note-1", content=_NOTE_TEXT, tags=[]))
        await session.commit()

        with patch("app.services.llm.LLMService.generate", _llm_returning_one_card()):
            cards = await generate_from_notes(None, ["note-1"], 1, session)

    assert cards, "the gate dropped the card; the quote must be in the note text"
    assert all(c.note_id == "note-1" for c in cards)


@pytest.mark.asyncio
async def test_a_card_from_several_notes_records_no_note(factory):
    """Their text is concatenated into one prompt, so no single note wrote the
    card. Naming one would be the false provenance I-35 exists to prevent."""
    from app.services.flashcard_generators import generate_from_notes

    async with factory() as session:
        session.add(NoteModel(id="note-1", content=_NOTE_TEXT, tags=[]))
        session.add(NoteModel(id="note-2", content="A queue absorbs bursts.", tags=[]))
        await session.commit()

        with patch("app.services.llm.LLMService.generate", _llm_returning_one_card()):
            cards = await generate_from_notes(None, ["note-1", "note-2"], 1, session)

    assert cards
    assert all(c.note_id is None for c in cards)
