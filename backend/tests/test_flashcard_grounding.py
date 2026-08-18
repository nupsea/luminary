"""A card has to be able to prove where it came from, and say so when it cannot.

The generation gate rejects a card whose quote is not in its passage. It says
nothing about the cards created before that gate existed, and a deck is reviewed
for years rather than regenerated. Measured on a real 949-card library: 26% of the
cards that quoted anything quoted text absent from their document, and the review
screen was showing every one of them under a heading that reads "Source".

`grounding` is four states, not a boolean, because "checked and found" and "nothing
could be checked" must never collapse into the same answer.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, FlashcardModel
from app.services.flashcard_parsers import (
    GROUNDING_UNSUPPORTED,
    GROUNDING_UNVERIFIABLE,
    GROUNDING_VERIFIED,
    excerpt_is_verbatim,
    grounding_state,
)

_PASSAGE = (
    "Penelope set up a great web in her house and told the suitors she would choose "
    "a husband when it was finished, but she undid her work each night for three "
    "years, so the weaving was never done."
)


class TestGroundingState:
    def test_a_real_quote_is_verified(self):
        assert grounding_state("she undid her work each night", _PASSAGE) == GROUNDING_VERIFIED

    def test_an_invented_quote_is_unsupported(self):
        assert (
            grounding_state("Penelope wove for ten years without rest", _PASSAGE)
            == GROUNDING_UNSUPPORTED
        )

    def test_no_quote_is_unverifiable_not_unsupported(self):
        """Unproven is not disproven. A card with no quote asserts nothing false."""
        assert grounding_state("", _PASSAGE) == GROUNDING_UNVERIFIABLE

    def test_no_source_text_is_unverifiable_even_with_a_quote(self):
        """The card may be perfect; there is simply nothing left to check it against."""
        assert grounding_state("she undid her work each night", "") == GROUNDING_UNVERIFIABLE

    def test_the_prompts_own_example_can_never_ground_a_card(self):
        from app.services.flashcard_prompts import EXAMPLE_SOURCE_EXCERPT

        assert (
            grounding_state(EXAMPLE_SOURCE_EXCERPT, EXAMPLE_SOURCE_EXCERPT)
            == GROUNDING_UNSUPPORTED
        )


class TestQuoteEdges:
    """The two cases that decide how much of a quote's edge may differ.

    Measured over 392 checkable cards in a real library: 4 rejections differed from
    the document by exactly one trailing character on a span whose other ~300
    characters were verbatim. Trimming one such character recovers a real card; it
    cannot rescue a fabricated one, which differs by content rather than by
    punctuation.
    """

    def test_a_closing_period_the_document_does_not_have_still_matches(self):
        assert excerpt_is_verbatim("the weaving was never done.", _PASSAGE)

    def test_a_wrapping_quotation_mark_still_matches(self):
        assert excerpt_is_verbatim('"the weaving was never done"', _PASSAGE)

    def test_a_trailing_clause_the_document_does_not_have_does_not_match(self):
        """Content, not punctuation -- this must stay rejected."""
        assert not excerpt_is_verbatim(
            "the weaving was never done and the suitors left", _PASSAGE
        )


@pytest.fixture()
async def test_db(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'grounding.db'}")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_session_factory", factory)
    yield factory
    await engine.dispose()


async def _seed(factory) -> str:
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="the_odyssey",
                format="txt",
                content_type="book",
                word_count=100,
                page_count=1,
                file_path="/tmp/the_odyssey.txt",
                stage="complete",
                tags=[],
            )
        )
        session.add(
            ChunkModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                section_id=None,
                text=_PASSAGE,
                token_count=40,
                page_number=1,
                chunk_index=0,
            )
        )
        await session.commit()
    return doc_id


def _card(doc_id: str | None, excerpt: str, **kw) -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        question="How did Penelope delay the suitors?",
        answer="She unravelled her weaving each night.",
        source_excerpt=excerpt,
        difficulty="medium",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        reps=0,
        lapses=0,
        **kw,
    )


@pytest.mark.asyncio
async def test_the_audit_separates_real_quotes_from_invented_ones(test_db):
    doc_id = await _seed(test_db)
    async with test_db() as session:
        session.add(_card(doc_id, "she undid her work each night"))
        session.add(_card(doc_id, "Penelope wove for ten years without rest"))
        session.add(_card(doc_id, ""))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/flashcards/grounding/audit", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] == 3
    assert body["verified"] == 1
    assert body["unsupported"] == 1
    assert body["unverifiable"] == 1
    assert body["changed"] == 3, "every card started unchecked"


@pytest.mark.asyncio
async def test_the_audit_persists_the_verdict(test_db):
    doc_id = await _seed(test_db)
    async with test_db() as session:
        session.add(_card(doc_id, "Penelope wove for ten years without rest"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/flashcards/grounding/audit", json={"document_id": doc_id})

    async with test_db() as session:
        stored = (await session.execute(select(FlashcardModel.grounding))).scalars().all()
    assert stored == [GROUNDING_UNSUPPORTED], "a verdict computed and dropped is no verdict"


@pytest.mark.asyncio
async def test_the_audit_never_downgrades_a_verdict_it_cannot_recheck(test_db):
    """A note-sourced card has no document. Its verdict was decided at generation,
    while the note text was in hand; replacing it with 'unverifiable' would delete a
    real measurement and put an absence of one in its place."""
    await _seed(test_db)
    async with test_db() as session:
        session.add(_card(None, "a quote from a note", source="note", grounding=GROUNDING_VERIFIED))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/flashcards/grounding/audit", json={})

    assert resp.json()["verified"] == 1
    async with test_db() as session:
        stored = (await session.execute(select(FlashcardModel.grounding))).scalars().all()
    assert stored == [GROUNDING_VERIFIED]


@pytest.mark.asyncio
async def test_a_gap_card_is_not_accused_of_faking_a_quote(test_db):
    """`source='gap'` writes the knowledge gap into source_excerpt -- it never
    claimed to quote a passage, and auditing it would report a label as a lie."""
    doc_id = await _seed(test_db)
    async with test_db() as session:
        session.add(
            _card(doc_id, "consistent hashing", source="gap", grounding=GROUNDING_UNVERIFIABLE)
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/flashcards/grounding/audit", json={})
    assert resp.json()["unsupported"] == 0
    assert resp.json()["unverifiable"] == 1


@pytest.mark.asyncio
async def test_the_summary_reports_unchecked_as_its_own_number(test_db):
    """Folding 'nobody looked' into a pass rate is how an unaudited deck reads clean."""
    doc_id = await _seed(test_db)
    async with test_db() as session:
        session.add(_card(doc_id, "she undid her work each night"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/flashcards/grounding")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "scanned": 1,
        "changed": 0,
        "verified": 0,
        "unsupported": 0,
        "unverifiable": 0,
        "unchecked": 1,
    }


def test_the_gate_records_the_verdict_on_the_card_it_keeps():
    from app.services.flashcard_generators import _gate_cards

    kept = _gate_cards(
        [
            {
                "question": "How did Penelope delay the suitors?",
                "answer": "She unravelled her weaving each night.",
                "source_excerpt": "she undid her work each night",
            }
        ],
        source_text=_PASSAGE,
    )
    assert [c["grounding"] for c in kept] == [GROUNDING_VERIFIED]
