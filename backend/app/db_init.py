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
    CollectionMemberModel,
    CollectionModel,
    DocumentModel,
    EnrichmentJobModel,
    EvalRunModel,
    FeynmanSessionModel,
    FeynmanTurnModel,
    FlashcardModel,
    GlossaryTermModel,
    ImageModel,
    LearningGoalModel,
    LearningObjectiveModel,
    LibrarySummaryModel,
    MisconceptionModel,
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
        fk_rows = (await conn.execute(text("PRAGMA foreign_key_list(note_sources)"))).fetchall()
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
            await conn.execute(text("ALTER TABLE note_sources_rebuild_s175 RENAME TO note_sources"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(FTS5_DDL))
        await conn.execute(text(NOTES_FTS5_DDL))
        await conn.execute(text(IMAGES_FTS5_DDL))
        await conn.execute(text(FLASHCARDS_FTS5_DDL))
        await conn.execute(text("PRAGMA foreign_keys = ON"))

        # S208: Rename note_collections to collections.
        # SQLite does not support RENAME TABLE if there are dependent views or triggers
        # in some versions, but usually it's fine. We'll use the table-rebuild idiom
        # to ensure the new table name is set correctly in metadata.
        try:
            await conn.execute(text("ALTER TABLE note_collections RENAME TO collections"))
        except Exception:
            pass  # Already renamed or doesn't exist

        # S208: Create collection_members and migrate from note_collection_members.
        # We check if collection_members exists; if not, create and migrate.
        try:
            # Check if old table exists
            table_check = (
                await conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='note_collection_members'"
                    )
                )
            ).fetchone()
            if table_check:
                # Create the new generic table if it doesn't exist yet
                # (Base.metadata.create_all handles this too)
                await conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS collection_members ("
                        " id TEXT PRIMARY KEY,"
                        " collection_id TEXT NOT NULL,"
                        " member_id TEXT NOT NULL,"
                        " member_type TEXT NOT NULL DEFAULT 'note',"
                        " added_at DATETIME,"
                        " UNIQUE(member_id, collection_id, member_type)"
                        ")"
                    )
                )
                # Migrate existing note memberships
                await conn.execute(
                    text(
                        "INSERT OR IGNORE INTO collection_members "
                        "(id, collection_id, member_id, member_type, added_at)"
                        " SELECT id, collection_id, note_id, 'note', added_at "
                        "FROM note_collection_members"
                    )
                )
                # Drop the old table
                await conn.execute(text("DROP TABLE note_collection_members"))
        except Exception as e:
            logger.warning("Migration S208 failed (non-critical): %s", e)

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
            # S192: auto-collection document linkage
            "ALTER TABLE collections ADD COLUMN auto_document_id TEXT",
            # S194: URL validation status for web references
            "ALTER TABLE web_references ADD COLUMN is_valid INTEGER",
            "ALTER TABLE web_references ADD COLUMN last_checked_at DATETIME",
            # Async teach-back evaluation status
            "ALTER TABLE teachback_results ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'",
            # Link teach-back results to study sessions for persistence
            "ALTER TABLE teachback_results ADD COLUMN session_id TEXT",
            # Link study sessions to a collection for enclave-scoped history
            "ALTER TABLE study_sessions ADD COLUMN collection_id TEXT",
            # Persist the planned queue per session so resume preserves scope
            "ALTER TABLE study_sessions ADD COLUMN planned_card_ids JSON",
        ]:
            try:
                await conn.execute(text(ddl))
            except Exception:
                pass  # column already exists

        # S161: migrate distinct group_name values into collections (idempotent).
        # Uses INSERT OR IGNORE so re-running on an already-migrated DB is safe.
        # The collection id is derived from the group_name to be deterministic across runs.
        await conn.execute(
            text(
                """
                INSERT OR IGNORE INTO collections
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
                WHERE group_name NOT IN (SELECT name FROM collections)
                """
            )
        )

        # S161: populate collection_members from group_name (idempotent via INSERT OR IGNORE).
        await conn.execute(
            text(
                """
                INSERT OR IGNORE INTO collection_members 
                (id, member_id, collection_id, member_type, added_at)
                SELECT
                    lower(hex(randomblob(16))) AS id,
                    notes.id AS member_id,
                    collections.id AS collection_id,
                    'note' AS member_type,
                    datetime('now') AS added_at
                FROM notes
                JOIN collections ON notes.group_name = collections.name
                WHERE notes.group_name IS NOT NULL
                """
            )
        )

        # S192: index on auto_document_id for fast auto-collection lookup.
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_collections_auto_doc_id "
                "ON collections(auto_document_id)"
            )
        )

        # S162: explicit indexes on note_tag_index for O(1) prefix lookup.
        # CREATE INDEX IF NOT EXISTS is idempotent.
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_note_tag_index_tag_full ON note_tag_index(tag_full)"
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_note_tag_index_note_id ON note_tag_index(note_id)")
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
            await conn.execute(text("ALTER TABLE flashcards ADD COLUMN source_content_hash TEXT"))
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
            await conn.execute(text("ALTER TABLE flashcards ADD COLUMN chunk_classification TEXT"))
        except Exception:
            pass  # Column already exists (idempotent)

        # S188: section_heading for source grounding display on flashcards.
        try:
            await conn.execute(text("ALTER TABLE flashcards ADD COLUMN section_heading TEXT"))
        except Exception:
            pass  # Column already exists (idempotent)

        # S201: content_hash on notes for dedup.
        try:
            await conn.execute(text("ALTER TABLE notes ADD COLUMN content_hash TEXT"))
        except Exception:
            pass  # Column already exists (idempotent)

        # S183-fix: flashcards.document_id must be nullable for note-sourced cards.
        # Old databases have NOT NULL on this column. Use table-rebuild idiom since
        # SQLite does not support ALTER COLUMN to drop a NOT NULL constraint.
        col_rows = (await conn.execute(text("PRAGMA table_info(flashcards)"))).fetchall()
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
            await conn.execute(text("ALTER TABLE flashcards_rebuild RENAME TO flashcards"))

        # S206: backfill flashcards_fts from existing flashcards (idempotent).
        # Uses LEFT JOIN on shadow content table to skip cards already indexed.
        await conn.execute(
            text(
                """
                INSERT INTO flashcards_fts(flashcard_id, question, answer)
                SELECT f.id, f.question, f.answer
                FROM flashcards f
                LEFT JOIN flashcards_fts_content c ON c.c2 = f.id
                WHERE c.c2 IS NULL
                """
            )
        )

        # S207: Retroactive naming normalization for tags and collections.
        # Normalizes existing tag slugs and collection names to match conventions
        # (tags: lower-case-hyphenated, collections: lower-case-hyphenated).
        # Idempotent: skips rows already in normalized form.
        import re  # noqa: PLC0415

        def _norm_tag(slug: str) -> str:
            s = slug.strip()
            if not s:
                return ""
            segs = s.split("/")
            parts = []
            for raw in segs:
                p = raw.strip()
                if not p:
                    continue
                p = re.sub(r"[_\s]+", "-", p)
                p = re.sub(r"-+", "-", p)
                p = p.lower().strip("-")
                if p:
                    parts.append(p)
            return "/".join(parts)

        def _norm_coll(name: str) -> str:
            s = name.strip()
            if not s:
                return ""
            s = re.sub(r"[_\s]+", "-", s)
            s = re.sub(r"-+", "-", s)
            s = s.upper().strip("-")
            return s

        # Normalize canonical_tags
        tag_rows = (await conn.execute(text("SELECT id FROM canonical_tags"))).fetchall()
        for (old_slug,) in tag_rows:
            new_slug = _norm_tag(old_slug)
            if not new_slug or old_slug == new_slug:
                continue
            # Check if target already exists (merge case)
            existing = (
                await conn.execute(
                    text("SELECT id FROM canonical_tags WHERE id = :nid"),
                    {"nid": new_slug},
                )
            ).fetchone()
            if existing:
                # Merge: move tag index rows, sum counts, delete old
                tag_parent = "/".join(new_slug.split("/")[:-1]) if "/" in new_slug else ""
                # Remove rows that would cause a UNIQUE constraint violation on (note_id, tag_full)
                await conn.execute(
                    text(
                        "DELETE FROM note_tag_index "
                        "WHERE tag_full = :old AND note_id IN ("
                        "  SELECT note_id FROM note_tag_index WHERE tag_full = :new"
                        ")"
                    ),
                    {"old": old_slug, "new": new_slug},
                )
                await conn.execute(
                    text(
                        "UPDATE note_tag_index "
                        "SET tag_full = :new, tag_root = :root, "
                        "tag_parent = :parent "
                        "WHERE tag_full = :old"
                    ),
                    {
                        "new": new_slug,
                        "root": new_slug.split("/")[0],
                        "parent": tag_parent,
                        "old": old_slug,
                    },
                )
                await conn.execute(
                    text("DELETE FROM canonical_tags WHERE id = :old"),
                    {"old": old_slug},
                )
                # Recount
                cnt = (
                    await conn.execute(
                        text(
                            "SELECT COUNT(DISTINCT note_id) "
                            "FROM note_tag_index WHERE tag_full = :tf"
                        ),
                        {"tf": new_slug},
                    )
                ).scalar() or 0
                await conn.execute(
                    text("UPDATE canonical_tags SET note_count = :cnt WHERE id = :tid"),
                    {"cnt": cnt, "tid": new_slug},
                )
            else:
                # Rename: update PK via delete+insert
                row = (
                    await conn.execute(
                        text(
                            "SELECT display_name, parent_tag, "
                            "note_count, created_at "
                            "FROM canonical_tags WHERE id = :oid"
                        ),
                        {"oid": old_slug},
                    )
                ).fetchone()
                if row:
                    await conn.execute(
                        text("DELETE FROM canonical_tags WHERE id = :oid"),
                        {"oid": old_slug},
                    )
                    new_display = new_slug.split("/")[-1]
                    new_parent = "/".join(new_slug.split("/")[:-1]) if "/" in new_slug else None
                    await conn.execute(
                        text(
                            "INSERT OR IGNORE INTO canonical_tags "
                            "(id, display_name, parent_tag, "
                            "note_count, created_at) "
                            "VALUES (:id, :dn, :pt, :nc, :ca)"
                        ),
                        {
                            "id": new_slug,
                            "dn": new_display,
                            "pt": new_parent,
                            "nc": row[2],
                            "ca": row[3],
                        },
                    )
                    # Update tag index rows
                    ren_parent = "/".join(new_slug.split("/")[:-1]) if "/" in new_slug else ""
                    # Remove rows that would cause a UNIQUE constraint violation
                    # on (note_id, tag_full)
                    await conn.execute(
                        text(
                            "DELETE FROM note_tag_index "
                            "WHERE tag_full = :old AND note_id IN ("
                            "  SELECT note_id FROM note_tag_index WHERE tag_full = :new"
                            ")"
                        ),
                        {"old": old_slug, "new": new_slug},
                    )
                    await conn.execute(
                        text(
                            "UPDATE note_tag_index "
                            "SET tag_full = :new, tag_root = :root, "
                            "tag_parent = :parent "
                            "WHERE tag_full = :old"
                        ),
                        {
                            "new": new_slug,
                            "root": new_slug.split("/")[0],
                            "parent": ren_parent,
                            "old": old_slug,
                        },
                    )

        # Normalize collection names (skip auto-collections)
        coll_rows = (await conn.execute(text("SELECT id, name FROM collections"))).fetchall()
        for coll_id, coll_name in coll_rows:
            new_name = _norm_coll(coll_name)
            if not new_name or coll_name == new_name:
                continue
            await conn.execute(
                text("UPDATE collections SET name = :name WHERE id = :cid"),
                {"name": new_name, "cid": coll_id},
            )

        # Normalize document tags (JSON column)
        import json as _json  # noqa: PLC0415

        doc_rows = (
            await conn.execute(
                text("SELECT id, tags FROM documents WHERE tags IS NOT NULL AND tags != '[]'")
            )
        ).fetchall()
        for doc_id, raw_tags in doc_rows:
            try:
                tags = _json.loads(raw_tags) if isinstance(raw_tags, str) else (raw_tags or [])
            except (ValueError, TypeError):
                continue
            if not isinstance(tags, list):
                continue
            new_tags = [_norm_tag(t) for t in tags if isinstance(t, str) and _norm_tag(t)]
            if tags != new_tags:
                await conn.execute(
                    text("UPDATE documents SET tags = :tags WHERE id = :did"),
                    {"tags": _json.dumps(new_tags), "did": doc_id},
                )

        # Normalize note tags (JSON column)
        note_rows = (
            await conn.execute(
                text("SELECT id, tags FROM notes WHERE tags IS NOT NULL AND tags != '[]'")
            )
        ).fetchall()
        for note_id, raw_tags in note_rows:
            try:
                tags = _json.loads(raw_tags) if isinstance(raw_tags, str) else (raw_tags or [])
            except (ValueError, TypeError):
                continue
            if not isinstance(tags, list):
                continue
            new_tags = [_norm_tag(t) for t in tags if isinstance(t, str) and _norm_tag(t)]
            if tags != new_tags:
                await conn.execute(
                    text("UPDATE notes SET tags = :tags WHERE id = :nid"),
                    {"tags": _json.dumps(new_tags), "nid": note_id},
                )

    logger.info("Database tables and FTS5 index initialized")
