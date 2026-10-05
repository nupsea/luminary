"""The enrichment job that writes each chapter's cards once a document is readable (#231).

Cards are stored in fsrs_state 'held' with no due date, so ingesting a 30-chapter book adds
nothing to the review queue; a chapter's cards are scheduled when that chapter is practised.
A chapter that already has cards is skipped, so a job interrupted mid-book resumes where it
stopped instead of writing the early chapters twice.
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
    from app.services.flashcard_generators import _generation_model  # noqa: PLC0415

    rows = await DocumentRepo(session).chunks_with_headings(chapter.section_ids)
    passages = [Passage(chunk.id, chunk.text, heading) for chunk, heading in rows]
    cards = await write_chapter_cards(
        get_llm_service(),
        _generation_model(),
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
    await session.commit()
    return len(cards)


async def chapter_cards_handler(document_id: str, job_id: str) -> None:
    """Enrichment handler for job_type='chapter_cards'."""
    async with get_session_factory()() as session:
        doc = await DocumentRepo(session).get_or_404(document_id)
        chapters = await chapters_for_document(document_id, doc.title, session)
        done = await FlashcardRepo(session).chapter_ids_with_cards(document_id)
        known_names = await _known_names(document_id, session)
        for chapter in chapters:
            if chapter.id in done:
                continue
            written = await write_chapter(document_id, doc.title, chapter, known_names, session)
            logger.info(
                "chapter_cards: doc=%s chapter=%d/%d %r cards=%d",
                document_id,
                chapter.order + 1,
                len(chapters),
                chapter.title[:60],
                written,
            )
