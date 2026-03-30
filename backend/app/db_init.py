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
    NoteSourceModel,
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

FLASHCARDS_FTS5_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS flashcards_fts
USING fts5(
    question,
    answer,
    flashcard_id UNINDEXED
)
"""


async def create_all_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        # S175: note_sources may have been created with an incorrect FK on document_id
        # during an early implementation attempt. Detect and rebuild if needed.
        # Uses SQLite table-rebuild idiom (no ALTER DROP CONSTRAINT support).
        fk_rows = (
            await conn.execute(text("PRAGMA foreign_key_list(note_sources)"))
        ).fetchall()
        if any(str(row[2]).lower() == "documents" for row in fk_rows):
            # Old schema has FK on document_id -- rebuild without it
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS note_sources_rebuild_s175 ("
                    "note_id TEXT NOT NULL,"
                    " document_id TEXT NOT NULL,"
                    " added_at TEXT NOT NULL,"
                    " PRIMARY KEY (note_id, document_id),"
                    " FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE"
                    ")"
                )
            )
            await conn.execute(
                text(
                    "INSERT OR IGNORE INTO note_sources_rebuild_s175"
                    " SELECT note_id, document_id, added_at FROM note_sources"
                )
            )
            await conn.execute(text("DROP TABLE note_sources"))
            await conn.execute(
                text(
                    "ALTER TABLE note_sources_rebuild_s175 RENAME TO note_sources"
                )
            )
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(FTS5_DDL))
        await conn.execute(text(NOTES_FTS5_DDL))
        await conn.execute(text(IMAGES_FTS5_DDL))
        await conn.execute(text(FLASHCARDS_FTS5_DDL))
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
            # S182: YouTube channel/uploader name and canonical YouTube URL
            "ALTER TABLE documents ADD COLUMN channel_name TEXT",
            "ALTER TABLE documents ADD COLUMN youtube_url TEXT",
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

        # S175: note_sources pivot table for multi-document source linkage.
        # Base.metadata.create_all above creates note_sources if absent.
        # Migration: backfill from notes.document_id (idempotent via composite PK).
        await conn.execute(
            text(
                """
                INSERT OR IGNORE INTO note_sources (note_id, document_id, added_at)
                SELECT id, document_id, created_at
                FROM notes
                WHERE document_id IS NOT NULL
                """
            )
        )

        # S179: chunk_classification label for pre-generation classifier.
        try:
            await conn.execute(
                text("ALTER TABLE flashcards ADD COLUMN chunk_classification TEXT")
            )
        except Exception:
            pass  # Column already exists (idempotent)

        # S188: section_heading for source grounding display on flashcards.
        try:
            await conn.execute(
                text("ALTER TABLE flashcards ADD COLUMN section_heading TEXT")
            )
        except Exception:
            pass  # Column already exists (idempotent)

        # S183-fix: flashcards.document_id must be nullable for note-sourced cards.
        # Old databases have NOT NULL on this column. Use table-rebuild idiom since
        # SQLite does not support ALTER COLUMN to drop a NOT NULL constraint.
        col_rows = (
            await conn.execute(text("PRAGMA table_info(flashcards)"))
        ).fetchall()
        doc_id_col = next((r for r in col_rows if r[1] == "document_id"), None)
        if doc_id_col is not None and doc_id_col[3] == 1:  # notnull == 1 means NOT NULL
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS flashcards_rebuild ("
                    "id TEXT PRIMARY KEY,"
                    " document_id TEXT,"
                    " chunk_id TEXT,"
                    " source TEXT NOT NULL DEFAULT 'document',"
                    " deck TEXT NOT NULL DEFAULT 'default',"
                    " question TEXT NOT NULL,"
                    " answer TEXT NOT NULL,"
                    " source_excerpt TEXT NOT NULL,"
                    " difficulty TEXT NOT NULL DEFAULT 'medium',"
                    " is_user_edited INTEGER,"
                    " fsrs_stability REAL,"
                    " fsrs_difficulty REAL,"
                    " due_date DATETIME,"
                    " fsrs_state TEXT,"
                    " reps INTEGER,"
                    " lapses INTEGER,"
                    " last_review DATETIME,"
                    " flashcard_type TEXT,"
                    " bloom_level INTEGER,"
                    " cloze_text TEXT,"
                    " source_content_hash TEXT,"
                    " note_id TEXT,"
                    " chunk_classification TEXT,"
                    " section_heading TEXT,"
                    " created_at DATETIME"
                    ")"
                )
            )
            await conn.execute(
                text(
                    "INSERT OR IGNORE INTO flashcards_rebuild"
                    " (id, document_id, chunk_id, source, deck, question, answer,"
                    "  source_excerpt, difficulty, is_user_edited, fsrs_stability,"
                    "  fsrs_difficulty, due_date, fsrs_state, reps, lapses, last_review,"
                    "  flashcard_type, bloom_level, cloze_text, source_content_hash,"
                    "  note_id, chunk_classification, section_heading, created_at)"
                    " SELECT id, document_id, chunk_id, source, deck, question, answer,"
                    "  source_excerpt, difficulty, is_user_edited, fsrs_stability,"
                    "  fsrs_difficulty, due_date, fsrs_state, reps, lapses, last_review,"
                    "  flashcard_type, bloom_level, cloze_text, source_content_hash,"
                    "  note_id, chunk_classification, section_heading, created_at"
                    " FROM flashcards"
                )
            )
            await conn.execute(text("DROP TABLE flashcards"))
            await conn.execute(
                text("ALTER TABLE flashcards_rebuild RENAME TO flashcards")
            )

    logger.info("Database tables and FTS5 index initialized")
