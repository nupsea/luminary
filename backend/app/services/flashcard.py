"""Flashcard generation service — LLM-based QA flashcard generation."""

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Literal

import litellm
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChunkModel,
    DocumentModel,
    FlashcardModel,
    NoteCollectionMemberModel,
    NoteCollectionModel,
    NoteModel,
    SectionModel,
)
from app.services.llm import get_llm_service
from app.telemetry import trace_chain

logger = logging.getLogger(__name__)

FLASHCARD_SYSTEM = (
    "You are a learning assistant creating flashcards for active recall. "
    "Generate questions that test understanding of the content. "
    "Prefer questions that: (1) ask the learner to explain a concept in their own words"
    " (comprehension), "
    "(2) apply a concept to a new situation (application), "
    "(3) distinguish between similar concepts (analysis), "
    "or (4) evaluate a claim or argument (evaluation). "
    "AVOID: trivia questions about exact wording, hypothetical questions not grounded"
    " in the content, "
    "questions whose answer is not in the text, yes/no questions. "
    "CRITICAL — questions must be fully self-contained. "
    "NEVER use phrases like 'in this passage', 'according to this text', 'in this excerpt', "
    "'in this book', 'in this document', or any similar reference to the source material. "
    "A flashcard question must make complete sense on its own without seeing the original text. "
    "CRITICAL — question framing must match the answer exactly: "
    "if the answer describes a state, mood, behaviour, or activity, ask about that"
    " state/mood/behaviour/activity. "
    "Do NOT use category words (occupation, profession, role, identity, trait) when"
    " the answer is actually describing what someone is doing or feeling. "
    "Before writing each question, ask yourself: would a reader who does not already"
    " know the answer interpret this question as asking exactly what the answer provides? "
    "If not, reword the question until it does. "
    "Output a JSON array starting with [ and ending with ]. "
    "Write no explanation, preamble, or markdown fences."
)

FLASHCARD_USER_TMPL = (
    "Generate {count} {difficulty}-level flashcard pairs from the text below.\n"
    "Difficulty guidelines: {difficulty_guidelines}\n"
    "{extra_instructions}"
    "Each card must be answerable from the provided text only.\n"
    'Format: [{{"question": "...", "answer": "...", "source_excerpt": "..."}}]\n'
    "The \"answer\" field may use Markdown (bold, lists) for clarity.\n\n"
    "Text:\n{text}\n\n"
    "JSON array:"
)

_DIFFICULTY_GUIDELINES = {
    "easy": (
        "Focus on basic recall, key characters, main plot points, and obvious facts. "
        "Questions should be straightforward."
    ),
    "medium": (
        "Focus on comprehension, connecting ideas, identifying themes, and explaining 'why'. "
        "Questions should require some thought and understanding."
    ),
    "hard": (
        "Focus on analysis, evaluation, complex relationships, subtle themes, and application "
        "to new contexts. Questions should be challenging and require deep insight."
    ),
}

_BOOK_CONTENT_GUIDELINE = (
    "IMPORTANT: Focus exclusively on the primary narrative or subject matter "
    "(story, characters, plot, themes, or core arguments). "
    "STRICTLY AVOID generating any flashcard about: "
    "Project Gutenberg, publication details, copyright notices, licensing, "
    "translators, editors, publishers, prefaces, forewords, introductions, "
    "the purpose of publishing the work, or any other front/back matter. "
    "These are irrelevant to learning the content and must be completely ignored. "
    "If the provided text starts with publisher boilerplate or editorial notes, "
    "skip past them entirely and generate questions only from the actual narrative or subject.\n"
)


