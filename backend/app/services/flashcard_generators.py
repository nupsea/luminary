"""Standalone flashcard generators (one async function per source).

Each function is a complete generation pipeline: fetch source content,
call the LLM with the appropriate prompt, parse, persist, and return the
created FlashcardModel rows. ``FlashcardService`` thin-delegates to these
so callers see no API change.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, DocumentModel, FlashcardModel, SectionModel
from app.services.flashcard_parsers import (
    _build_cloze_question,
    _parse_cloze_llm_response,
    _parse_cloze_text,
    _parse_llm_response,
)
from app.services.flashcard_prompts import (
    CLOZE_SYSTEM,
    CLOZE_USER_TMPL,
    TECH_FLASHCARD_SYSTEM,
    TECH_FLASHCARD_USER_TMPL,
)
from app.services.flashcard_search import _sync_flashcard_fts
from app.telemetry import trace_chain

logger = logging.getLogger(__name__)


def _get_llm_service():
    """Indirect through ``app.services.flashcard`` so test patches on
    ``app.services.flashcard.get_llm_service`` are honored when callers
    invoke through these module-level generators.
    """
    from app.services import flashcard as _flashcard  # noqa: PLC0415

    return _flashcard.get_llm_service()


def _generation_model() -> str | None:
    from app.config import get_settings  # noqa: PLC0415

    m = get_settings().LITELLM_GENERATION_MODEL
    return m if m else None


async def generate_technical(
    document_id: str,
    scope: Literal["full", "section"],
    section_heading: str | None,
    count: int,
    session: AsyncSession,
) -> list[FlashcardModel]:
    """Generate Bloom's-taxonomy-typed flashcards for tech_book/tech_article documents.

    Uses TECH_FLASHCARD_SYSTEM exclusively. Stores flashcard_type and bloom_level
    on every generated card.
    """
    from app.services.flashcard import _build_text, _fetch_chunks  # noqa: PLC0415

    llm = _get_llm_service()

    doc_result = await session.execute(
        select(DocumentModel).where(DocumentModel.id == document_id)
    )
    doc = doc_result.scalar_one_or_none()
    content_type = doc.content_type if doc else "unknown"

    chunks = await _fetch_chunks(document_id, scope, section_heading, session, content_type)
    if not chunks:
        return []

    has_code = any(c.has_code for c in chunks)
    admonition_type: str | None = None
    if scope == "section" and section_heading:
        sec_result = await session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .where(SectionModel.heading == section_heading)
            .limit(1)
        )
        sec = sec_result.scalar_one_or_none()
        if sec:
            admonition_type = sec.admonition_type

    combined_text, first_chunk_id = _build_text(chunks)
    if not combined_text:
        return []

    prompt = TECH_FLASHCARD_USER_TMPL.format(
        count=count,
        section_heading=section_heading or "(none)",
        has_code=str(has_code),
        admonition_type=admonition_type or "(none)",
        text=combined_text,
    )

    await session.commit()  # Release read locks to prevent WAL deadlocks during LLM call

    with trace_chain(
        "flashcard.generate_technical",
        input_value=f"doc={document_id} scope={scope} count={count}",
    ) as span:
        span.set_attribute("flashcard.document_id", document_id)
        span.set_attribute("flashcard.scope", scope)
        span.set_attribute("flashcard.requested_count", count)
        span.set_attribute("flashcard.mode", "technical")

        raw = await llm.generate(
            prompt, system=TECH_FLASHCARD_SYSTEM,
            model=_generation_model(), stream=False,
        )
        cards_data = _parse_llm_response(raw, document_id)
        span.set_attribute("flashcard.generated_count", len(cards_data))

    now = datetime.now(UTC)
    flashcards: list[FlashcardModel] = []
    for item in cards_data:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        source_excerpt = str(item.get("source_excerpt", "")).strip()
        flashcard_type = str(item.get("flashcard_type", "definition")).strip()
        raw_bloom = item.get("bloom_level")
        # Coerce bloom_level defensively: LLM may return int, float, or "4" string
        if isinstance(raw_bloom, (int, float)):
            bloom_level: int | None = int(raw_bloom)
        elif isinstance(raw_bloom, str) and raw_bloom.isdigit():
            bloom_level = int(raw_bloom)
        else:
            bloom_level = None
        if not question or not answer:
            continue
        card = FlashcardModel(
            id=str(uuid.uuid4()),
            document_id=document_id,
            chunk_id=first_chunk_id,
            question=question,
            answer=answer,
            source_excerpt=source_excerpt,
            difficulty="medium",
            fsrs_state="new",
            fsrs_stability=0.0,
            fsrs_difficulty=0.0,
            due_date=now,
            reps=0,
            lapses=0,
            created_at=now,
            flashcard_type=flashcard_type,
            bloom_level=bloom_level,
        )
        session.add(card)
        await _sync_flashcard_fts(card, session)
        flashcards.append(card)

    if flashcards:
        await session.commit()
        for card in flashcards:
            await session.refresh(card)

    return flashcards


async def generate_cloze(
    section_id: str,
    count: int,
    session: AsyncSession,
) -> list[FlashcardModel]:
    """Generate cloze deletion flashcards for a section.

    Prompts the LLM to produce {{term}} fill-in-the-blank sentences.
    Validates that each card has at least one blank. Retries once if the
    first response contains zero valid cards. Cards whose cloze_text has
    no {{}} markers are skipped.

    question = cloze_text with {{term}} replaced by [____] (for list views)
    answer = comma-separated terms from the blanks
    cloze_text = raw {{term}} text for frontend rendering
    """
    from app.services.flashcard import _build_text  # noqa: PLC0415

    llm = _get_llm_service()

    chunk_result = await session.execute(
        select(ChunkModel)
        .where(ChunkModel.section_id == section_id)
        .order_by(ChunkModel.chunk_index)
    )
    chunks = list(chunk_result.scalars().all())
    if not chunks:
        return []

    document_id = chunks[0].document_id
    first_chunk_id = chunks[0].id

    combined_text, _ = _build_text(chunks)
    if not combined_text:
        return []

    prompt = CLOZE_USER_TMPL.format(count=count, text=combined_text)

    await session.commit()  # Release read locks to prevent WAL deadlocks during LLM call

    with trace_chain(
        "flashcard.generate_cloze",
        input_value=f"section={section_id} count={count}",
    ) as span:
        span.set_attribute("flashcard.section_id", section_id)
        span.set_attribute("flashcard.requested_count", count)
        span.set_attribute("flashcard.mode", "cloze")

        raw = await llm.generate(
            prompt, system=CLOZE_SYSTEM,
            model=_generation_model(), stream=False,
        )
        items = _parse_cloze_llm_response(raw)

        if not items:
            logger.warning(
                "generate_cloze: no valid cards on first attempt for section=%s, retrying",
                section_id,
            )
            raw2 = await llm.generate(
                prompt, system=CLOZE_SYSTEM,
                model=_generation_model(), stream=False,
            )
            items = _parse_cloze_llm_response(raw2)

        span.set_attribute("flashcard.generated_count", len(items))

    now = datetime.now(UTC)
    flashcards: list[FlashcardModel] = []
    for item in items:
        cloze_text = str(item.get("cloze_text", "")).strip()
        source_excerpt = str(item.get("source_excerpt", "")).strip()
        blanks = _parse_cloze_text(cloze_text)
        if not blanks:
            continue
        question = _build_cloze_question(cloze_text)
        answer = ", ".join(blanks)
        card = FlashcardModel(
            id=str(uuid.uuid4()),
            document_id=document_id,
            chunk_id=first_chunk_id,
            source="document",
            deck="default",
            question=question,
            answer=answer,
            source_excerpt=source_excerpt,
            difficulty="medium",
            is_user_edited=False,
            fsrs_state="new",
            fsrs_stability=0.0,
            fsrs_difficulty=0.0,
            due_date=now,
            reps=0,
            lapses=0,
            created_at=now,
            flashcard_type="cloze",
            bloom_level=None,
            cloze_text=cloze_text,
        )
        session.add(card)
        await _sync_flashcard_fts(card, session)
        flashcards.append(card)

    if flashcards:
        await session.commit()
        for card in flashcards:
            await session.refresh(card)

    return flashcards
