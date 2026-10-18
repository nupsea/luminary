"""Flashcard search: an FTS5 match, falling back to a substring match when it finds nothing."""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FlashcardModel
from app.repos.flashcard_repo import FlashcardRepo

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


class FlashcardSearchService:
    """FTS5 + filter search over flashcards"""

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
        section_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FlashcardModel], int]:
        """Search flashcards with optional FTS query and structured filters

        All filters combine with AND. Returns (cards, total_count).
        """
        repo = FlashcardRepo(session)
        filters = {
            "document_id": document_id,
            "collection_id": collection_id,
            "tag": tag,
            "bloom_level_min": bloom_level_min,
            "bloom_level_max": bloom_level_max,
            "fsrs_state": fsrs_state,
            "flashcard_type": flashcard_type,
            "section_id": section_id,
            "page": page,
            "page_size": page_size,
        }
        raw = query.strip() if query else ""
        match = _sanitize_fts5_query(raw) if raw else ""
        if not match:
            return await repo.search(like=raw or None, **filters)

        cards, total = await repo.search(fts_match=match, **filters)
        if total:
            return cards, total
        cards, total = await repo.search(like=raw, **filters)
        if total:
            logger.info("flashcard.search: FTS5 returned 0, LIKE fallback found %d", total)
        return cards, total