# Keep well within mistral's 8K-token context (~4 chars/token, reserve ~2K for prompt+response)
_CHUNK_CHAR_LIMIT = 10_000


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
            "preface", "introduction", "prologue", "foreword",
            "about the author", "copyright", "translator",
            "table of contents", "appendix", "index", "bibliography"
        ]
        sections_result = await session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .order_by(SectionModel.section_order)
        )
        sections = list(sections_result.scalars().all())

        if sections:
            valid_section_ids = [
                s.id for s in sections
                if not any(term in s.heading.lower() for term in skip_terms)
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


def _parse_llm_response(raw: str, document_id: str) -> list[dict]:
    """Extract a JSON array from the LLM response.

    Handles:
    - Clean JSON array responses
    - Responses wrapped in markdown code fences
    - Responses with preamble prose before the array
    - Responses with trailing text after the array
    """
    raw = raw.strip()

    # Strip markdown code fences
    raw = re.sub(r"^```[^\n]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()

    # If it already looks like a clean array, try parsing directly
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    # Fall back: find the first '[' and last ']' and parse that slice
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("Flashcard JSON parse failed for doc %s: %r", document_id, raw[:200])
    return []


TECH_FLASHCARD_SYSTEM = (
    "You are a technical learning assistant creating flashcards based on Bloom's Taxonomy. "
    "For each card choose exactly one of these flashcard types: "
    "definition (L1), syntax_recall (L1), concept_explanation (L2), analogy (L2), "
    "code_completion (L3), api_signature (L3), trace (L4), pattern_recognition (L4), "
    "design_decision (L5), complexity (L5), implementation (L6). "
    "Choose the type that best matches what the card asks the learner to do. "
    "For code_completion cards: show a code block with a blank rendered as ____ where the "
    "learner must supply the missing part. "
    "For trace cards: show a code snippet and ask the learner to predict its output. "
    "For design_decision cards: ask the learner to justify a technical choice. "
    "For complexity cards: ask the learner to state and justify Big-O for an algorithm. "
    "Questions must be self-contained. "
    "NEVER use phrases like 'in this passage' or 'in this text'. "
    "Output a JSON array starting with [ and ending with ]. "
    'Each element: {"question": "...", "answer": "...", '
    '"source_excerpt": "...", "flashcard_type": "...", "bloom_level": N}. '
    "bloom_level is an integer 1-6. "
    "Write no explanation, preamble, or markdown fences."
)

TECH_FLASHCARD_USER_TMPL = (
    "Generate {count} technical flashcards from the text below.\n"
    "Prefer higher Bloom levels (trace, code_completion, design_decision) when the text "
    "contains code blocks, API signatures, or trade-off discussions.\n"
    "When the section heading contains 'vs' or 'trade-off', generate at least one "
    "design_decision card (bloom_level=5).\n"
    "When the text contains an admonition type of 'warning', generate at least one "
    "definition card (bloom_level=1) that captures the warning.\n"
    "Each card must be answerable from the provided text only.\n"
    'Format: [{{"question": "...", "answer": "...", "source_excerpt": "...", '
    '"flashcard_type": "...", "bloom_level": N}}]\n\n'
    "Section heading: {section_heading}\n"
    "Has code blocks: {has_code}\n"
    "Admonition type: {admonition_type}\n\n"
    "Text:\n{text}\n\n"
    "JSON array:"
)


GAP_FLASHCARD_SYSTEM = (
    "You are a learning assistant. Generate exactly ONE flashcard for the given knowledge gap. "
    'Output ONLY a JSON object with two keys: {"front": "...", "back": "..."} '
    "where 'front' is the question and 'back' is a concise answer. "
    "Write no explanation, preamble, or markdown fences. Output only the JSON object."
)

GAP_FLASHCARD_USER_TMPL = (
    'Knowledge gap: "{gap}"\n\n'
    'Generate one flashcard as JSON: {{"front": "question", "back": "answer"}}'
)

GRAPH_FLASHCARD_SYSTEM = (
    "You are a learning assistant creating flashcards that test understanding of relationships "
    "between concepts. Each question must ask how two named entities are connected, "
    "what one entity means in the context of the other, "
    "or what role one plays relative to the other. "
    "NEVER frame a question as a definition question ('What is X?'). "
    "NEVER use phrases like 'in this passage' or 'according to this text'. "
    "Questions must be self-contained. "
    "Output a JSON array starting with [ and ending with ]. "
    "Write no explanation, preamble, or markdown fences."
)

GRAPH_FLASHCARD_USER_TMPL = (
    "Entity A: {name_a}\n"
    "Entity B: {name_b}\n"
    "Relationship hint: {relation_label}\n\n"
    "Context passages:\n{context}\n\n"
    "Generate {count} flashcard(s) testing the relationship between '{name_a}' and '{name_b}'.\n"
    "Each question must be framed as a relationship question "
    "('How does X relate to Y?', 'What connects X and Y?', 'What role does X play in Y?').\n"
    'Format: [{{"question": "...", "answer": "...", "source_excerpt": "..."}}]\n'
    "JSON array:"
)


def _parse_gap_flashcard(raw: str, gap: str) -> dict | None:
    """Parse a single {front, back} JSON object from LLM response for one gap."""
    raw = raw.strip()
    raw = re.sub(r"^```[^\n]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, dict) and data.get("front") and data.get("back"):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("Gap flashcard JSON parse failed for gap %r: %r", gap[:50], raw[:200])
    return None


# ---------------------------------------------------------------------------
# S154: Cloze deletion helpers and prompts
# ---------------------------------------------------------------------------

CLOZE_SYSTEM = (
    "You are a learning assistant creating cloze deletion (fill-in-the-blank) flashcards. "
    "Extract 3-5 key technical terms or concepts from the section text. "
    "For each term, produce a sentence that embeds the term using {{term}} syntax. "
    "Each sentence must make sense without the blank and use one or two blanks only. "
    "Output a JSON array starting with [ and ending with ]. "
    'Each element: {"cloze_text": "...", "source_excerpt": "..."}. '
    "cloze_text uses {{term}} markers. source_excerpt is a verbatim passage from the text. "
    "Write no explanation, preamble, or markdown fences."
)

CLOZE_USER_TMPL = (
    "Generate {count} cloze deletion cards from the text below.\n"
    "Each card must contain at least one {{{{term}}}} blank. "
    "Use exactly one or two blanks per sentence.\n"
    "Text:\n{text}\n\n"
    "JSON array:"
)

_CLOZE_BLANK_RE = re.compile(r"\{\{(.+?)\}\}")


def _parse_cloze_text(cloze_text: str) -> list[str]:
    """Return list of blank terms extracted from {{term}} markers in order."""
    return _CLOZE_BLANK_RE.findall(cloze_text)


def _build_cloze_question(cloze_text: str) -> str:
    """Replace {{term}} markers with [____] for list-view display."""
    return _CLOZE_BLANK_RE.sub("[____]", cloze_text)


def _parse_cloze_llm_response(raw: str) -> list[dict]:
    """Parse the LLM JSON array response for cloze cards.

    Filters out any element whose cloze_text has no {{}} markers (malformed).
    Returns only valid elements.
    """
    items = _parse_llm_response(raw, "cloze")
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cloze_text = str(item.get("cloze_text", "")).strip()
        if not cloze_text:
            continue
        blanks = _parse_cloze_text(cloze_text)
        if not blanks:
            logger.warning("Cloze item has no {{}} markers, skipping: %r", cloze_text[:100])
            continue
        valid.append(item)
    return valid


class FlashcardService:
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

        # When the caller supplies selected text, use it directly.
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

            combined_text, first_chunk_id = _build_text(chunks)
            if not combined_text:
                return []

        extra_instructions = ""
        if content_type == "book":
            extra_instructions = _BOOK_CONTENT_GUIDELINE

        prompt = FLASHCARD_USER_TMPL.format(
            count=count,
            difficulty=difficulty,
            difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
            extra_instructions=extra_instructions,
            text=combined_text,
        )

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

            raw = await llm.generate(prompt, system=FLASHCARD_SYSTEM, stream=False)
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
            if not question or not answer:
                continue
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
            )
            session.add(card)
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
            result = await session.execute(
                select(NoteModel).where(NoteModel.id.in_(note_ids))
            )
            notes = list(result.scalars().all())
        else:
            result = await session.execute(
                select(NoteModel).where(
                    text(
                        "EXISTS (SELECT 1 FROM json_each(notes.tags)"
                        " WHERE json_each.value = :tag)"
                    ).bindparams(tag=tag)
                )
            )
            notes = list(result.scalars().all())

        if not notes:
            return []

        combined_text = "\n\n".join(n.content for n in notes)[:_CHUNK_CHAR_LIMIT]
        if not combined_text:
            return []

        prompt = FLASHCARD_USER_TMPL.format(
            count=count,
            difficulty=difficulty,
            difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
            extra_instructions="",
            text=combined_text,
        )

        with trace_chain(
            "flashcard.generate_from_notes",
            input_value=f"tag={tag} note_ids={note_ids} count={count} difficulty={difficulty}",
        ) as span:
            span.set_attribute("flashcard.source", "note")
            span.set_attribute("flashcard.requested_count", count)
            span.set_attribute("flashcard.difficulty", difficulty)

            raw = await llm.generate(prompt, system=FLASHCARD_SYSTEM, stream=False)
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
            select(NoteCollectionModel).where(NoteCollectionModel.id == collection_id)
        )
        collection = coll_result.scalar_one_or_none()
        if collection is None:
            raise ValueError(f"Collection {collection_id!r} not found")

        deck_name = collection.name

        # 2. Fetch member note_ids
        member_result = await session.execute(
            select(NoteCollectionMemberModel.note_id).where(
                NoteCollectionMemberModel.collection_id == collection_id
            )
        )
        note_ids = [row[0] for row in member_result.all()]

        created = 0
        skipped = 0

        # 3. Process each note sequentially
        for note_id in note_ids:
            note_result = await session.execute(
                select(NoteModel).where(NoteModel.id == note_id)
            )
            note = note_result.scalar_one_or_none()
            if note is None or not note.content:
                continue

            content_hash = hashlib.sha256(
                note.content[:500].encode()
            ).hexdigest()[:16]

            if not force_regenerate:
                count_result = await session.execute(
                    select(func.count()).select_from(FlashcardModel).where(
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
            prompt = FLASHCARD_USER_TMPL.format(
                count=count_per_note,
                difficulty=difficulty,
                difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
                extra_instructions="",
                text=combined_text,
            )

            raw = await llm.generate(prompt, system=FLASHCARD_SYSTEM, stream=False)
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
                created += 1

            await session.commit()

        return {"created": created, "skipped": skipped, "deck": deck_name}

    async def generate_from_gaps(
        self,
        gaps: list[str],
        document_id: str,
        session: AsyncSession,
    ) -> tuple[int, list[str]]:
        """Generate one flashcard per gap using bounded LLM concurrency (semaphore=5).

        Skips gaps whose LLM response cannot be parsed.
        Raises litellm.ServiceUnavailableError if Ollama is unreachable.
        Returns (created_count, card_ids).
        """
        llm = get_llm_service()
        semaphore = asyncio.Semaphore(5)

        async def _generate_one(gap: str) -> FlashcardModel | None:
            async with semaphore:
                prompt = GAP_FLASHCARD_USER_TMPL.format(gap=gap)
                raw = await llm.generate(prompt, system=GAP_FLASHCARD_SYSTEM, stream=False)
                item = _parse_gap_flashcard(raw, gap)
                if item is None:
                    return None
                now = datetime.now(UTC)
                return FlashcardModel(
                    id=str(uuid.uuid4()),
                    document_id=document_id if document_id else None,
                    chunk_id=None,
                    source="gap",
                    deck="gaps",
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
                )

        raw_results = await asyncio.gather(
            *[_generate_one(g) for g in gaps], return_exceptions=True
        )
        # Re-raise Ollama-offline errors so the router can map them to 503.
        # Any other unexpected exception is logged and skipped (same policy as malformed JSON).
        for exc in raw_results:
            if isinstance(exc, (litellm.ServiceUnavailableError, litellm.APIConnectionError)):
                raise exc
            if isinstance(exc, BaseException):
                logger.warning(
                    "generate_from_gaps: unexpected error for a gap, skipping: %s", exc
                )
        results: list[FlashcardModel | None] = [
            r for r in raw_results if not isinstance(r, BaseException)
        ]
        cards = [r for r in results if r is not None]
        ids: list[str] = []
        for card in cards:
            session.add(card)
            ids.append(card.id)
        if cards:
            await session.commit()
            logger.info(
                "generate_from_gaps: created %d flashcards from %d gaps",
                len(cards),
                len(gaps),
            )
        return len(cards), ids


    async def generate_from_feynman_gaps(
        self,
        gaps: list[str],
        document_id: str,
        session: AsyncSession,
    ) -> tuple[int, list[str]]:
        """Generate concept_explanation flashcards from Feynman session gaps.

        Identical to generate_from_gaps but sets source='feynman',
        deck='feynman', flashcard_type='concept_explanation'.
        Raises litellm.ServiceUnavailableError if Ollama is unreachable.
        Returns (created_count, card_ids).
        """
        llm = get_llm_service()
        semaphore = asyncio.Semaphore(5)

        async def _generate_one(gap: str) -> FlashcardModel | None:
            async with semaphore:
                prompt = GAP_FLASHCARD_USER_TMPL.format(gap=gap)
                raw = await llm.generate(prompt, system=GAP_FLASHCARD_SYSTEM, stream=False)
                item = _parse_gap_flashcard(raw, gap)
                if item is None:
                    return None
                now = datetime.now(UTC)
                return FlashcardModel(
                    id=str(uuid.uuid4()),
                    document_id=document_id if document_id else None,
                    chunk_id=None,
                    source="feynman",
                    deck="feynman",
                    flashcard_type="concept_explanation",
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
                )

        raw_results = await asyncio.gather(
            *[_generate_one(g) for g in gaps], return_exceptions=True
        )
        for exc in raw_results:
            if isinstance(exc, (litellm.ServiceUnavailableError, litellm.APIConnectionError)):
                raise exc
            if isinstance(exc, BaseException):
                logger.warning(
                    "generate_from_feynman_gaps: unexpected error for a gap, skipping: %s", exc
                )
        results: list[FlashcardModel | None] = [
            r for r in raw_results if not isinstance(r, BaseException)
        ]
        cards = [r for r in results if r is not None]
        ids: list[str] = []
        for card in cards:
            session.add(card)
            ids.append(card.id)
        if cards:
            await session.commit()
            logger.info(
                "generate_from_feynman_gaps: created %d flashcards from %d gaps",
                len(cards),
                len(gaps),
            )
        return len(cards), ids

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
                raw = await llm.generate(prompt, system=GRAPH_FLASHCARD_SYSTEM, stream=False)
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

        raw_results = await asyncio.gather(
            *[_generate_one(a, b, label) for a, b, label, _conf in pairs],
            return_exceptions=True,
        )

        all_cards: list[FlashcardModel] = []
        for res in raw_results:
            if isinstance(res, (litellm.ServiceUnavailableError, litellm.APIConnectionError)):
                raise res  # type: ignore[misc]
            if isinstance(res, BaseException):
                logger.warning("generate_from_graph: error for a pair: %s", res)
                continue
            all_cards.extend(res)  # type: ignore[arg-type]

        for card in all_cards:
            session.add(card)
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

        with trace_chain(
            "flashcard.generate_technical",
            input_value=f"doc={document_id} scope={scope} count={count}",
        ) as span:
            span.set_attribute("flashcard.document_id", document_id)
            span.set_attribute("flashcard.scope", scope)
            span.set_attribute("flashcard.requested_count", count)
            span.set_attribute("flashcard.mode", "technical")

            raw = await llm.generate(prompt, system=TECH_FLASHCARD_SYSTEM, stream=False)
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

        with trace_chain(
            "flashcard.generate_cloze",
            input_value=f"section={section_id} count={count}",
        ) as span:
            span.set_attribute("flashcard.section_id", section_id)
            span.set_attribute("flashcard.requested_count", count)
            span.set_attribute("flashcard.mode", "cloze")

            raw = await llm.generate(prompt, system=CLOZE_SYSTEM, stream=False)
            items = _parse_cloze_llm_response(raw)

            if not items:
                logger.warning(
                    "generate_cloze: no valid cards on first attempt for section=%s, retrying",
                    section_id,
                )
                raw2 = await llm.generate(prompt, system=CLOZE_SYSTEM, stream=False)
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
