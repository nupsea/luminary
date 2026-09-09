"""What text a teach-back is actually graded against.

`source_chunk_ids` is the whole generation batch's passage: every card produced
by one call records the same list, and over `_CHUNK_CHAR_LIMIT` that list is
windows sampled from across the document. Measured on a real library on
2026-09-09: 173 of 173 cards with recorded chunks were graded against more than
one chunk, 41% of those passages jumped across the document, and a recorded
passage ran to 6.5 chunks against the 3.7 the card was written from -- 38% of
the graded text was some other card's.

`completeness` is scored against that text. The card that produced this file
asked why personal context matters and was marked down for not explaining
`agents.md` and `/skeptical` -- two topics from other windows of the same batch.

The fixture below is that card's real shape: recorded chunks 12, 20, 28 and 29 of
a forty-chunk transcript, three separate runs, with the card's own quote in 28.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, FlashcardModel
from app.routers.study import _card_scope_passage, _source_passage

_TEXT = {
    12: "If you care about the outcome, whatever it is, technical or usage, you can do it.",
    20: "You can set up agents.md, skills, slash commands, all this stuff.",
    28: "This is like slash skeptical. It will go and actually check code.",
    29: "I run this every time I do not get it and models will get smarter.",
}
_QUOTE = "It will go and actually check code."


@pytest.fixture
async def db():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(factory, doc_id: str) -> dict[int, str]:
    ids: dict[int, str] = {}
    async with factory() as session:
        for index, text in _TEXT.items():
            chunk_id = str(uuid.uuid4())
            ids[index] = chunk_id
            session.add(
                ChunkModel(
                    id=chunk_id,
                    document_id=doc_id,
                    text=text,
                    chunk_index=index,
                    token_count=0,
                    page_number=0,
                )
            )
        await session.commit()
    return ids


def _card(doc_id: str, chunk_ids: list[str], *, excerpt: str = _QUOTE) -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=chunk_ids[0],
        question="What happens when you ask an agent to be skeptical about a bug report?",
        answer="It checks the code.",
        source_excerpt=excerpt,
        source_chunk_ids=chunk_ids,
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=3.0,
        due_date=now,
        reps=0,
        lapses=0,
        created_at=now,
    )


@pytest.mark.asyncio
async def test_the_card_is_graded_against_its_own_run_of_chunks(db):
    """Chunks 28 and 29 are the passage. 12 and 20 are two other cards' topics."""
    doc_id = str(uuid.uuid4())
    ids = await _seed(db, doc_id)
    card = _card(doc_id, [ids[12], ids[20], ids[28], ids[29]])

    async with db() as session:
        passage = await _card_scope_passage(card, session)

    assert _TEXT[28] in passage
    # The chunk after the quote comes with it: a run is the passage's context,
    # and a quote spanning the seam between them is real.
    assert _TEXT[29] in passage
    assert _TEXT[12] not in passage
    assert _TEXT[20] not in passage


@pytest.mark.asyncio
async def test_the_foreign_material_is_what_completeness_was_measured_against(db):
    """The whole point, stated as the ratio it moves.

    `_source_passage` is what reaches the prompt, so the assertion is on that
    rather than on the helper.
    """
    doc_id = str(uuid.uuid4())
    ids = await _seed(db, doc_id)
    card = _card(doc_id, [ids[12], ids[20], ids[28], ids[29]])

    async with db() as session:
        passage = await _source_passage(card, session)

    own = len(_TEXT[28]) + len(_TEXT[29])
    foreign = len(passage) - own
    assert foreign < own / 2, passage


@pytest.mark.asyncio
async def test_a_quote_spanning_the_seam_still_locates_its_run(db):
    """Runs are matched joined, not chunk by chunk: chunking cuts sentences."""
    doc_id = str(uuid.uuid4())
    ids = await _seed(db, doc_id)
    spanning = "actually check code.\n\nI run this every time"
    card = _card(doc_id, [ids[12], ids[20], ids[28], ids[29]], excerpt=spanning)

    async with db() as session:
        passage = await _card_scope_passage(card, session)

    assert _TEXT[28] in passage
    assert _TEXT[29] in passage
    assert _TEXT[12] not in passage


