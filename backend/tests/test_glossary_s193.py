"""Tests for S193 -- glossary persistence, upsert, cached endpoint, delete."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import DocumentModel, GlossaryTermModel, SectionModel
from app.services.explain import ExplainService, GlossaryParseError

# ---------------------------------------------------------------------------
# Isolated test DB fixture
# ---------------------------------------------------------------------------

DOC_ID = "doc-s193"
SEC_ID = "sec-intro"


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


async def _seed_doc_and_sections(factory):
    """Insert a document and section for glossary tests."""
    async with factory() as session:
        session.add(DocumentModel(
            id=DOC_ID,
            title="Test Document",
            format="txt",
            content_type="book",
            word_count=5000,
            page_count=20,
            file_path="/tmp/test.txt",
        ))
        session.add(SectionModel(
            id=SEC_ID,
            document_id=DOC_ID,
            heading="Introduction",
            level=1,
            section_order=0,
            preview="Entanglement is a quantum phenomenon where particles share state.",
        ))
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_glossary_persists_terms(test_db):
    """AC: extract_glossary persists terms to GlossaryTermModel table."""
    _engine, factory, _tmp = test_db
    await _seed_doc_and_sections(factory)

    glossary_json = json.dumps([
        {"term": "Entanglement", "definition": "A quantum phenomenon.", "category": "concept"},
        {"term": "Qubit", "definition": "Quantum bit.", "category": "technical"},
    ])

    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[
        MagicMock(text="Entanglement is a quantum phenomenon where particles share state."),
    ])
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=glossary_json)

    with (
        patch("app.services.explain.get_retriever", return_value=retriever),
        patch("app.services.explain.get_llm_service", return_value=llm),
    ):
        svc = ExplainService()
        result = await svc.extract_glossary(DOC_ID)

    assert len(result) == 2
    terms = {r["term"] for r in result}
    assert "Entanglement" in terms
    assert "Qubit" in terms
    # Verify persisted -- must have id field
    assert all(r["id"] for r in result)
    # Entanglement should match the intro section
    ent = next(r for r in result if r["term"] == "Entanglement")
    assert ent["first_mention_section_id"] == SEC_ID
    assert ent["category"] == "concept"


@pytest.mark.asyncio
async def test_cached_endpoint_returns_persisted_terms(test_db):
    """AC: cached endpoint returns persisted terms without invoking LLM."""
    _engine, factory, _tmp = test_db
    await _seed_doc_and_sections(factory)

    # Seed a glossary term directly
    async with factory() as session:
        session.add(GlossaryTermModel(
            id=str(uuid.uuid4()),
            document_id=DOC_ID,
            term="Photon",
            definition="A particle of light.",
            category="concept",
        ))
        await session.commit()

    svc = ExplainService()
    result = await svc.get_cached_glossary(DOC_ID)

    assert len(result) == 1
    assert result[0]["term"] == "Photon"
    assert result[0]["definition"] == "A particle of light."


@pytest.mark.asyncio
async def test_regenerate_upserts_terms(test_db):
    """AC: regenerate upserts (updates existing, adds new, does not remove old)."""
    _engine, factory, _tmp = test_db
    await _seed_doc_and_sections(factory)

    # First generation
    glossary_json_1 = json.dumps([
        {"term": "Entanglement", "definition": "Old definition.", "category": "concept"},
    ])
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[
        MagicMock(text="Entanglement is quantum."),
    ])
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=glossary_json_1)

    with (
        patch("app.services.explain.get_retriever", return_value=retriever),
        patch("app.services.explain.get_llm_service", return_value=llm),
    ):
        svc = ExplainService()
        await svc.extract_glossary(DOC_ID)

    # Second generation with updated definition + new term
    glossary_json_2 = json.dumps([
        {"term": "Entanglement", "definition": "Updated definition.", "category": "concept"},
        {"term": "Superposition", "definition": "Both states at once.", "category": "concept"},
    ])
    llm.generate = AsyncMock(return_value=glossary_json_2)

    with (
        patch("app.services.explain.get_retriever", return_value=retriever),
        patch("app.services.explain.get_llm_service", return_value=llm),
    ):
        result = await svc.extract_glossary(DOC_ID)

    # Should have both terms
    terms_map = {r["term"]: r for r in result}
    assert "Entanglement" in terms_map
    assert "Superposition" in terms_map
    # Definition should be updated
    assert terms_map["Entanglement"]["definition"] == "Updated definition."


@pytest.mark.asyncio
async def test_delete_removes_term(test_db):
    """AC: DELETE removes a specific term by ID."""
    _engine, factory, _tmp = test_db
    await _seed_doc_and_sections(factory)

    term_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(GlossaryTermModel(
            id=term_id,
            document_id=DOC_ID,
            term="Photon",
            definition="A particle of light.",
            category="concept",
        ))
        await session.commit()

    svc = ExplainService()
    deleted = await svc.delete_term(term_id)
    assert deleted is True

    # Verify it's gone
    cached = await svc.get_cached_glossary(DOC_ID)
    assert len(cached) == 0


@pytest.mark.asyncio
async def test_extract_glossary_parse_error_raises():
    """AC: parse failure raises GlossaryParseError."""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[
        MagicMock(text="Some text."),
    ])
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="not valid json at all")

    with (
        patch("app.services.explain.get_retriever", return_value=retriever),
        patch("app.services.explain.get_llm_service", return_value=llm),
    ):
        svc = ExplainService()
        with pytest.raises(GlossaryParseError):
            await svc.extract_glossary("doc-x")
