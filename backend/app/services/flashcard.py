"""Flashcard generation service — LLM-based QA flashcard generation."""

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
    _CLOZE_BLANK_RE,
    _build_cloze_question,
    _parse_cloze_llm_response,
    _parse_cloze_text,
    _parse_concept_extract,
    _parse_gap_flashcard,
    _parse_llm_response,
)
from app.services.flashcard_prompts import (
    _BLOOM_L3_INSTRUCTION,
    _BOOK_CONTENT_GUIDELINE,
    _DIFFICULTY_GUIDELINES,
    _TECH_TITLE_KEYWORDS,
    CLOZE_SYSTEM,
    CLOZE_USER_TMPL,
    FLASHCARD_SYSTEM,
    FLASHCARD_USER_TMPL,
    GAP_FLASHCARD_SYSTEM,
    GAP_FLASHCARD_USER_TMPL,
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
from app.services.flashcard_search import (
    FlashcardSearchService,
    _delete_flashcard_fts,
    _sanitize_fts5_query,
    _sync_flashcard_fts,
)
from app.services.llm import (
    LLMAPIConnectionError,
    LLMServiceUnavailableError,
    get_llm_service,
)
from app.telemetry import trace_chain

# Re-exported for back-compat (tests + routers import these here).
__all__ = [
    "CLOZE_SYSTEM",
    "CLOZE_USER_TMPL",
    "FLASHCARD_SYSTEM",
    "FLASHCARD_USER_TMPL",
    "FlashcardSearchService",
    "FlashcardService",
    "GAP_FLASHCARD_SYSTEM",
    "GAP_FLASHCARD_USER_TMPL",
    "GRAPH_FLASHCARD_SYSTEM",
    "GRAPH_FLASHCARD_USER_TMPL",
    "NOTES_CARD_FROM_CONCEPTS_SYSTEM",
    "NOTES_CARD_FROM_CONCEPTS_TMPL",
    "NOTES_CONCEPT_EXTRACT_SYSTEM",
    "NOTES_CONCEPT_EXTRACT_TMPL",
    "TECH_FLASHCARD_SYSTEM",
    "TECH_FLASHCARD_USER_TMPL",
    "_BLOOM_L3_INSTRUCTION",
    "_BOOK_CONTENT_GUIDELINE",
    "_CLOZE_BLANK_RE",
    "_DIFFICULTY_GUIDELINES",
    "_TECH_TITLE_KEYWORDS",
    "_build_cloze_question",
    "_build_genre_system_prompt",
    "_delete_flashcard_fts",
    "_infer_genre",
    "_parse_cloze_llm_response",
    "_parse_cloze_text",
    "_parse_concept_extract",
    "_parse_gap_flashcard",
    "_parse_llm_response",
    "_sanitize_fts5_query",
    "_sync_flashcard_fts",
    "get_flashcard_service",
]

logger = logging.getLogger(__name__)


def _get_generation_model() -> str | None:
    """Return the model override for generation tasks, or None to use default."""
    m = get_settings().LITELLM_GENERATION_MODEL
    return m if m else None


# Keep well within mistral's 8K-token context (~4 chars/token, reserve ~2K for prompt+response)
_CHUNK_CHAR_LIMIT = 10_000


async def _get_section_context_for_chunks(
    chunks: list[ChunkModel],
    session: AsyncSession,
) -> dict[str, tuple[str, str | None]]:
    """Return a map of section_id -> (section_heading, parent_heading).

    Used to enrich prompt text with section/chapter context.
    """
    section_ids = list({c.section_id for c in chunks if c.section_id})
    if not section_ids:
        return {}

    result = await session.execute(select(SectionModel).where(SectionModel.id.in_(section_ids)))
    sections = {s.id: s for s in result.scalars().all()}

    # Resolve parent headings (one level up = chapter)
    parent_ids = [s.parent_section_id for s in sections.values() if s.parent_section_id]
    parents: dict[str, SectionModel] = {}
    if parent_ids:
        parent_result = await session.execute(
            select(SectionModel).where(SectionModel.id.in_(parent_ids))
        )
        parents = {s.id: s for s in parent_result.scalars().all()}

    context_map: dict[str, tuple[str, str | None]] = {}
    for sid, sec in sections.items():
        parent_heading = (
            parents[sec.parent_section_id].heading
            if sec.parent_section_id and sec.parent_section_id in parents
            else None
        )
        context_map[sid] = (sec.heading, parent_heading)
    return context_map


async def _get_entity_names_for_document(
    document_id: str,
    types: list[str] | None = None,
    limit: int = 5,
) -> list[str]:
    """Query Kuzu for top entity names for a document, filtered by type.

    Returns up to *limit* names. Non-fatal: returns [] on error.
    """
    try:
        from app.services.graph import get_graph_service  # noqa: PLC0415

        graph_svc = get_graph_service()
        by_type = await asyncio.to_thread(graph_svc.get_entities_by_type_for_document, document_id)
        names: list[str] = []
        target_types = types or ["PERSON", "PLACE"]
        for t in target_types:
            names.extend(by_type.get(t, []))
        # Deduplicate while preserving order, take top N
        seen: set[str] = set()
        unique: list[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                unique.append(n)
        return unique[:limit]
    except Exception:
        logger.debug(
            "Entity lookup failed for %s; skipping enrichment",
            document_id,
            exc_info=True,
        )
        return []


def _build_enriched_text(
    chunks: list[ChunkModel],
    section_ctx: dict[str, tuple[str, str | None]],
) -> tuple[str, str]:
    """Build combined text with section heading prefixes for context.

    Returns (enriched_text, first_chunk_id).
    """
    if not chunks:
        return "", ""

    parts: list[str] = []
    total = 0
    for c in chunks:
        if total >= _CHUNK_CHAR_LIMIT:
            break
        prefix = ""
        if c.section_id and c.section_id in section_ctx:
            heading, parent = section_ctx[c.section_id]
            if parent:
                prefix = f"[{parent} > {heading}]\n"
            else:
                prefix = f"[{heading}]\n"
        part = prefix + c.text
        parts.append(part)
        total += len(part)

    return "\n\n".join(parts), chunks[0].id


def _resolve_section_heading(
    chunk: ChunkModel,
    section_ctx: dict[str, tuple[str, str | None]],
) -> str | None:
    """Build a display-friendly section heading for a card from its chunk's section context."""
    if not chunk.section_id or chunk.section_id not in section_ctx:
        return None
    heading, parent = section_ctx[chunk.section_id]
    if parent:
        return f"{parent} - {heading}"
    return heading


async def _fetch_chunks(
    document_id: str,
    scope: Literal["full", "section"],
    section_heading: str | None,
    session: AsyncSession,
    content_type: str = "unknown",
) -> list[ChunkModel]:
    """Return ordered chunks for the document, filtered by section when scope='section'.

    If scope='full' and content_type='book', it tries to skip preface/introduction sections
    to avoid metadata-heavy flashcards.
    """
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

    # Full scope
    if content_type == "book":
        # Identify sections to skip (preface, intro, etc.)
        skip_terms = [
            "preface",
            "introduction",
            "prologue",
            "foreword",
            "about the author",
            "copyright",
            "translator",
            "table of contents",
            "appendix",
            "index",
            "bibliography",
        ]
        sections_result = await session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .order_by(SectionModel.section_order)
        )
        sections = list(sections_result.scalars().all())

        if sections:
            valid_section_ids = [
                s.id for s in sections if not any(term in s.heading.lower() for term in skip_terms)
            ]
            # If we filtered everything out, fall back to all sections
            if not valid_section_ids:
                valid_section_ids = [s.id for s in sections]

            result = await session.execute(
                select(ChunkModel)
                .where(ChunkModel.document_id == document_id)
                .where(ChunkModel.section_id.in_(valid_section_ids))
                .order_by(ChunkModel.chunk_index)
            )
            return list(result.scalars().all())

    result = await session.execute(
        select(ChunkModel)
        .where(ChunkModel.document_id == document_id)
        .order_by(ChunkModel.chunk_index)
    )
    all_chunks = list(result.scalars().all())

    # If it's a book and we don't have sections (or skip logic didn't trigger),
    # skip the first 5% which is usually front matter/preface.
    if content_type == "book" and all_chunks:
        # Check if first chunk has a section heading that was missed
        # If no sections at all, skip first 5%
        sections_count_result = await session.execute(
            select(text("COUNT(*)"))
            .select_from(SectionModel)
            .where(SectionModel.document_id == document_id)
        )
        count = sections_count_result.scalar()
        if count == 0:
            skip_count = max(1, len(all_chunks) // 20)
            return all_chunks[skip_count:]

    return all_chunks


def _build_text(chunks: list[ChunkModel]) -> tuple[str, str]:
    """Build combined text from chunks.

    If the total text exceeds _CHUNK_CHAR_LIMIT, it samples chunks from the
    beginning, middle, and end to provide better coverage of the entire document.
    Returns (combined_text, first_chunk_id).
    """
    if not chunks:
        return "", ""

    total_chars = sum(len(c.text) for c in chunks)
    if total_chars <= _CHUNK_CHAR_LIMIT:
        return "\n\n".join(c.text for c in chunks), chunks[0].id

    # Sampling strategy:
    # 1. Take first 25% of the limit from the beginning
    # 2. Take 50% from the middle
    # 3. Take 25% from the end
    target_len = _CHUNK_CHAR_LIMIT
    segment_size = target_len // 4

    def get_segment(chunk_list: list[ChunkModel], max_chars: int) -> str:
        parts: list[str] = []
        current = 0
        for c in chunk_list:
            if current + len(c.text) > max_chars:
                break
            parts.append(c.text)
            current += len(c.text)
        return "\n\n".join(parts)

    # Beginning
    beginning = get_segment(chunks, segment_size)

    # Middle
    mid_idx = len(chunks) // 2
    middle = get_segment(chunks[mid_idx:], segment_size * 2)

    # End
    # For the end, we iterate backwards to get a segment, then reverse it
    end_parts: list[str] = []
    end_current = 0
    for c in reversed(chunks):
        if end_current + len(c.text) > segment_size:
            break
        end_parts.append(c.text)
        end_current += len(c.text)
    end = "\n\n".join(reversed(end_parts))

    combined = f"{beginning}\n\n[...]\n\n{middle}\n\n[...]\n\n{end}"
    return combined, chunks[0].id


# ---------------------------------------------------------------------------
# S179: Chunk classifier helpers
# ---------------------------------------------------------------------------

_ANALOGY_PATTERNS = re.compile(
    r"\b(like a|similar to|imagine|think of it as|is like|just as|as if|as though"
    r"|analogous to|metaphor|by analogy)\b",
    re.IGNORECASE,
)
_EXAMPLE_PATTERNS = re.compile(
    r"\b(for example|for instance|e\.g\.|consider this|such as|to illustrate"
    r"|as an example|as a case)\b",
    re.IGNORECASE,
)
_DEFINITION_PATTERNS = re.compile(
    r"(is defined as|refers to|means that|is the process of|is a term|"
    r"can be defined|:\s*a\s+\w|:\s*the\s+\w)",
    re.IGNORECASE,
)
_CONCEPT_PATTERNS = re.compile(
    r"\b(therefore|as a result|the key idea|the principle|this means|the reason"
    r"|this enables|this causes|the mechanism|the implication|the effect|"
    r"crucially|fundamentally|essentially)\b",
    re.IGNORECASE,
)
_TRANSITION_PATTERNS = re.compile(
    r"\b(in the next|in the following|as we saw|moving on|in summary|"
    r"to recap|we have seen|in this chapter)\b",
    re.IGNORECASE,
)

_CHUNK_CLASSIFICATION_LABELS = frozenset(
    {"concept", "definition", "example", "analogy", "narrative", "transition"}
)
_ELIGIBLE_LABELS = frozenset({"concept", "definition"})


def _classify_chunk(text: str) -> str:
    """Classify a chunk of text into one of six categories.

    Rules applied in order -- first match wins:
      definition > concept > analogy > example > transition > narrative
    """
    if _DEFINITION_PATTERNS.search(text):
        return "definition"
    if _CONCEPT_PATTERNS.search(text):
        return "concept"
    if _ANALOGY_PATTERNS.search(text):
        return "analogy"
    if _EXAMPLE_PATTERNS.search(text):
        return "example"
    if len(text.strip()) < 80 or _TRANSITION_PATTERNS.search(text):
        return "transition"
    return "narrative"


def _filter_chunks_by_classification(
    chunks: list[ChunkModel],
) -> list[tuple[ChunkModel, str]]:
    """Return (chunk, label) pairs for chunks eligible for flashcard generation.

    Eligible: concept or definition chunks, plus any immediately adjacent
    example/analogy chunk that elaborates a concept/definition chunk.
    """
    if not chunks:
        return []

    labels = [_classify_chunk(c.text) for c in chunks]
    eligible_indices: set[int] = set()

    for i, label in enumerate(labels):
        if label in _ELIGIBLE_LABELS:
            eligible_indices.add(i)
            # Adjacent elaborators
            if i > 0 and labels[i - 1] in ("example", "analogy"):
                eligible_indices.add(i - 1)
            if i < len(chunks) - 1 and labels[i + 1] in ("example", "analogy"):
                eligible_indices.add(i + 1)

    return [(chunks[i], labels[i]) for i in sorted(eligible_indices)]


async def _fetch_existing_embeddings(
    deck: str, session: AsyncSession
) -> "tuple[list[str], list] | tuple[list, None]":
    """Fetch all existing questions in *deck* and embed them in one batch.

    Returns (questions, vectors) or ([], None) when the deck is empty or embedding fails.
    """
    import numpy as np  # noqa: PLC0415

    from app.services.embedder import get_embedding_service  # noqa: PLC0415

    result = await session.execute(
        select(FlashcardModel.question).where(FlashcardModel.deck == deck)
    )
    existing_questions = [row[0] for row in result.all()]
    if not existing_questions:
        return [], None

    embedder = get_embedding_service()
    try:
        vecs = await asyncio.to_thread(embedder.encode, existing_questions)
        return existing_questions, np.array(vecs)
    except Exception:
        logger.warning(
            "Embedding dedup: failed to encode existing questions; skipping dedup", exc_info=True
        )
        return [], None


def _is_near_duplicate(
    candidate_vec: "Any",
    existing_vecs: "Any",
    threshold: float = 0.85,
) -> bool:
    """Return True if candidate_vec is within *threshold* cosine similarity of any existing_vec."""
    import numpy as np  # noqa: PLC0415

    candidate_norm = candidate_vec / (np.linalg.norm(candidate_vec) + 1e-10)
    existing_norms = existing_vecs / (np.linalg.norm(existing_vecs, axis=1, keepdims=True) + 1e-10)
    sims = existing_norms @ candidate_norm
    return bool(np.any(sims >= threshold))


class FlashcardService(FlashcardSearchService):
    async def generate(
        self,
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
        llm = get_llm_service()

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
        if context and context.strip():
            combined_text = context.strip()[:_CHUNK_CHAR_LIMIT]
            # Still need a chunk_id (NOT NULL) — grab the first chunk for the document.
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
                # Safety net: no chunks classified as concept/definition -- use all chunks
                eligible_chunks = chunks
                logger.info(
                    "flashcard.generate: no concept/definition chunks found, using all %d chunks",
                    len(chunks),
                )

            # S188: build enriched text with section heading prefixes
            if section_ctx:
                combined_text, first_chunk_id = _build_enriched_text(eligible_chunks, section_ctx)
            else:
                combined_text, first_chunk_id = _build_text(eligible_chunks)
            if not combined_text:
                return []

            # S188: resolve section heading for cards (first chunk's section)
            first_sec = eligible_chunks[0].section_id if eligible_chunks else None
            if first_sec and first_sec in section_ctx:
                resolved_section_heading = _resolve_section_heading(eligible_chunks[0], section_ctx)

        # S188: enrich system prompt with Bloom L3+ targeting and citation instruction
        system_prompt += _BLOOM_L3_INSTRUCTION

        # S188: for books, inject entity names into the system prompt
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

        # S188: for technical docs, include code block excerpts
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
                model=_get_generation_model(), stream=False,
            )
            cards_data = _parse_llm_response(raw, document_id)
            span.set_attribute("flashcard.generated_count", len(cards_data))

        now = datetime.now(UTC)

        # Pre-compute existing embeddings once (avoids re-embedding on every card).
        # Also embed all candidate questions in one batch, then filter duplicates in-memory.
        import numpy as np  # noqa: PLC0415

        from app.services.embedder import get_embedding_service  # noqa: PLC0415

        _existing_qs, existing_vecs = await _fetch_existing_embeddings("default", session)

        # Collect valid candidates first, then dedup in a single embed batch
        candidates: list[dict] = []
        for item in cards_data:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question", "")).strip()
            a = str(item.get("answer", "")).strip()
            if q and a:
                candidates.append(item)

        # Batch-embed all candidate questions in one call
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

        # Build accepted set, checking each candidate against existing + previously accepted
        pool_vecs = existing_vecs  # grows as we accept cards
        flashcards: list[FlashcardModel] = []
        for i, item in enumerate(candidates):
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            source_excerpt = str(item.get("source_excerpt", "")).strip()
            # Dedup check using pre-computed vectors
            if cand_vecs is not None and pool_vecs is not None:
                if _is_near_duplicate(cand_vecs[i], pool_vecs):
                    logger.info(
                        "flashcard.generate: skipping near-duplicate question: %r",
                        question[:80],
                    )
                    continue
                # Add accepted card's vector to pool so intra-batch duplicates are also caught
                pool_vecs = np.vstack([pool_vecs, cand_vecs[i : i + 1]])
            # S188: extract bloom_level from LLM response if present
            card_bloom_level = item.get("bloom_level")
            if isinstance(card_bloom_level, int) and 1 <= card_bloom_level <= 6:
                pass  # valid
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
        self,
        tag: str | None,
        note_ids: list[str] | None,
        count: int,
        session: AsyncSession,
        difficulty: Literal["easy", "medium", "hard"] = "medium",
    ) -> list[FlashcardModel]:
        """Generate flashcards from user notes scoped by tag or explicit note IDs.

        Raises ValueError if neither tag nor note_ids is provided.
        Returns [] if no matching notes are found.
        """
        if not tag and not note_ids:
            raise ValueError("Must provide tag or note_ids")

        llm = get_llm_service()

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

        # Pass 1: extract typed concepts from the notes.
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
                model=_get_generation_model(), stream=False,
            )
            domain, concepts = _parse_concept_extract(raw_concepts)
            concepts = concepts[:count]

            if not concepts:
                return []

            # Pass 2: generate one typed card per concept, grounded against original text.
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
                model=_get_generation_model(), stream=False,
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
        self,
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
        llm = get_llm_service()

        # 1. Fetch collection name
        coll_result = await session.execute(
            select(CollectionModel).where(CollectionModel.id == collection_id)
        )
        collection = coll_result.scalar_one_or_none()
        if collection is None:
            raise ValueError(f"Collection {collection_id!r} not found")

        deck_name = collection.name

        # 2. Fetch member note_ids
        member_result = await session.execute(
            select(CollectionMemberModel.member_id).where(
                CollectionMemberModel.collection_id == collection_id,
                CollectionMemberModel.member_type == "note",
            )
        )
        note_ids = [row[0] for row in member_result.all()]

        created = 0
        skipped = 0

        # 3. Process each note sequentially
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

            # Pass 1: extract typed concepts.
            raw_concepts = await llm.generate(
                NOTES_CONCEPT_EXTRACT_TMPL.format(
                    max_concepts=max(count_per_note, 8),
                    text=combined_text,
                ),
                system=NOTES_CONCEPT_EXTRACT_SYSTEM,
                model=_get_generation_model(),
                stream=False,
            )
            domain, concepts = _parse_concept_extract(raw_concepts)
            concepts = concepts[:count_per_note]
            if not concepts:
                continue

            # Pass 2: generate one typed card per concept, grounded against original text.
            raw = await llm.generate(
                NOTES_CARD_FROM_CONCEPTS_TMPL.format(
                    domain=domain,
                    difficulty=difficulty,
                    difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
                    concepts_json=json.dumps(concepts, ensure_ascii=False),
                    text=combined_text,
                ),
                system=NOTES_CARD_FROM_CONCEPTS_SYSTEM,
                model=_get_generation_model(),
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

    async def _run_gap_generation(
        self,
        gaps: list[str],
        document_id: str,
        session: AsyncSession,
        *,
        source: str,
        deck: str,
        flashcard_type: str | None,
        log_prefix: str,
    ) -> tuple[int, list[str]]:
        """Shared engine for gap-based flashcard generation.

        Used by both generate_from_gaps and generate_from_feynman_gaps. Calls
        the LLM once per gap with bounded concurrency, parses the {front,back}
        JSON, persists matching FlashcardModel rows, syncs FTS, and returns
        (created_count, card_ids). Re-raises Ollama-offline errors; logs and
        skips any other per-gap exception.
        """
        llm = get_llm_service()
        semaphore = asyncio.Semaphore(5)

        async def _generate_one(gap: str) -> FlashcardModel | None:
            async with semaphore:
                prompt = GAP_FLASHCARD_USER_TMPL.format(gap=gap)
                raw = await llm.generate(
                    prompt, system=GAP_FLASHCARD_SYSTEM,
                    model=_get_generation_model(), stream=False,
                )
                item = _parse_gap_flashcard(raw, gap)
                if item is None:
                    return None
                now = datetime.now(UTC)
                kwargs: dict[str, Any] = {}
                if flashcard_type is not None:
                    kwargs["flashcard_type"] = flashcard_type
                return FlashcardModel(
                    id=str(uuid.uuid4()),
                    document_id=document_id if document_id else None,
                    chunk_id=None,
                    source=source,
                    deck=deck,
                    question=item["front"].strip(),
                    answer=item["back"].strip(),
                    source_excerpt=gap,
                    fsrs_state="new",
                    fsrs_stability=0.0,
                    fsrs_difficulty=0.0,
                    due_date=now,
                    reps=0,
                    lapses=0,
                    created_at=now,
                    **kwargs,
                )

        await session.commit()  # Release read locks to prevent WAL deadlocks
        raw_results = await asyncio.gather(
            *[_generate_one(g) for g in gaps], return_exceptions=True
        )
        # Re-raise Ollama-offline errors so the router can map them to 503.
        # Any other unexpected exception is logged and skipped (same policy as malformed JSON).
        for exc in raw_results:
            if isinstance(exc, (LLMServiceUnavailableError, LLMAPIConnectionError)):
                raise exc
            if isinstance(exc, BaseException):
                logger.warning("%s: unexpected error for a gap, skipping: %s", log_prefix, exc)
        results: list[FlashcardModel | None] = [
            r for r in raw_results if not isinstance(r, BaseException)
        ]
        cards = [r for r in results if r is not None]
        ids: list[str] = []
        for card in cards:
            session.add(card)
            await _sync_flashcard_fts(card, session)
            ids.append(card.id)
        if cards:
            await session.commit()
            logger.info(
                "%s: created %d flashcards from %d gaps", log_prefix, len(cards), len(gaps)
            )
        return len(cards), ids

    async def generate_from_gaps(
        self,
        gaps: list[str],
        document_id: str,
        session: AsyncSession,
    ) -> tuple[int, list[str]]:
        """Generate one flashcard per gap using bounded LLM concurrency (semaphore=5).

        Skips gaps whose LLM response cannot be parsed.
        Raises LLMServiceUnavailableError if Ollama is unreachable.
        Returns (created_count, card_ids).
        """
        return await self._run_gap_generation(
            gaps,
            document_id,
            session,
            source="gap",
            deck="gaps",
            flashcard_type=None,
            log_prefix="generate_from_gaps",
        )

    async def generate_from_feynman_gaps(
        self,
        gaps: list[str],
        document_id: str,
        session: AsyncSession,
    ) -> tuple[int, list[str]]:
        """Generate concept_explanation flashcards from Feynman session gaps.

        Identical to generate_from_gaps but sets source='feynman',
        deck='feynman', flashcard_type='concept_explanation'.
        Raises LLMServiceUnavailableError if Ollama is unreachable.
        Returns (created_count, card_ids).
        """
        return await self._run_gap_generation(
            gaps,
            document_id,
            session,
            source="feynman",
            deck="feynman",
            flashcard_type="concept_explanation",
            log_prefix="generate_from_feynman_gaps",
        )

    async def generate_from_graph(
        self,
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
        from app.services.graph import get_graph_service  # noqa: PLC0415

        llm = get_llm_service()
        graph = get_graph_service()

        # Fetch top-k pairs by confidence (RELATED_TO) -- fall back to CO_OCCURS if empty
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

                context = "\n\n".join(c.text for c in scored_chunks)[:_CHUNK_CHAR_LIMIT]
                first_chunk_id = scored_chunks[0].chunk_id

                prompt = GRAPH_FLASHCARD_USER_TMPL.format(
                    name_a=name_a,
                    name_b=name_b,
                    relation_label=relation_label or "related",
                    context=context,
                    count=cards_per_pair,
                )
                raw = await llm.generate(
                    prompt, system=GRAPH_FLASHCARD_SYSTEM,
                    model=_get_generation_model(), stream=False,
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

    async def generate_technical(
        self,
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
        llm = get_llm_service()

        doc_result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = doc_result.scalar_one_or_none()
        content_type = doc.content_type if doc else "unknown"

        chunks = await _fetch_chunks(document_id, scope, section_heading, session, content_type)
        if not chunks:
            return []

        # Determine context signals for the prompt
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
                model=_get_generation_model(), stream=False,
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
        self,
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
        llm = get_llm_service()

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
                model=_get_generation_model(), stream=False,
            )
            items = _parse_cloze_llm_response(raw)

            if not items:
                logger.warning(
                    "generate_cloze: no valid cards on first attempt for section=%s, retrying",
                    section_id,
                )
                raw2 = await llm.generate(
                prompt, system=CLOZE_SYSTEM,
                model=_get_generation_model(), stream=False,
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


_flashcard_service: FlashcardService | None = None


def get_flashcard_service() -> FlashcardService:
    global _flashcard_service  # noqa: PLW0603
    if _flashcard_service is None:
        _flashcard_service = FlashcardService()
    return _flashcard_service
