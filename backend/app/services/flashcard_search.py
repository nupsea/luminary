"""Flashcard search service and FTS5 sync helpers.

Split from `flashcard.py` to keep search logic separate from generation
strategies. The FlashcardService class inherits from FlashcardSearchService
so existing call sites (`service.search(...)`) continue to work.
"""

import logging
import re

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FlashcardModel

logger = logging.getLogger(__name__)


_FTS5_SPECIAL = re.compile(r'[(){}*:^~"\[\]<>]')


def _sanitize_fts5_query(raw: str) -> str:
    """Strip FTS5 operators and join tokens with AND for multi-word queries.

    Returns empty string if nothing useful remains after sanitization.
    """
    cleaned = _FTS5_SPECIAL.sub(" ", raw)
    tokens = [t for t in cleaned.split() if t.upper() not in ("AND", "OR", "NOT", "NEAR")]
    if not tokens:
        return ""
    return " AND ".join(f'"{t}"' for t in tokens)


async def _sync_flashcard_fts(card: FlashcardModel, session: AsyncSession) -> None:
    """Insert or update a flashcard's question+answer in the FTS5 index.

    FTS5 UNINDEXED columns don't support OR REPLACE semantics.
    Delete any existing row first (via shadow table rowid lookup per I-4),
    then insert the new row.
    """
    row = (
        await session.execute(
            text("SELECT rowid FROM flashcards_fts_content WHERE c2 = :fid"),
            {"fid": card.id},
        )
    ).first()
    if row:
        await session.execute(
            text("DELETE FROM flashcards_fts WHERE rowid = :rid"),
            {"rid": row[0]},
        )
    await session.execute(
        text("INSERT INTO flashcards_fts(flashcard_id, question, answer) VALUES (:fid, :q, :a)"),
        {"fid": card.id, "q": card.question, "a": card.answer},
    )


async def _delete_flashcard_fts(card_id: str, session: AsyncSession) -> None:
    """Delete a flashcard from the FTS5 index using shadow table rowid lookup (I-4 safe)."""
    row = (
        await session.execute(
            text("SELECT rowid FROM flashcards_fts_content WHERE c2 = :fid"),
            {"fid": card_id},
        )
    ).first()
    if row:
        await session.execute(
            text("DELETE FROM flashcards_fts WHERE rowid = :rid"),
            {"rid": row[0]},
        )


class FlashcardSearchService:
    """FTS5 + filter search over flashcards (S184/S206)."""

    async def search(
        self,
        session: AsyncSession,
        query: str | None = None,
        document_id: str | None = None,
        collection_id: str | None = None,
        tag: str | None = None,
        bloom_level_min: int | None = None,
        bloom_level_max: int | None = None,
        fsrs_state: str | None = None,
        flashcard_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FlashcardModel], int]:
        """Search flashcards with optional FTS query and structured filters (S184).

        All filters combine with AND. Returns (cards, total_count).
        """
        from sqlalchemy import or_  # noqa: PLC0415

        from app.models import CollectionMemberModel, NoteTagIndexModel  # noqa: PLC0415

        stmt = select(FlashcardModel)
        _fts_query_used = False
        _raw_query = query.strip() if query else ""

        if _raw_query:
            sanitized = _sanitize_fts5_query(_raw_query)
            if sanitized:
                fts_sub = (
                    select(text("flashcard_id"))
                    .select_from(text("flashcards_fts"))
                    .where(text("flashcards_fts MATCH :q"))
                )
                stmt = stmt.where(FlashcardModel.id.in_(fts_sub)).params(q=sanitized)
                _fts_query_used = True
            else:
                like_pat = f"%{_raw_query}%"
                stmt = stmt.where(
                    or_(
                        FlashcardModel.question.ilike(like_pat),
                        FlashcardModel.answer.ilike(like_pat),
                    )
                )

        if document_id:
            stmt = stmt.where(FlashcardModel.document_id == document_id)

        if collection_id:
            member_sub = select(CollectionMemberModel.member_id).where(
                CollectionMemberModel.collection_id == collection_id,
                CollectionMemberModel.member_type == "note",
            )
            stmt = stmt.where(FlashcardModel.note_id.in_(member_sub))

        if tag:
            tag_sub = select(NoteTagIndexModel.note_id).where(
                or_(
                    NoteTagIndexModel.tag_full == tag,
                    NoteTagIndexModel.tag_full.like(tag + "/%"),
                )
            )
            stmt = stmt.where(FlashcardModel.note_id.in_(tag_sub))

        if bloom_level_min is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level >= bloom_level_min,
            )

        if bloom_level_max is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level <= bloom_level_max,
            )

        if fsrs_state:
            stmt = stmt.where(FlashcardModel.fsrs_state == fsrs_state)

        if flashcard_type:
            stmt = stmt.where(FlashcardModel.flashcard_type == flashcard_type)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar_one()

        # S206: LIKE fallback when FTS5 returns 0 results
        if total == 0 and _fts_query_used and query:
            like_pat = f"%{query.strip()}%"
            stmt_fallback = select(FlashcardModel).where(
                or_(
                    FlashcardModel.question.ilike(like_pat),
                    FlashcardModel.answer.ilike(like_pat),
                )
            )
            if document_id:
                stmt_fallback = stmt_fallback.where(FlashcardModel.document_id == document_id)
            if collection_id:
                member_sub2 = select(CollectionMemberModel.member_id).where(
                    CollectionMemberModel.collection_id == collection_id,
                    CollectionMemberModel.member_type == "note",
                )
                stmt_fallback = stmt_fallback.where(FlashcardModel.note_id.in_(member_sub2))
            if tag:
                tag_sub2 = select(NoteTagIndexModel.note_id).where(
                    or_(
                        NoteTagIndexModel.tag_full == tag,
                        NoteTagIndexModel.tag_full.like(tag + "/%"),
                    )
                )
                stmt_fallback = stmt_fallback.where(FlashcardModel.note_id.in_(tag_sub2))
            if bloom_level_min is not None:
                stmt_fallback = stmt_fallback.where(
                    FlashcardModel.bloom_level.is_not(None),
                    FlashcardModel.bloom_level >= bloom_level_min,
                )
            if bloom_level_max is not None:
                stmt_fallback = stmt_fallback.where(
                    FlashcardModel.bloom_level.is_not(None),
                    FlashcardModel.bloom_level <= bloom_level_max,
                )
            if fsrs_state:
                stmt_fallback = stmt_fallback.where(FlashcardModel.fsrs_state == fsrs_state)
            if flashcard_type:
                stmt_fallback = stmt_fallback.where(FlashcardModel.flashcard_type == flashcard_type)

            count_fb = select(func.count()).select_from(stmt_fallback.subquery())
            total = (await session.execute(count_fb)).scalar_one()
            if total > 0:
                stmt = stmt_fallback
                logger.info("flashcard.search: FTS5 returned 0, LIKE fallback found %d", total)

        stmt = stmt.order_by(FlashcardModel.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(stmt)
        cards = list(result.scalars().all())

        return cards, total
