"""Standalone flashcard generators (one async function per source).

Each function is a complete generation pipeline: fetch source content,
call the LLM with the appropriate prompt, parse, persist, and return the
created FlashcardModel rows. ``FlashcardService`` thin-delegates to these
so callers see no API change.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChunkModel,
    CollectionMemberModel,
    CollectionModel,
    DocumentModel,
    FlashcardModel,
    NoteModel,
    SectionModel,
)
from app.services.flashcard_parsers import (
    _build_cloze_question,
    _parse_cloze_llm_response,
    _parse_cloze_text,
    _parse_concept_extract,
    _parse_llm_response,
)
from app.services.flashcard_prompts import (
    _BLOOM_L3_INSTRUCTION,
    _BOOK_CONTENT_GUIDELINE,
    _DIFFICULTY_GUIDELINES,
    CLOZE_SYSTEM,
    CLOZE_USER_TMPL,
    FLASHCARD_USER_TMPL,
    GRAPH_FLASHCARD_SYSTEM,
    GRAPH_FLASHCARD_USER_TMPL,
    NOTES_CARD_FROM_CONCEPTS_SYSTEM,
    NOTES_CARD_FROM_CONCEPTS_TMPL,
    NOTES_CONCEPT_EXTRACT_SYSTEM,
    NOTES_CONCEPT_EXTRACT_TMPL,
    TECH_FLASHCARD_SYSTEM,
    TECH_FLASHCARD_USER_TMPL,
    _build_genre_system_prompt,
    _infer_genre,
)
from app.services.flashcard_search import _sync_flashcard_fts
from app.services.llm import LLMAPIConnectionError, LLMServiceUnavailableError
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


async def generate(
    document_id: str,
    scope: Literal["full", "section"],
    section_heading: str | None,
    count: int,
    session: AsyncSession,
    difficulty: Literal["easy", "medium", "hard"] = "medium",
    context: str | None = None,
) -> list[FlashcardModel]:
    """Generate flashcards from document chunks using LLM.

    When *context* (selected text) is provided, uses it directly instead of
    fetching chunks -- this produces questions grounded in the exact selection.
    Otherwise fetches chunks (all or filtered by section heading), calls LiteLLM,
    parses JSON output, and persists cards in SQLite with fsrs_state='new'.
    """
    from app.services.flashcard import (  # noqa: PLC0415
        _CHUNK_CHAR_LIMIT,
        _build_enriched_text,
        _build_text,
        _fetch_chunks,
        _fetch_existing_embeddings,
        _filter_chunks_by_classification,
        _get_entity_names_for_document,
        _get_section_context_for_chunks,
        _is_near_duplicate,
        _resolve_section_heading,
    )

    llm = _get_llm_service()

    doc_result = await session.execute(
        select(DocumentModel).where(DocumentModel.id == document_id)
    )
    doc = doc_result.scalar_one_or_none()
    content_type = doc.content_type if doc else "unknown"

    # S179: infer genre for genre-aware system prompt
    genre = _infer_genre(doc)
    system_prompt = _build_genre_system_prompt(genre)

    # When the caller supplies selected text, use it directly (bypass classifier).
    chunk_classification: str | None = None
    section_ctx: dict[str, tuple[str, str | None]] = {}
    resolved_section_heading: str | None = None
    eligible_chunks: list[ChunkModel] = []
    if context and context.strip():
        combined_text = context.strip()[:_CHUNK_CHAR_LIMIT]
        # Still need a chunk_id (NOT NULL) -- grab the first chunk for the document.
        first_chunk_result = await session.execute(
            select(ChunkModel.id)
            .where(ChunkModel.document_id == document_id)
            .order_by(ChunkModel.chunk_index)
            .limit(1)
        )
        first_chunk_id = first_chunk_result.scalar_one_or_none() or document_id
    else:
        chunks = await _fetch_chunks(document_id, scope, section_heading, session, content_type)
        if not chunks:
            return []

        # S188: look up section headings for context enrichment
        section_ctx = await _get_section_context_for_chunks(chunks, session)

        # S179: classify chunks and filter to concept/definition (+ adjacent elaborators)
        classified = _filter_chunks_by_classification(chunks)
        if classified:
            eligible_chunks = [c for c, _ in classified]
            chunk_classification = classified[0][1]  # dominant label of first chunk
            logger.info(
                "flashcard.generate: %d/%d chunks eligible after classification (genre=%s)",
                len(eligible_chunks),
                len(chunks),
                genre,
            )
        else:
            eligible_chunks = chunks
            logger.info(
                "flashcard.generate: no concept/definition chunks found, using all %d chunks",
                len(chunks),
            )

        if section_ctx:
            combined_text, first_chunk_id = _build_enriched_text(eligible_chunks, section_ctx)
        else:
            combined_text, first_chunk_id = _build_text(eligible_chunks)
        if not combined_text:
            return []

        first_sec = eligible_chunks[0].section_id if eligible_chunks else None
        if first_sec and first_sec in section_ctx:
            resolved_section_heading = _resolve_section_heading(eligible_chunks[0], section_ctx)

    system_prompt += _BLOOM_L3_INSTRUCTION

    extra_instructions = ""
    if content_type == "book":
        extra_instructions = _BOOK_CONTENT_GUIDELINE
        entity_names = await _get_entity_names_for_document(
            document_id, types=["PERSON", "PLACE"], limit=5
        )
        if entity_names:
            names_str = ", ".join(entity_names)
            extra_instructions += (
                f"Key characters and places in this work: {names_str}. "
                "Reference these names directly in questions when relevant.\n"
            )

    is_tech = content_type in ("code", "tech_book", "tech_article")
    has_context = context and context.strip()
    if is_tech and not has_context:
        code_chunks = [c for c in eligible_chunks if c.has_code]
        if code_chunks:
            code_excerpts = "\n\n".join(c.text[:1000] for c in code_chunks[:3])
            extra_instructions += (
                f"Code blocks from the document:\n{code_excerpts}\n"
                "Include code examples in questions where appropriate.\n"
            )

    prompt = FLASHCARD_USER_TMPL.format(
        count=count,
        difficulty=difficulty,
        difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
        extra_instructions=extra_instructions,
        text=combined_text,
    )

    await session.commit()  # Release read locks to prevent WAL deadlocks during LLM call

    with trace_chain(
        "flashcard.generate",
        input_value=f"doc={document_id} scope={scope} count={count} difficulty={difficulty}",
    ) as span:
        span.set_attribute("flashcard.document_id", document_id)
        span.set_attribute("flashcard.scope", scope)
        span.set_attribute("flashcard.requested_count", count)
        span.set_attribute("flashcard.difficulty", difficulty)
        if section_heading:
            span.set_attribute("flashcard.section_heading", section_heading)

        raw = await llm.generate(
            prompt, system=system_prompt,
            model=_generation_model(), stream=False,
        )
        cards_data = _parse_llm_response(raw, document_id)
        span.set_attribute("flashcard.generated_count", len(cards_data))

    now = datetime.now(UTC)

    import numpy as np  # noqa: PLC0415

    from app.services.embedder import get_embedding_service  # noqa: PLC0415

    _existing_qs, existing_vecs = await _fetch_existing_embeddings("default", session)

    candidates: list[dict] = []
    for item in cards_data:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        a = str(item.get("answer", "")).strip()
        if q and a:
            candidates.append(item)

    if candidates and existing_vecs is not None:
        try:
            embedder = get_embedding_service()
            cand_texts = [str(c.get("question", "")).strip() for c in candidates]
            cand_vecs = await asyncio.to_thread(embedder.encode, cand_texts)
            cand_vecs = np.array(cand_vecs)
        except Exception:
            logger.warning(
                "Embedding dedup: candidate encode failed; skipping dedup", exc_info=True
            )
            cand_vecs = None
    else:
        cand_vecs = None

    pool_vecs = existing_vecs
    flashcards: list[FlashcardModel] = []
    for i, item in enumerate(candidates):
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        source_excerpt = str(item.get("source_excerpt", "")).strip()
        if cand_vecs is not None and pool_vecs is not None:
            if _is_near_duplicate(cand_vecs[i], pool_vecs):
                logger.info(
                    "flashcard.generate: skipping near-duplicate question: %r",
                    question[:80],
                )
                continue
            pool_vecs = np.vstack([pool_vecs, cand_vecs[i : i + 1]])
        card_bloom_level = item.get("bloom_level")
        if isinstance(card_bloom_level, int) and 1 <= card_bloom_level <= 6:
            pass
        else:
            card_bloom_level = None

        card = FlashcardModel(
            id=str(uuid.uuid4()),
            document_id=document_id,
            chunk_id=first_chunk_id,
            question=question,
            answer=answer,
            source_excerpt=source_excerpt,
            difficulty=difficulty,
            fsrs_state="new",
            fsrs_stability=0.0,
            fsrs_difficulty=0.0,
            due_date=now,
            reps=0,
            lapses=0,
            created_at=now,
            chunk_classification=chunk_classification,
            bloom_level=card_bloom_level,
            section_heading=resolved_section_heading,
        )
        session.add(card)
        await _sync_flashcard_fts(card, session)
        flashcards.append(card)

    if flashcards:
        await session.commit()
        for card in flashcards:
            await session.refresh(card)

    return flashcards


async def generate_from_notes(
    tag: str | None,
    note_ids: list[str] | None,
    count: int,
    session: AsyncSession,
    difficulty: Literal["easy", "medium", "hard"] = "medium",
) -> list[FlashcardModel]:
    """Generate flashcards from user notes scoped by tag or explicit note IDs."""
    from app.services.flashcard import _CHUNK_CHAR_LIMIT  # noqa: PLC0415

    if not tag and not note_ids:
        raise ValueError("Must provide tag or note_ids")

    llm = _get_llm_service()

    if note_ids:
        result = await session.execute(select(NoteModel).where(NoteModel.id.in_(note_ids)))
        notes = list(result.scalars().all())
    else:
        result = await session.execute(
            select(NoteModel).where(
                text(
                    "EXISTS (SELECT 1 FROM json_each(notes.tags) WHERE json_each.value = :tag)"
                ).bindparams(tag=tag)
            )
        )
        notes = list(result.scalars().all())

    if not notes:
        return []

    combined_text = "\n\n".join(n.content for n in notes)[:_CHUNK_CHAR_LIMIT]
    if not combined_text:
        return []

    extract_prompt = NOTES_CONCEPT_EXTRACT_TMPL.format(
        max_concepts=max(count, 8),
        text=combined_text,
    )

    await session.commit()  # Release read locks to prevent WAL deadlocks during LLM call

    with trace_chain(
        "flashcard.generate_from_notes",
        input_value=f"tag={tag} note_ids={note_ids} count={count} difficulty={difficulty}",
    ) as span:
        span.set_attribute("flashcard.source", "note")
        span.set_attribute("flashcard.requested_count", count)
        span.set_attribute("flashcard.difficulty", difficulty)

        raw_concepts = await llm.generate(
            extract_prompt,
            system=NOTES_CONCEPT_EXTRACT_SYSTEM,
            model=_generation_model(), stream=False,
        )
        domain, concepts = _parse_concept_extract(raw_concepts)
        concepts = concepts[:count]

        if not concepts:
            return []

        card_prompt = NOTES_CARD_FROM_CONCEPTS_TMPL.format(
            domain=domain,
            difficulty=difficulty,
            difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
            concepts_json=json.dumps(concepts, ensure_ascii=False),
            text=combined_text,
        )
        raw = await llm.generate(
            card_prompt,
            system=NOTES_CARD_FROM_CONCEPTS_SYSTEM,
            model=_generation_model(), stream=False,
        )
        cards_data = _parse_llm_response(raw, "notes")
        span.set_attribute("flashcard.generated_count", len(cards_data))

    now = datetime.now(UTC)
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
            document_id=None,
            chunk_id=None,
            source="note",
            question=question,
            answer=answer,
            source_excerpt=source_excerpt,
            difficulty=difficulty,
            fsrs_state="new",
            fsrs_stability=0.0,
            fsrs_difficulty=0.0,
            due_date=now,
            reps=0,
            lapses=0,
            created_at=now,
        )
        session.add(card)
        await _sync_flashcard_fts(card, session)
        flashcards.append(card)

    if flashcards:
        await session.commit()
        for card in flashcards:
            await session.refresh(card)

    return flashcards


async def generate_from_collection(
    collection_id: str,
    count_per_note: int,
    difficulty: Literal["easy", "medium", "hard"],
    session: AsyncSession,
    force_regenerate: bool = False,
) -> dict:
    """Generate flashcards for every note in a collection with hash-based deduplication.

    Each note is processed sequentially (I-1: no asyncio.gather with shared session).
    Returns {created: int, skipped: int, deck: str}.
    """
    from app.services.flashcard import _CHUNK_CHAR_LIMIT  # noqa: PLC0415

    llm = _get_llm_service()

    coll_result = await session.execute(
        select(CollectionModel).where(CollectionModel.id == collection_id)
    )
    collection = coll_result.scalar_one_or_none()
    if collection is None:
        raise ValueError(f"Collection {collection_id!r} not found")

    deck_name = collection.name

    member_result = await session.execute(
        select(CollectionMemberModel.member_id).where(
            CollectionMemberModel.collection_id == collection_id,
            CollectionMemberModel.member_type == "note",
        )
    )
    note_ids = [row[0] for row in member_result.all()]

    created = 0
    skipped = 0

    for note_id in note_ids:
        note_result = await session.execute(select(NoteModel).where(NoteModel.id == note_id))
        note = note_result.scalar_one_or_none()
        if note is None or not note.content:
            continue

        content_hash = hashlib.sha256(note.content[:500].encode()).hexdigest()[:16]

        if not force_regenerate:
            count_result = await session.execute(
                select(func.count())
                .select_from(FlashcardModel)
                .where(
                    FlashcardModel.deck == deck_name,
                    FlashcardModel.source == "note",
                    FlashcardModel.source_content_hash == content_hash,
                )
            )
            existing = count_result.scalar_one()
            if existing > 0:
                skipped += 1
                continue

        combined_text = note.content[:_CHUNK_CHAR_LIMIT]

        await session.commit()  # Release read locks to prevent WAL deadlocks during LLM call

        raw_concepts = await llm.generate(
            NOTES_CONCEPT_EXTRACT_TMPL.format(
                max_concepts=max(count_per_note, 8),
                text=combined_text,
            ),
            system=NOTES_CONCEPT_EXTRACT_SYSTEM,
            model=_generation_model(),
            stream=False,
        )
        domain, concepts = _parse_concept_extract(raw_concepts)
        concepts = concepts[:count_per_note]
        if not concepts:
            continue

        raw = await llm.generate(
            NOTES_CARD_FROM_CONCEPTS_TMPL.format(
                domain=domain,
                difficulty=difficulty,
                difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
                concepts_json=json.dumps(concepts, ensure_ascii=False),
                text=combined_text,
            ),
            system=NOTES_CARD_FROM_CONCEPTS_SYSTEM,
            model=_generation_model(),
            stream=False,
        )
        cards_data = _parse_llm_response(raw, note_id)

        now = datetime.now(UTC)
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
                document_id=None,
                chunk_id=None,
                source="note",
                deck=deck_name,
                source_content_hash=content_hash,
                note_id=note_id,
                question=question,
                answer=answer,
                source_excerpt=source_excerpt,
                difficulty=difficulty,
                fsrs_state="new",
                fsrs_stability=0.0,
                fsrs_difficulty=0.0,
                due_date=now,
                reps=0,
                lapses=0,
                created_at=now,
            )
            session.add(card)
            await _sync_flashcard_fts(card, session)
            created += 1

        await session.commit()

    return {"created": created, "skipped": skipped, "deck": deck_name}


async def generate_from_graph(
    document_id: str,
    k: int,
    session: AsyncSession,
    cards_per_pair: int = 1,
) -> list[FlashcardModel]:
    """Generate flashcards from Kuzu entity relationship pairs.

    For each of the top-k entity pairs (by edge weight), fetches shared
    chunk context and calls LiteLLM with a relationship-framing prompt.
    Falls through gracefully when Kuzu is empty or Ollama is unreachable.
    """
    from app.services.flashcard import _CHUNK_CHAR_LIMIT  # noqa: PLC0415
    from app.services.graph import get_graph_service  # noqa: PLC0415

    llm = _get_llm_service()
    graph = get_graph_service()

    pairs_4 = graph.get_related_entity_pairs_for_document(document_id, limit=k)
    if pairs_4:
        pairs: list[tuple[str, str, str, float]] = pairs_4
    else:
        co_pairs = graph.get_co_occurring_pairs_for_document(document_id, limit=k)
        pairs = [(a, b, "co-occurs", w) for a, b, w in co_pairs]

    if not pairs:
        logger.info("generate_from_graph: no entity pairs found for doc=%s", document_id)
        return []

    semaphore = asyncio.Semaphore(5)

    async def _generate_one(
        name_a: str, name_b: str, relation_label: str
    ) -> list[FlashcardModel]:
        async with semaphore:
            from app.services.retriever import get_retriever  # noqa: PLC0415

            retriever = get_retriever()
            query = f"{name_a} {name_b}"
            scored_chunks = await retriever.retrieve(
                query=query, document_ids=[document_id], k=5
            )
            if not scored_chunks:
                return []

            ctx = "\n\n".join(c.text for c in scored_chunks)[:_CHUNK_CHAR_LIMIT]
            first_chunk_id = scored_chunks[0].chunk_id

            prompt = GRAPH_FLASHCARD_USER_TMPL.format(
                name_a=name_a,
                name_b=name_b,
                relation_label=relation_label or "related",
                context=ctx,
                count=cards_per_pair,
            )
            raw = await llm.generate(
                prompt, system=GRAPH_FLASHCARD_SYSTEM,
                model=_generation_model(), stream=False,
            )
            cards_data = _parse_llm_response(raw, document_id)

            now = datetime.now(UTC)
            cards: list[FlashcardModel] = []
            for item in cards_data:
                if not isinstance(item, dict):
                    continue
                question = str(item.get("question", "")).strip()
                answer = str(item.get("answer", "")).strip()
                source_excerpt = str(item.get("source_excerpt", "")).strip()
                if not question or not answer:
                    continue
                cards.append(
                    FlashcardModel(
                        id=str(uuid.uuid4()),
                        document_id=document_id,
                        chunk_id=first_chunk_id,
                        source="graph",
                        deck="graph",
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
                    )
                )
            return cards

    await session.commit()  # Release read locks to prevent WAL deadlocks
    raw_results = await asyncio.gather(
        *[_generate_one(a, b, label) for a, b, label, _conf in pairs],
        return_exceptions=True,
    )

    all_cards: list[FlashcardModel] = []
    for res in raw_results:
        if isinstance(res, (LLMServiceUnavailableError, LLMAPIConnectionError)):
            raise res  # type: ignore[misc]
        if isinstance(res, BaseException):
            logger.warning("generate_from_graph: error for a pair: %s", res)
            continue
        all_cards.extend(res)  # type: ignore[arg-type]

    for card in all_cards:
        session.add(card)
        await _sync_flashcard_fts(card, session)
    if all_cards:
        await session.commit()
        for card in all_cards:
            await session.refresh(card)
        logger.info(
            "generate_from_graph: created %d cards for doc=%s", len(all_cards), document_id
        )

    return all_cards


