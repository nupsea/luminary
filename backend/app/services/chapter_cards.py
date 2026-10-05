"""Writing a chapter's cards, and the ingestion job that writes a document's first chapters (#231).

Ingestion writes only the first INGEST_CHAPTERS chapters, so a book is practisable when the
reader starts it without hours of generation up front; `chapter_backfill` writes the rest as
the reader moves through it. Cards are stored in fsrs_state 'held' with no due date, so they
add nothing to the review queue until their chapter is practised. Every written chapter is
recorded, so an interrupted job resumes and no chapter is written twice.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import FlashcardModel
from app.repos.document_repo import DocumentRepo
from app.repos.flashcard_repo import FlashcardRepo
from app.repos.graph_entity_repo import GraphEntityRepo
from app.services.chapters import Chapter, chapters_for_document
from app.services.embedder import get_embedding_service
from app.services.flashcard_chapter import ChapterCard, Passage, write_chapter_cards
from app.services.flashcard_factuality import FACTUALITY_UNCHECKED
from app.services.flashcard_parsers import grounding_state
from app.services.flashcard_search import _sync_flashcard_fts

logger = logging.getLogger(__name__)

HELD = "held"
# Names the document's own entity graph holds may appear in a question though its window
# does not show them ("the Time Traveller" in a chapter that only says "I").
KNOWN_NAMES = 40
# A reader opening a new book reaches the end of chapter 1 first; the second is written ahead
# so the prompt at that chapter's end has cards even if the backfill has not run yet.
INGEST_CHAPTERS = 2


async def _known_names(document_id: str, session: AsyncSession) -> str:
    entities = await GraphEntityRepo(session).entities_for_document(document_id)
    top = sorted(entities, key=lambda e: e.mention_count or 0, reverse=True)[:KNOWN_NAMES]
    return " ".join(e.name for e in top)


def _card_row(document_id: str, chapter: Chapter, card: ChapterCard, now: datetime):
    window = card.window
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=document_id,
        chunk_id=window.chunk_ids[0],
        question=card.question,
        answer=card.answer,
        source_excerpt=card.source_excerpt,
        fsrs_state=HELD,
        due_date=None,
        created_at=now,
        section_heading=chapter.title[:300],
        chapter_id=chapter.id,
        grounding=grounding_state(card.source_excerpt, " ".join(window.units)),
        factuality=FACTUALITY_UNCHECKED,
        source_chunk_ids=list(window.chunk_ids),
    )


async def write_chapter(
    document_id: str, book: str, chapter: Chapter, known_names: str, session: AsyncSession
) -> int:
    from app.services.flashcard import get_llm_service  # noqa: PLC0415

    rows = await DocumentRepo(session).chunks_with_headings(chapter.section_ids)
    passages = [Passage(chunk.id, chunk.text, heading) for chunk, heading in rows]
    cards = await write_chapter_cards(
        get_llm_service(),
        None,  # background routing picks the on-device model
        get_embedding_service().encode,
        book=book,
        passages=passages,
        known_names=known_names,
        document_id=document_id,
    )
    now = datetime.now(UTC)
    for card in cards:
        row = _card_row(document_id, chapter, card, now)
        session.add(row)
        await _sync_flashcard_fts(row, session)
    await FlashcardRepo(session).record_chapter_written(document_id, chapter.id, len(cards))
    await session.commit()
    logger.info(
        "chapter_cards: doc=%s chapter %d %r chars=%d cards=%d",
        document_id,
        chapter.order + 1,
        chapter.title[:60],
        chapter.chars,
        len(cards),
    )
    return len(cards)


async def chapter_cards_handler(document_id: str, job_id: str) -> None:
    """Enrichment handler for job_type='chapter_cards': the document's first chapters."""
    async with get_session_factory()() as session:
        doc = await DocumentRepo(session).get_or_404(document_id)
        chapters = await chapters_for_document(document_id, doc.title, session)
        done = await FlashcardRepo(session).chapters_written(document_id)
        known_names = await _known_names(document_id, session)
        for chapter in chapters[:INGEST_CHAPTERS]:
            if chapter.id not in done:
                await write_chapter(document_id, doc.title, chapter, known_names, session)