@pytest.mark.parametrize(
    ("label", "indices", "excerpt"),
    [
        # Already one continuous run: the caller's fallback is the same text.
        ("contiguous", [28, 29], _QUOTE),
        ("a single chunk", [28], _QUOTE),
    ],
)
@pytest.mark.asyncio
async def test_a_continuous_passage_needs_no_narrowing(db, label, indices, excerpt):
    doc_id = str(uuid.uuid4())
    ids = await _seed(db, doc_id)
    card = _card(doc_id, [ids[i] for i in indices], excerpt=excerpt)

    async with db() as session:
        assert await _card_scope_passage(card, session) == "", label
        assert _TEXT[28] in await _source_passage(card, session)


@pytest.mark.parametrize(
    ("label", "excerpt"),
    [
        # 2 of the 173 cards measured name a quote that is in none of them.
        ("quote is in none of them", "a sentence from nowhere"),
        ("no quote at all", ""),
    ],
)
@pytest.mark.asyncio
async def test_an_unlocatable_card_keeps_everything_with_its_seams_marked(
    db, label, excerpt
):
    """Grading against too much beats grading against nothing. But four places in
    a document are not one passage, and the evaluator cannot see a gap that is
    not marked."""
    doc_id = str(uuid.uuid4())
    ids = await _seed(db, doc_id)
    card = _card(doc_id, [ids[12], ids[20], ids[28], ids[29]], excerpt=excerpt)

    async with db() as session:
        passage = await _source_passage(card, session)

    for text in _TEXT.values():
        assert text in passage, label
    assert passage.count("[...]") == 2, label


# Generation-side attribution: what a NEW card records, so no repair is needed


def test_a_new_card_records_the_window_it_was_written_from():
    """`source_chunk_ids` was the whole batch's sampled list on every card of a
    call. The quote picks the window out, exactly as grading does."""
    from app.services.flashcard_generators import _card_chunk_ids

    chunks = [
        ChunkModel(id=f"c{i}", document_id="d", text=_TEXT[i], chunk_index=i)
        for i in (12, 20, 28, 29)
    ]
    batch = [c.id for c in chunks]

    assert _card_chunk_ids(chunks, batch, _QUOTE) == ["c28", "c29"]


@pytest.mark.parametrize(
    ("label", "excerpt"),
    [
        ("quote in none of the windows", "a sentence from nowhere"),
        ("no quote at all", ""),
    ],
)
def test_an_unlocatable_new_card_keeps_the_whole_batch(label, excerpt):
    """Claiming too much is the safe direction: every reader of this column
    treats a wider passage as more permissive, never less."""
    from app.services.flashcard_generators import _card_chunk_ids

    chunks = [
        ChunkModel(id=f"c{i}", document_id="d", text=_TEXT[i], chunk_index=i)
        for i in (12, 20, 28, 29)
    ]
    batch = [c.id for c in chunks]

    assert _card_chunk_ids(chunks, batch, excerpt) == batch, label


# A recording is not automatically a meeting


class _Doc:
    form = None
    domain = None
    register = None
    title = "Practical Tips for Vibe Coding & Agent Workflows"

    def __init__(self, content_type: str) -> None:
        self.content_type = content_type


@pytest.mark.parametrize(
    ("label", "content_type", "has_speakers", "expected"),
    [
        # A conference talk ingested as `audio`, which this branch called a
        # meeting -- the defect `_infer_genre`'s own docstring names.
        ("a talk", "audio", False, "non-fiction"),
        ("a talk, nothing measured", "audio", None, "non-fiction"),
        ("a recording with participants", "audio", True, "conversation"),
        ("a video", "video", False, "non-fiction"),
        # Named as a conversation by ingestion: still a meeting.
        ("a meeting", "meeting", None, "conversation"),
        ("a transcript", "transcript", None, "conversation"),
    ],
)
def test_a_recording_is_not_automatically_a_meeting(
    label, content_type, has_speakers, expected
):
    from app.services.flashcard_prompts import _infer_genre

    assert _infer_genre(_Doc(content_type), has_speakers=has_speakers) == expected, label
