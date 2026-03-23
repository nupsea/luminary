import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import DocumentModel


@pytest.fixture
async def db_session():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_insert_and_retrieve_document(db_session: AsyncSession):
    doc_id = str(uuid.uuid4())
    doc = DocumentModel(
        id=doc_id,
        title="Test Document",
        format="pdf",
        content_type="paper",
        word_count=1000,
        page_count=10,
        file_path="/tmp/test.pdf",
        stage="complete",
        created_at=datetime.now(UTC),
        last_accessed_at=datetime.now(UTC),
    )
    db_session.add(doc)
    await db_session.commit()

    retrieved = await db_session.get(DocumentModel, doc_id)
    assert retrieved is not None
    assert retrieved.title == "Test Document"
    assert retrieved.format == "pdf"
    assert retrieved.content_type == "paper"
    assert retrieved.word_count == 1000
    assert retrieved.stage == "complete"


async def test_fts5_table_exists(db_session: AsyncSession):
    from sqlalchemy import text

    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks_fts'")
    )
    row = result.fetchone()
    assert row is not None, "chunks_fts FTS5 virtual table was not created"
