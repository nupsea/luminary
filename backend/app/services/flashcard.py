"""Flashcard generation service — LLM-based QA flashcard generation."""

import json
import logging
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, FlashcardModel, SectionModel
from app.services.llm import get_llm_service

logger = logging.getLogger(__name__)

FLASHCARD_SYSTEM = (
    "You are a flashcard generator. "
    "Output only valid JSON, no preamble, no markdown code fences."
)

FLASHCARD_USER_TMPL = (
    "Generate {count} question-answer flashcard pairs from the following text. "
    "Each card must be answerable only from this specific content. "
    'Output JSON array: [{{"question": str, "answer": str, "source_excerpt": str}}]. '
    "Output only JSON.\n\nText:\n{text}"
)

_CHUNK_CHAR_LIMIT = 32_000


async def _fetch_chunks(
    document_id: str,
    scope: Literal["full", "section"],
    section_heading: str | None,
    session: AsyncSession,
) -> list[ChunkModel]:
    """Return ordered chunks for the document, filtered by section when scope='section'."""
    if scope == "section" and section_heading:
        sec_result = await session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .where(SectionModel.heading == section_heading)
            .limit(1)
        )
        section = sec_result.scalar_one_or_none()
        if section:
            result = await session.execute(
                select(ChunkModel)
                .where(ChunkModel.document_id == document_id)
                .where(ChunkModel.section_id == section.id)
                .order_by(ChunkModel.chunk_index)
            )
            return list(result.scalars().all())

    result = await session.execute(
        select(ChunkModel)
        .where(ChunkModel.document_id == document_id)
        .order_by(ChunkModel.chunk_index)
    )
    return list(result.scalars().all())


def _build_text(chunks: list[ChunkModel]) -> tuple[str, str]:
    """Build combined text (up to char limit) from chunks.

    Returns (combined_text, first_chunk_id).
    """
    parts: list[str] = []
    total = 0
    for chunk in chunks:
        if total + len(chunk.text) > _CHUNK_CHAR_LIMIT:
            remaining = _CHUNK_CHAR_LIMIT - total
            if remaining > 200:  # noqa: PLR2004
                parts.append(chunk.text[:remaining])
            break
        parts.append(chunk.text)
        total += len(chunk.text)
    return "\n\n".join(parts), chunks[0].id


def _parse_llm_response(raw: str, document_id: str) -> list[dict]:
    """Strip markdown fences and parse JSON array from LLM response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        logger.warning("LLM returned non-list JSON for doc %s", document_id)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Flashcard JSON parse failed for doc %s: %r", document_id, raw[:200])
    return []


class FlashcardService:
    async def generate(
        self,
        document_id: str,
        scope: Literal["full", "section"],
        section_heading: str | None,
        count: int,
        session: AsyncSession,
    ) -> list[FlashcardModel]:
        """Generate flashcards from document chunks using LLM.

        Fetches chunks (all or filtered by section heading), calls LiteLLM,
        parses JSON output, and persists cards in SQLite with fsrs_state='new'.
        """
        llm = get_llm_service()
        chunks = await _fetch_chunks(document_id, scope, section_heading, session)
        if not chunks:
            return []

        combined_text, first_chunk_id = _build_text(chunks)
        if not combined_text:
            return []

        prompt = FLASHCARD_USER_TMPL.format(count=count, text=combined_text)
        raw = await llm.generate(prompt, system=FLASHCARD_SYSTEM, stream=False)
        cards_data = _parse_llm_response(raw, document_id)

        now = datetime.utcnow()
        flashcards: list[FlashcardModel] = []
        for item in cards_data:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            source_excerpt = str(item.get("source_excerpt", "")).strip()
            if not question or not answer:
                continue
            card = FlashcardModel(
                id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_id=first_chunk_id,
                question=question,
                answer=answer,
                source_excerpt=source_excerpt,
                fsrs_state="new",
                fsrs_stability=0.0,
                fsrs_difficulty=0.0,
                due_date=now,
                reps=0,
                lapses=0,
                created_at=now,
            )
            session.add(card)
            flashcards.append(card)

        if flashcards:
            await session.commit()
            for card in flashcards:
                await session.refresh(card)

        return flashcards


_flashcard_service: FlashcardService | None = None


def get_flashcard_service() -> FlashcardService:
    global _flashcard_service  # noqa: PLW0603
    if _flashcard_service is None:
        _flashcard_service = FlashcardService()
    return _flashcard_service
