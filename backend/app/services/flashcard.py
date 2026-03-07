"""Flashcard generation service — LLM-based QA flashcard generation."""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, FlashcardModel, SectionModel
from app.services.llm import get_llm_service
from app.telemetry import trace_chain

logger = logging.getLogger(__name__)

FLASHCARD_SYSTEM = (
    "You are a learning assistant creating flashcards for active recall. "
    "Generate questions that test understanding of the passage. "
    "Prefer questions that: (1) ask the learner to explain a concept in their own words"
    " (comprehension), "
    "(2) apply a concept to a new situation (application), "
    "(3) distinguish between similar concepts (analysis), "
    "or (4) evaluate a claim or argument (evaluation). "
    "AVOID: trivia questions about exact wording, hypothetical questions not grounded"
    " in the passage, "
    "questions whose answer is not in the text, yes/no questions. "
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
    "Generate {count} flashcard pairs from the text below.\n"
    "Each card must be answerable from the provided text only.\n"
    'Format: [{{"question": "...", "answer": "...", "source_excerpt": "..."}}]\n'
    "The \"answer\" field may use Markdown (bold, lists) for clarity.\n\n"
    "Text:\n{text}\n\n"
    "JSON array:"
)

# Keep well within mistral's 8K-token context (~4 chars/token, reserve ~2K for prompt+response)
_CHUNK_CHAR_LIMIT = 5_000


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

        with trace_chain(
            "flashcard.generate",
            input_value=f"doc={document_id} scope={scope} count={count}",
        ) as span:
            span.set_attribute("flashcard.document_id", document_id)
            span.set_attribute("flashcard.scope", scope)
            span.set_attribute("flashcard.requested_count", count)
            if section_heading:
                span.set_attribute("flashcard.section_heading", section_heading)

            raw = await llm.generate(prompt, system=FLASHCARD_SYSTEM, stream=False)
            cards_data = _parse_llm_response(raw, document_id)
            span.set_attribute("flashcard.generated_count", len(cards_data))

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
