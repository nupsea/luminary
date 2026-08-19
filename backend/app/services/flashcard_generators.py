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
from collections.abc import Awaitable, Callable
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
from app.services import llm_output_stats
from app.services.enrichment_concurrency import get_enrichment_llm_semaphore
from app.services.flashcard_factuality import (
    FACTUALITY_UNCHECKED,
    FACTUALITY_UNSUPPORTED,
    check_answer,
    effective_generation_model,
    factuality_model,
    is_self_judging,
)
from app.services.flashcard_parsers import (
    GROUNDING_UNCHECKED,
    _build_cloze_question,
    _parse_cloze_llm_response,
    _parse_cloze_text,
    _parse_concept_extract,
    _parse_llm_response,
    card_field,
    card_rejection,
    grounding_state,
    strip_source_ref,
)
from app.services.flashcard_prompts import (
    _BOOK_CONTENT_GUIDELINE,
    _DIFFICULTY_GUIDELINES,
    CLOZE_SYSTEM,
    CLOZE_USER_TMPL,
    GRAPH_FLASHCARD_SYSTEM,
    GRAPH_FLASHCARD_USER_TMPL,
    NOTES_CARD_FROM_CONCEPTS_SYSTEM,
    NOTES_CARD_FROM_CONCEPTS_TMPL,
    NOTES_CONCEPT_EXTRACT_TMPL,
    TECH_FLASHCARD_SYSTEM,
    TECH_FLASHCARD_USER_TMPL,
    _build_genre_system_prompt,
    _infer_genre,
    bloom_from,
    flashcard_user_tmpl,
    notes_concept_extract_system,
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
    """See `flashcard._get_generation_model`: resolved, not read from config."""
    from app.services.model_router import resolve  # noqa: PLC0415

    choice = resolve("generation")
    # None when nothing overrides: LLMService then routes it itself, which is
    # what supplies the API key the Settings UI stores and what keeps the
    # offline reroute available. Returning a concrete id here pins the model and
    # loses both -- in cloud mode with the key only in Settings, every
    # generation would fail authentication while chat kept working.
    return choice.model if choice.explicit else None


async def generate_technical(
    document_id: str,
    scope: Literal["full", "section"],
    section_heading: str | None,
    count: int,
    session: AsyncSession,
    model: str | None = None,
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

    combined_text, first_chunk_id, passage_chunk_ids = _build_text(chunks)
    if not combined_text:
        return []

    async def _batch(want: int, avoid: list[str]) -> list[dict]:
        prompt = TECH_FLASHCARD_USER_TMPL.format(
            count=want,
            section_heading=section_heading or "(none)",
            has_code=str(has_code),
            admonition_type=admonition_type or "(none)",
            text=combined_text,
        ) + _avoid_suffix(avoid)
        raw = await llm.generate(
            prompt, system=TECH_FLASHCARD_SYSTEM,
            model=model or _generation_model(), stream=False,
        )
        return await _screen_factuality(
            _gate_cards(
                _parse_llm_response(raw, document_id, expect="array"),
                source_text=combined_text,
            ),
            combined_text,
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

        cards_data = await _collect_with_backfill(count, _batch)
        span.set_attribute("flashcard.generated_count", len(cards_data))

    now = datetime.now(UTC)
    flashcards: list[FlashcardModel] = []
    for item in cards_data:
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        source_excerpt = str(item.get("source_excerpt", "")).strip()
        flashcard_type = str(item.get("flashcard_type", "definition")).strip()
        # Derived from the card's own type or depth word, not asked for as a
        # number: the prompt no longer names a taxonomy (I-28), and the level a
        # type maps to is a decision this codebase owns rather than the model.
        bloom_level: int | None = bloom_from(item)
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
            grounding=item.get("grounding", GROUNDING_UNCHECKED),
            factuality=item.get("factuality", FACTUALITY_UNCHECKED),
            source_chunk_ids=passage_chunk_ids,
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

    combined_text, _, passage_chunk_ids = _build_text(chunks)
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
            # A cloze IS its passage, so the sentence stands in for a quote when the
            # model gave none -- a cloze whose sentence is not in the section was
            # written from memory, and that is checkable without a judge.
            grounding=grounding_state(
                source_excerpt or _build_cloze_question(cloze_text).replace("[____]", ""),
                combined_text,
            ),
            source_chunk_ids=passage_chunk_ids,
        )
        session.add(card)
        await _sync_flashcard_fts(card, session)
        flashcards.append(card)

    if flashcards:
        await session.commit()
        for card in flashcards:
            await session.refresh(card)

    return flashcards


# Extra LLM passes to backfill cards lost to the quality gate / parse failures,
# so a request for N cards returns N rather than silently fewer.
_MAX_GENERATION_RETRIES = 2


def _avoid_suffix(avoid: list[str]) -> str:
    """Prompt fragment steering a retry pass away from questions already kept."""
    if not avoid:
        return ""
    listed = "; ".join(q[:120] for q in avoid[:20])
    return f"\nDo NOT repeat or paraphrase these already-written questions: {listed}\n"


def _gate_cards(parsed: list, source_text: str | None = None) -> list[dict]:
    """Normalize parsed LLM items to {question, answer, source_excerpt, ...} and
    drop any that fail the quality gate. Extra fields (bloom_level,
    flashcard_type) pass through untouched for the caller to persist.

    *source_text* is the passage the cards were generated from. Passing it turns
    on the grounding rules -- the card must quote that text and may not invent
    figures. Generators that build cards from concepts or gaps have no single
    passage to quote and pass nothing."""
    kept: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        q = card_field(item, "question", "front", "q", "term", "prompt")
        a = strip_source_ref(card_field(item, "answer", "back", "a", "definition", "response"))
        excerpt = card_field(item, "source_excerpt", "source", "excerpt")
        verdict = card_rejection(q, a, excerpt, source_text)
        llm_output_stats.record_card_gate(verdict[0] if verdict else None)
        if verdict:
            logger.info("flashcard: dropped low-quality card (%s): %r", verdict[1], q[:80])
            continue
        # The gate already decided this; persisting it is what lets a reviewer ask
        # later which cards proved their source, instead of the answer being lost
        # the moment the request returns.
        kept.append({
            **item,
            "question": q,
            "answer": a,
            "source_excerpt": excerpt,
            "grounding": grounding_state(excerpt, source_text),
        })
    return kept


async def _screen_factuality(cards: list[dict], source_text: str | None) -> list[dict]:
    """Drop cards whose answer does not follow from the passage they were written from.

    Runs only when a checker is configured. It is a second model on a runtime that
    serves one at a time (I-27/I-31), so the checks are batched after generation
    rather than interleaved with it: one model switch per batch instead of one per
    card. Cost is stated in `docs/model-and-eval-plan.md`.

    A card the checker could not judge is kept and recorded `unverifiable`. Failing
    closed would let an unreachable checker silently empty the deck, which is a
    worse failure than an honestly-labelled card -- and the label is on the wire,
    so the reviewer can see it.
    """
    checker = factuality_model()
    if not checker or not source_text or not cards:
        return cards
    if is_self_judging(checker, effective_generation_model()):
        # A model asked whether its own card follows from a passage agrees with
        # itself. Refusing is the only honest option; passing everything is not.
        logger.error(
            "flashcard: factuality checker %s is also the generation model; "
            "skipping the check rather than letting a model grade its own cards",
            checker,
        )
        return cards

    llm = _get_llm_service()
    semaphore = get_enrichment_llm_semaphore()

    async def _one(card: dict) -> str:
        async with semaphore:
            return await check_answer(
                card.get("question", ""),
                card.get("answer", ""),
                source_text,
                checker=checker,
                llm=llm,
            )

    verdicts = await asyncio.gather(*[_one(c) for c in cards])
    kept: list[dict] = []
    for card, verdict in zip(cards, verdicts, strict=True):
        llm_output_stats.record_factuality(verdict)
        if verdict == FACTUALITY_UNSUPPORTED:
            logger.info(
                "flashcard: dropped card whose answer is not in the passage: %r",
                card.get("question", "")[:80],
            )
            continue
        kept.append({**card, "factuality": verdict})
    return kept


async def _collect_with_backfill(
    count: int,
    generate_batch: Callable[[int, list[str]], Awaitable[list[dict]]],
) -> list[dict]:
    """Run `generate_batch(want, avoid)` until `count` gate-passing cards are
    collected or a pass stops making progress. Each retry is told which
    questions are already accepted so it adds new cards instead of repeats.
    Returns at most `count` cards."""
    candidates: list[dict] = []
    seen: set[str] = set()
    attempts = 0
    while len(candidates) < count and attempts <= _MAX_GENERATION_RETRIES:
        batch = await generate_batch(count - len(candidates), [c["question"] for c in candidates])
        attempts += 1
        added = 0
        for c in batch:
            key = c["question"].lower()
            if key in seen:
                # The model was told which questions it had already produced and
                # produced one of them again. Dropping it silently hid exactly the
                # structural weakness a small model shows first: `cards_generated`
                # absorbed the repeat and nothing reported it.
                llm_output_stats.record_duplicate_question()
                continue
            seen.add(key)
            candidates.append(c)
            added += 1
        if added == 0:
            break
    if len(candidates) < count:
        logger.info(
            "flashcard: %d/%d usable cards after %d attempt(s) (model=%s)",
            len(candidates), count, attempts, _generation_model() or "default",
        )
    # Retry-to-backfill is where a weaker model shows up as call count rather
    # than as quality: N cards are delivered either way, and only `attempts`
    # differs. Counted here so the difference is a number.
    delivered = min(len(candidates), count)
    llm_output_stats.record_generation(requested=count, delivered=delivered, attempts=attempts)
    return candidates[:count]


async def _generate_concept_cards(
    llm,
    domain: str,
    concepts: list,
    combined_text: str,
    difficulty: str,
    parse_ctx: str,
    count: int,
) -> list[dict]:
    """Concept-grounded card generation with quality-gate backfill. Shared by
    the note-tag and collection-per-note paths. Parameters (not loop variables)
    are captured by the inner batch closure, so it is safe to call in a loop."""

    async def _batch(_want: int, avoid: list[str]) -> list[dict]:
        prompt = NOTES_CARD_FROM_CONCEPTS_TMPL.format(
            domain=domain,
            difficulty=difficulty,
            difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
            concepts_json=json.dumps(concepts, ensure_ascii=False),
            text=combined_text,
        ) + _avoid_suffix(avoid)
        raw = await llm.generate(
            prompt, system=NOTES_CARD_FROM_CONCEPTS_SYSTEM,
            model=_generation_model(), stream=False,
        )
        return await _screen_factuality(
            _gate_cards(
                _parse_llm_response(raw, parse_ctx, expect="array"),
                source_text=combined_text,
            ),
            combined_text,
        )

    # cards are grounded one-per-concept, so the achievable count is bounded by
    # how many concepts were extracted -- never retry past that
    return await _collect_with_backfill(min(count, len(concepts)), _batch)


async def generate(
    document_id: str,
    scope: Literal["full", "section"],
    section_heading: str | None,
    count: int,
    session: AsyncSession,
    difficulty: Literal["easy", "medium", "hard"] = "medium",
    context: str | None = None,
    model: str | None = None,
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

    # infer genre for genre-aware system prompt
    genre = _infer_genre(doc)
    system_prompt = _build_genre_system_prompt(genre)

    # When the caller supplies selected text, use it directly (bypass classifier).
    chunk_classification: str | None = None
    section_ctx: dict[str, tuple[str, str | None]] = {}
    resolved_section_heading: str | None = None
    eligible_chunks: list[ChunkModel] = []
    # [] rather than None: the passage was supplied text (a reader selection), so
    # there is nothing in the library to rebuild it from -- which is a different
    # fact from "we never recorded it" and has to stay distinguishable.
    passage_chunk_ids: list[str] = []
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

        # look up section headings for context enrichment
        section_ctx = await _get_section_context_for_chunks(chunks, session)

        # classify chunks and filter to concept/definition (+ adjacent elaborators)
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
            combined_text, first_chunk_id, passage_chunk_ids = _build_enriched_text(
                eligible_chunks, section_ctx
            )
        else:
            combined_text, first_chunk_id, passage_chunk_ids = _build_text(eligible_chunks)
        if not combined_text:
            return []

        first_sec = eligible_chunks[0].section_id if eligible_chunks else None
        if first_sec and first_sec in section_ctx:
            resolved_section_heading = _resolve_section_heading(eligible_chunks[0], section_ctx)

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

    async def _batch(want: int, avoid: list[str]) -> list[dict]:
        batch_prompt = flashcard_user_tmpl().format(
            count=want,
            difficulty=difficulty,
            difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
            extra_instructions=extra_instructions,
            text=combined_text,
        ) + _avoid_suffix(avoid)
        raw = await llm.generate(
            batch_prompt, system=system_prompt,
            model=model or _generation_model(), stream=False,
            response_format={"type": "json_object"},
        )
        return await _screen_factuality(
            _gate_cards(
                _parse_llm_response(raw, document_id, expect="object"),
                source_text=combined_text,
            ),
            combined_text,
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

        candidates = await _collect_with_backfill(count, _batch)
        span.set_attribute("flashcard.generated_count", len(candidates))

    now = datetime.now(UTC)

    import numpy as np  # noqa: PLC0415

    from app.services.embedder import get_embedding_service  # noqa: PLC0415

    _existing_qs, existing_vecs = await _fetch_existing_embeddings(
        "default", session, document_id=document_id
    )

    if not candidates:
        logger.warning(
            "flashcard.generate: 0 usable cards (model=%s)",
            model or _generation_model() or "default",
        )

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
    deduped = 0
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
                deduped += 1
                continue
            pool_vecs = np.vstack([pool_vecs, cand_vecs[i : i + 1]])
        # Derived from the card's own type or depth word, not asked for as a
        # number: the prompt no longer names a taxonomy (I-28), and the level a
        # type maps to is a decision this codebase owns rather than the model.
        card_bloom_level = bloom_from(item)

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
            grounding=item.get("grounding", GROUNDING_UNCHECKED),
            factuality=item.get("factuality", FACTUALITY_UNCHECKED),
            source_chunk_ids=passage_chunk_ids,
        )
        session.add(card)
        await _sync_flashcard_fts(card, session)
        flashcards.append(card)

    if deduped:
        llm_output_stats.record_items_deduped(deduped)
        logger.info(
            "flashcard.generate: %d of %d candidates removed as near-duplicates of cards "
            "this document already has",
            deduped,
            len(candidates),
        )

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
            system=notes_concept_extract_system(),
            model=_generation_model(), stream=False,
        )
        domain, concepts = _parse_concept_extract(raw_concepts)
        concepts = concepts[:count]

        if not concepts:
            return []

        cards_data = await _generate_concept_cards(
            llm, domain, concepts, combined_text, difficulty, "notes", count
        )
        span.set_attribute("flashcard.generated_count", len(cards_data))

    now = datetime.now(UTC)
    flashcards: list[FlashcardModel] = []
    for item in cards_data:
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        source_excerpt = str(item.get("source_excerpt", "")).strip()
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
            grounding=item.get("grounding", GROUNDING_UNCHECKED),
            factuality=item.get("factuality", FACTUALITY_UNCHECKED),
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
            system=notes_concept_extract_system(),
            model=_generation_model(),
            stream=False,
        )
        domain, concepts = _parse_concept_extract(raw_concepts)
        concepts = concepts[:count_per_note]
        if not concepts:
            continue

        cards_data = await _generate_concept_cards(
            llm, domain, concepts, combined_text, difficulty, note_id, count_per_note
        )

        now = datetime.now(UTC)
        for item in cards_data:
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            source_excerpt = str(item.get("source_excerpt", "")).strip()
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
                grounding=item.get("grounding", GROUNDING_UNCHECKED),
                factuality=item.get("factuality", FACTUALITY_UNCHECKED),
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
            passage_ids = [c.chunk_id for c in scored_chunks]

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
            cards_data = _parse_llm_response(raw, document_id, expect="array")

            now = datetime.now(UTC)
            cards: list[FlashcardModel] = []
            for item in cards_data:
                if not isinstance(item, dict):
                    continue
                question = str(item.get("question", "")).strip()
                answer = str(item.get("answer", "")).strip()
                source_excerpt = str(item.get("source_excerpt", "")).strip()
                verdict = card_rejection(question, answer, source_excerpt, ctx)
                if verdict:
                    logger.info(
                        "flashcard: dropped low-quality card (%s): %r", verdict[1], question[:80]
                    )
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
                        grounding=grounding_state(source_excerpt, ctx),
                        source_chunk_ids=passage_ids,
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


