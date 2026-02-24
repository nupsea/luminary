import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.database import Base
from app.models import (  # noqa: F401 — imported to register ORM models with Base.metadata
    ChunkModel,
    DocumentModel,
    EvalRunModel,
    FlashcardModel,
    MisconceptionModel,
    NoteModel,
    QAHistoryModel,
    SectionModel,
    SettingsModel,
    StudySessionModel,
    SummaryModel,
)

logger = logging.getLogger(__name__)

FTS5_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
USING fts5(
    text,
    chunk_id UNINDEXED,
    document_id UNINDEXED
)
"""


async def create_all_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(FTS5_DDL))
    logger.info("Database tables and FTS5 index initialized")
