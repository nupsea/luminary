"""The [Title > Section] header is kept OUT of chunks.text (so it never
enters the embedding) but MUST still land in the FTS5 index via
keyword_index_node, or BM25 loses section/title terms. Drives the real node.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel
from app.workflows.ingestion_nodes.embed import keyword_index_node


@pytest.fixture
async def fts_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    get_settings.cache_clear()
    await engine.dispose()


async def _fts_match(factory, query: str) -> list[str]:
    async with factory() as session:
        rows = await session.execute(
            sa_text("SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH :q"),
            {"q": query},
        )
        return [r[0] for r in rows.fetchall()]


@pytest.mark.asyncio
async def test_context_header_indexed_in_fts_but_not_in_chunk_text(fts_db):
    factory = fts_db
    doc_id, chunk_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="The Time Machine",
                format="txt",
                content_type="book",
                file_path="/tmp/tm.txt",
            )
        )
        session.add(
            ChunkModel(
                id=chunk_id,
                document_id=doc_id,
                chunk_index=0,
                text="The Traveller vanished into the fourth dimension.",
                context_header="[The Time Machine > Chapter 3]",
            )
        )
        await session.commit()

    await keyword_index_node({"document_id": doc_id, "content_type": "book"})

    # body term matches
    assert await _fts_match(factory, "Traveller") == [chunk_id]
    # header-only term (never in body) matches -> header IS indexed for BM25
    assert await _fts_match(factory, "Machine") == [chunk_id]
    assert await _fts_match(factory, "Chapter") == [chunk_id]

    # ...yet the stored chunk text stays clean (never carries the header,
    # so the embedding built from it is header-free).
    async with factory() as session:
        stored = await session.execute(
            sa_text("SELECT text FROM chunks WHERE id = :cid"), {"cid": chunk_id}
        )
        assert "[" not in stored.scalar_one()
