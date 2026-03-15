import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.database import Base
from app.models import (  # noqa: F401 — imported to register ORM models with Base.metadata
    AnnotationModel,
    ChunkModel,
    CodeSnippetModel,
    DocumentModel,
    EnrichmentJobModel,
    EvalRunModel,
    FlashcardModel,
    ImageModel,
    LearningGoalModel,
    LearningObjectiveModel,
    LibrarySummaryModel,
    MisconceptionModel,
    NoteModel,
    QAHistoryModel,
    ReadingProgressModel,
    SectionModel,
    SectionSummaryModel,
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

NOTES_FTS5_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
USING fts5(
    content,
    note_id UNINDEXED,
    document_id UNINDEXED
)
"""

IMAGES_FTS5_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS images_fts
USING fts5(
    body,
    image_id UNINDEXED,
    document_id UNINDEXED
)
"""


async def create_all_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(FTS5_DDL))
        await conn.execute(text(NOTES_FTS5_DDL))
        await conn.execute(text(IMAGES_FTS5_DDL))
        await conn.execute(text("PRAGMA foreign_keys = ON"))

        # Additive migrations — safe to run on existing databases.
        # SQLite ignores "duplicate column" errors so we wrap each in its own try.
        for ddl in [
            "ALTER TABLE documents ADD COLUMN file_hash TEXT",
            "ALTER TABLE documents ADD COLUMN chapter_count INTEGER",
            "ALTER TABLE documents ADD COLUMN conversation_metadata JSON",
            "ALTER TABLE flashcards ADD COLUMN source TEXT NOT NULL DEFAULT 'document'",
            "ALTER TABLE flashcards ADD COLUMN deck TEXT NOT NULL DEFAULT 'default'",
            "ALTER TABLE flashcards ADD COLUMN difficulty TEXT NOT NULL DEFAULT 'medium'",
            "ALTER TABLE notes ADD COLUMN section_id TEXT",
            "ALTER TABLE annotations ADD COLUMN note_text TEXT",
            "ALTER TABLE study_sessions ADD COLUMN accuracy_pct REAL",
            "ALTER TABLE documents ADD COLUMN audio_duration_seconds REAL",
            "ALTER TABLE documents ADD COLUMN error_message TEXT",
            "ALTER TABLE documents ADD COLUMN source_url TEXT",
            "ALTER TABLE documents ADD COLUMN video_title TEXT",
            "ALTER TABLE chunks ADD COLUMN has_code INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE chunks ADD COLUMN code_language TEXT",
            "ALTER TABLE chunks ADD COLUMN code_signature TEXT",
            "ALTER TABLE sections ADD COLUMN admonition_type TEXT",
            "ALTER TABLE sections ADD COLUMN parent_section_id TEXT",
        ]:
            try:
                await conn.execute(text(ddl))
            except Exception:
                pass  # column already exists

    logger.info("Database tables and FTS5 index initialized")
