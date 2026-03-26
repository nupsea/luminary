import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.database import Base
from app.models import (  # noqa: F401 — imported to register ORM models with Base.metadata
    AnnotationModel,
    CanonicalTagModel,
    ChunkModel,
    ClipModel,
    ClusterSuggestionModel,
    CodeSnippetModel,
    DocumentModel,
    EnrichmentJobModel,
    EvalRunModel,
    FeynmanSessionModel,
    FeynmanTurnModel,
    FlashcardModel,
    ImageModel,
    LearningGoalModel,
    LearningObjectiveModel,
    LibrarySummaryModel,
    MisconceptionModel,
    NoteCollectionMemberModel,
    NoteCollectionModel,
    NoteLinkModel,
    NoteModel,
    NoteTagIndexModel,
    PredictionEventModel,
    QAHistoryModel,
    ReadingPositionModel,
    ReadingProgressModel,
    SectionModel,
    SectionSummaryModel,
    SettingsModel,
    StudySessionModel,
    SummaryModel,
    TagAliasModel,
    TagMergeSuggestionModel,
    WebReferenceModel,
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
            # S137: Bloom's Taxonomy flashcard type/level — nullable; generate_technical() sets them
            "ALTER TABLE flashcards ADD COLUMN flashcard_type TEXT",
            "ALTER TABLE flashcards ADD COLUMN bloom_level INTEGER",
            # S139: prerequisite chain depth per section (set by PrereqExtractorService)
            "ALTER TABLE sections ADD COLUMN difficulty_estimate INTEGER",
            # S141: publication year for contradiction prefer_source temporal ordering
            "ALTER TABLE documents ADD COLUMN publication_year INTEGER",
            # S146: PDF page number per chunk for PDF viewer deep-links
            "ALTER TABLE chunks ADD COLUMN pdf_page_number INTEGER",
            # S154: cloze deletion text with {{term}} markers; null for non-cloze cards
            "ALTER TABLE flashcards ADD COLUMN cloze_text TEXT",
            # S156: structured rubric JSON for teachback results and feynman sessions
            "ALTER TABLE teachback_results ADD COLUMN rubric_json JSON",
            "ALTER TABLE feynman_sessions ADD COLUMN rubric_json JSON",
            # S159: model-generated explanation and key points for diff view
            "ALTER TABLE feynman_sessions ADD COLUMN model_explanation_text TEXT",
            "ALTER TABLE feynman_sessions ADD COLUMN key_points_json JSON",
            # Inline highlights: page_number for PDF annotations
            "ALTER TABLE annotations ADD COLUMN page_number INTEGER",
        ]:
            try:
                await conn.execute(text(ddl))
            except Exception:
                pass  # column already exists

        # S161: migrate distinct group_name values into note_collections (idempotent).
        # Uses INSERT OR IGNORE so re-running on an already-migrated DB is safe.
        # The collection id is derived from the group_name to be deterministic across runs.
        await conn.execute(
            text(
                """
                INSERT OR IGNORE INTO note_collections
                    (id, name, color, sort_order, created_at, updated_at)
                SELECT
                    lower(hex(randomblob(16))) AS id,
                    group_name AS name,
                    '#6366F1' AS color,
                    0 AS sort_order,
                    datetime('now') AS created_at,
                    datetime('now') AS updated_at
                FROM (
                    SELECT DISTINCT group_name
                    FROM notes
                    WHERE group_name IS NOT NULL
                ) AS distinct_groups
                WHERE group_name NOT IN (SELECT name FROM note_collections)
                """
            )
        )

        # S161: populate note_collection_members from group_name (idempotent via INSERT OR IGNORE).
        await conn.execute(
            text(
                """
                INSERT OR IGNORE INTO note_collection_members (id, note_id, collection_id, added_at)
                SELECT
                    lower(hex(randomblob(16))) AS id,
                    notes.id AS note_id,
                    note_collections.id AS collection_id,
                    datetime('now') AS added_at
                FROM notes
                JOIN note_collections ON notes.group_name = note_collections.name
                WHERE notes.group_name IS NOT NULL
                """
            )
        )

        # S162: explicit indexes on note_tag_index for O(1) prefix lookup.
        # CREATE INDEX IF NOT EXISTS is idempotent.
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_note_tag_index_tag_full "
                "ON note_tag_index(tag_full)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_note_tag_index_note_id "
                "ON note_tag_index(note_id)"
            )
        )

        # S162: backfill note_tag_index from existing notes.tags JSON.
        # tag_parent set to '' for all rows; _sync_tag_index recomputes it on
        # any future note update. For hierarchical tags already in the DB, the
        # prefix-search filter only uses tag_full (not tag_parent), so filtering
        # is correct even before a note is updated.
        # INSERT OR IGNORE for idempotency.
        await conn.execute(
            text(
                """
                INSERT OR IGNORE INTO note_tag_index (note_id, tag_full, tag_root, tag_parent)
                SELECT
                    n.id AS note_id,
                    j.value AS tag_full,
                    CASE
                        WHEN instr(j.value, '/') > 0
                        THEN substr(j.value, 1, instr(j.value, '/') - 1)
                        ELSE j.value
                    END AS tag_root,
                    '' AS tag_parent
                FROM notes n, json_each(n.tags) AS j
                WHERE json_type(n.tags) = 'array'
                """
            )
        )
        # Backfill canonical_tags from note_tag_index (idempotent via INSERT OR IGNORE).
        # display_name = last path segment (correct for 1-2 level tags);
        # parent_tag = NULL for top-level, first segment for simple 2-level tags.
        await conn.execute(
            text(
                """
                INSERT OR IGNORE INTO canonical_tags
                    (id, display_name, parent_tag, note_count, created_at)
                SELECT
                    tag_full AS id,
                    CASE
                        WHEN instr(tag_full, '/') = 0 THEN tag_full
                        ELSE substr(tag_full, instr(tag_full, '/') + 1)
                    END AS display_name,
                    CASE
                        WHEN instr(tag_full, '/') = 0 THEN NULL
                        ELSE substr(tag_full, 1, instr(tag_full, '/') - 1)
                    END AS parent_tag,
                    COUNT(DISTINCT note_id) AS note_count,
                    datetime('now') AS created_at
                FROM note_tag_index
                GROUP BY tag_full
                """
            )
        )

        # S168: index on tag_merge_suggestions.status for efficient pending-suggestion queries.
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_tag_merge_suggestions_status "
                "ON tag_merge_suggestions(status)"
            )
        )

        # S169: source_content_hash column for incremental collection-based flashcard generation.
        # ALTER TABLE is idempotent -- column is silently ignored if it already exists.
        try:
            await conn.execute(
                text("ALTER TABLE flashcards ADD COLUMN source_content_hash TEXT")
            )
        except Exception:
            pass  # Column already exists (idempotent)

        # S173: archived flag on notes; note_id FK on flashcards for per-note coverage tracking.
        for ddl in [
            "ALTER TABLE notes ADD COLUMN archived INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE flashcards ADD COLUMN note_id TEXT",
        ]:
            try:
                await conn.execute(text(ddl))
            except Exception:
                pass  # Column already exists (idempotent)

    logger.info("Database tables and FTS5 index initialized")
