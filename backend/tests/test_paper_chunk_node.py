"""chunk_node's paper path: routing, reference exclusion, and fallback safety."""

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel, SectionModel
from app.workflows.ingestion import chunk_node

PROSE = " ".join(f"Sentence {i} states a claim about the model." for i in range(60))


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield engine, factory, tmp_path
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    get_settings.cache_clear()
    await engine.dispose()


async def _insert_document(factory, doc_id: str, tmp_path: Path) -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="A Research Paper",
                format="pdf",
                content_type="paper",
                word_count=500,
                page_count=10,
                file_path=str(tmp_path / "paper.pdf"),
                stage="chunking",
            )
        )
        await session.commit()


def _state(doc_id: str, sections: list[dict], tmp_path: Path) -> dict:
    return {
        "document_id": doc_id,
        "file_path": str(tmp_path / "paper.pdf"),
        "format": "pdf",
        "content_type": "paper",
        "parsed_document": {
            "title": "A Research Paper",
            "format": "pdf",
            "pages": 10,
            "word_count": 500,
            "sections": sections,
            "raw_text": PROSE,
        },
        "chunks": None,
        "status": "chunking",
        "error": None,
    }


def _section(heading: str, text: str = PROSE) -> dict:
    return {"heading": heading, "level": 1, "text": text, "page_start": 1, "page_end": 2}


PAPER_SECTIONS = [
    _section("Abstract"),
    _section("1. Introduction"),
    _section("2. Methods"),
    _section("3. Results"),
    _section("References", "Smith et al. 2020. A Title. In Proceedings.\nJones 2021. Another."),
]


@pytest.mark.asyncio
async def test_paper_path_excludes_references_from_chunks(test_db):
    _, factory, tmp_path = test_db
    doc_id = "paper-refs"
    await _insert_document(factory, doc_id, tmp_path)

    result = await chunk_node(_state(doc_id, PAPER_SECTIONS, tmp_path))
    assert result["status"] == "embedding"

    async with factory() as session:
        refs = (
            await session.execute(
                select(SectionModel).where(
                    SectionModel.document_id == doc_id, SectionModel.heading == "References"
                )
            )
        ).scalar_one()
        chunks = (
            (
                await session.execute(
                    select(ChunkModel).where(ChunkModel.section_id == refs.id)
                )
            )
            .scalars()
            .all()
        )

    assert refs is not None, "the References section must still exist for reading"
    assert chunks == [], "reference lists must not be indexed"


@pytest.mark.asyncio
async def test_paper_path_sets_context_header(test_db):
    _, factory, tmp_path = test_db
    doc_id = "paper-header"
    await _insert_document(factory, doc_id, tmp_path)
    await chunk_node(_state(doc_id, PAPER_SECTIONS, tmp_path))

    async with factory() as session:
        chunk = (
            (await session.execute(select(ChunkModel).where(ChunkModel.document_id == doc_id)))
            .scalars()
            .first()
        )
    assert chunk.context_header is not None
    assert "A Research Paper" in chunk.context_header


@pytest.mark.asyncio
async def test_unrecognised_structure_falls_back_to_generic(test_db):
    """A misclassified document still ingests, via the generic path."""
    _, factory, tmp_path = test_db
    doc_id = "paper-unstructured"
    await _insert_document(factory, doc_id, tmp_path)

    sections = [_section("Getting Started"), _section("Installing"), _section("FAQ")]
    result = await chunk_node(_state(doc_id, sections, tmp_path))

    assert result["status"] == "embedding"
    async with factory() as session:
        chunks = (
            (await session.execute(select(ChunkModel).where(ChunkModel.document_id == doc_id)))
            .scalars()
            .all()
        )
    assert len(chunks) > 0


@pytest.mark.asyncio
async def test_paper_chunker_failure_falls_back_without_duplicating_sections(test_db):
    """On failure the paper transaction must roll back before the generic retry,
    or the document ends up with two copies of every section."""
    _, factory, tmp_path = test_db
    doc_id = "paper-boom"
    await _insert_document(factory, doc_id, tmp_path)

    with patch(
        "app.services.paper_chunker.chunk_paper_section",
        side_effect=RuntimeError("boom"),
    ):
        result = await chunk_node(_state(doc_id, PAPER_SECTIONS, tmp_path))

    assert result["status"] == "embedding"
    async with factory() as session:
        sections = (
            (await session.execute(select(SectionModel).where(SectionModel.document_id == doc_id)))
            .scalars()
            .all()
        )
        chunks = (
            (await session.execute(select(ChunkModel).where(ChunkModel.document_id == doc_id)))
            .scalars()
            .all()
        )

    assert len(sections) == len(PAPER_SECTIONS), "sections duplicated by the fallback"
    assert len(chunks) > 0
