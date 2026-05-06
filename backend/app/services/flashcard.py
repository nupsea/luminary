"""Flashcard generation service — LLM-based QA flashcard generation."""

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    ChunkModel,
    FlashcardModel,
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
        from app.services.flashcard_generators import generate as _gen  # noqa: PLC0415

        return await _gen(
            document_id, scope, section_heading, count, session, difficulty, context
        )

    async def generate_from_notes(
        self,
        tag: str | None,
        note_ids: list[str] | None,
        count: int,
        session: AsyncSession,
        difficulty: Literal["easy", "medium", "hard"] = "medium",
    ) -> list[FlashcardModel]:
        from app.services.flashcard_generators import (  # noqa: PLC0415
            generate_from_notes as _gen,
        )

        return await _gen(tag, note_ids, count, session, difficulty)

    async def generate_from_collection(
        self,
        collection_id: str,
        count_per_note: int,
        difficulty: Literal["easy", "medium", "hard"],
        session: AsyncSession,
        force_regenerate: bool = False,
    ) -> dict:
        from app.services.flashcard_generators import (  # noqa: PLC0415
            generate_from_collection as _gen,
        )

        return await _gen(
            collection_id, count_per_note, difficulty, session, force_regenerate
        )

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
        from app.services.flashcard_generators import (  # noqa: PLC0415
            generate_from_graph as _gen,
        )

        return await _gen(document_id, k, session, cards_per_pair)

    async def generate_technical(
        self,
        document_id: str,
        scope: Literal["full", "section"],
        section_heading: str | None,
        count: int,
        session: AsyncSession,
    ) -> list[FlashcardModel]:
        from app.services.flashcard_generators import (  # noqa: PLC0415
            generate_technical as _gen_technical,
        )

        return await _gen_technical(document_id, scope, section_heading, count, session)

    async def generate_cloze(
        self,
        section_id: str,
        count: int,
        session: AsyncSession,
    ) -> list[FlashcardModel]:
        from app.services.flashcard_generators import (  # noqa: PLC0415
            generate_cloze as _gen_cloze,
        )

        return await _gen_cloze(section_id, count, session)


_flashcard_service: FlashcardService | None = None


def get_flashcard_service() -> FlashcardService:
    global _flashcard_service  # noqa: PLW0603
    if _flashcard_service is None:
        _flashcard_service = FlashcardService()
    return _flashcard_service
