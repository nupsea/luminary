"""Concept-scoped generation grounds in a concept's evidence ACROSS all its documents.

The payoff of the global concept layer: one idea ("data modeling") extracted from two different
books should generate questions grounded in BOTH, not just whichever document was first. Guards
against the old behavior, where _generate_for_concepts used only doc_ids[0] (and, in fact, only a
one-line hint with no source text).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, ConceptModel, DocumentModel, FlashcardModel
from app.services import study_assembler
from app.services.study_assembler import _concept_evidence_text, _generate_for_concepts

_TEXT_A = "Relational data modeling centers on normalization and foreign keys across tables."
_TEXT_B = "Dimensional data modeling centers on star schemas with fact and dimension tables."


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_e, orig_f = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield factory
    db_module._engine, db_module._session_factory = orig_e, orig_f


async def _seed_two_books_one_concept(factory):
    async with factory() as s:
        for did, title in (("bookA", "Relational DBs"), ("bookB", "Data Warehousing")):
            s.add(DocumentModel(id=did, title=title, format="pdf",
                                content_type="tech_book", file_path=f"/tmp/{did}.pdf"))
        s.add(ChunkModel(id="chA", document_id="bookA", text=_TEXT_A, chunk_index=0))
        s.add(ChunkModel(id="chB", document_id="bookB", text=_TEXT_B, chunk_index=0))
        s.add(ConceptModel(
            id="c1", slug="c-data-modeling", label="data modeling", kind="concept",
            origin="document", status="proposed", level=2,
            evidence_json=[{
                "document_ids": ["bookA", "bookB"],
                "chunk_ids": ["chA", "chB"],
                "members": ["data modeling", "normalization", "star schema"],
            }],
        ))
        await s.commit()


async def test_evidence_text_spans_both_documents(test_db):
    await _seed_two_books_one_concept(test_db)
    async with test_db() as s:
        text = await _concept_evidence_text(s, ["chA", "chB"])
    assert "normalization" in text          # from bookA
    assert "star schemas" in text           # from bookB


async def test_concept_generation_grounds_across_docs(test_db, monkeypatch):
    await _seed_two_books_one_concept(test_db)

    captured: dict[str, str | None] = {}

    async def fake_generate(self, document_id, scope, section_heading, count, session,
                            difficulty="medium", context=None):
        captured["context"] = context
        now = datetime.now(UTC)
        return [
            FlashcardModel(
                id=f"card{i}", document_id=document_id, chunk_id="chA", source="concept",
                question=f"q{i}", answer=f"a{i}", fsrs_state="new", fsrs_stability=0.0,
                fsrs_difficulty=0.0, due_date=now, reps=0, lapses=0, created_at=now,
            )
            for i in range(count)
        ]

    monkeypatch.setattr(
        "app.services.flashcard.FlashcardService.generate", fake_generate
    )

    async with test_db() as s:
        cards = await _generate_for_concepts(s, ["c1"], count=4)

    # generation was grounded in BOTH books' evidence, not just doc_ids[0]
    ctx = captured["context"] or ""
    assert "normalization" in ctx and "star schemas" in ctx
    assert "data modeling" in ctx  # the concept focus hint is present
    # and the produced cards are mapped back to the concept
    assert cards and all(c.concept_id == "c1" and c.mapping_status == "mapped" for c in cards)
    assert all(c.source_scope == "concept:c1" for c in cards)


async def test_falls_back_to_whole_doc_when_no_evidence_chunks(test_db, monkeypatch):
    """A concept with no captured chunk_ids still generates -- grounded in the primary doc."""
    async with test_db() as s:
        s.add(DocumentModel(id="bookA", title="Relational DBs", format="pdf",
                            content_type="tech_book", file_path="/tmp/a.pdf"))
        s.add(ConceptModel(
            id="c2", slug="c-x", label="indexing", kind="concept", origin="document",
            status="proposed", level=2,
            evidence_json=[{"document_ids": ["bookA"], "chunk_ids": [], "members": ["indexing"]}],
        ))
        await s.commit()

    seen: dict[str, object] = {}

    async def fake_generate(self, document_id, scope, section_heading, count, session,
                            difficulty="medium", context=None):
        seen["context"] = context
        seen["document_id"] = document_id
        return []

    monkeypatch.setattr("app.services.flashcard.FlashcardService.generate", fake_generate)
    async with test_db() as s:
        await _generate_for_concepts(s, ["c2"], count=2)
    # fallback path: no evidence -> no context override, grounded in the doc itself
    assert seen["context"] is None and seen["document_id"] == "bookA"
    assert study_assembler._CONCEPT_EVIDENCE_CHARS == 9000  # sanity: budget wired
