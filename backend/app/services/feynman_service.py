"""Feynman technique session service (S144).

Manages guided explanation sessions where a Socratic tutor:
1. Asks the learner to explain a concept from scratch
2. Identifies gaps in the explanation
3. After 3 exchanges, generates flashcards targeting the gaps

Usage:
  svc = get_feynman_service()
  session_row, opening = await svc.create_session(doc_id, section_id, concept, db)
  async for event in svc.stream_turn(session_id, learner_message, db):
      ...  # SSE data strings
  result = await svc.complete_session(session_id, db)
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import litellm
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    FeynmanSessionModel,
    FeynmanTurnModel,
    SectionModel,
    SectionSummaryModel,
)
from app.services.llm import get_llm_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_FEYNMAN_SYSTEM_TMPL = (
    "You are a Socratic tutor using the Feynman technique. "
    "The learner is studying the concept: {concept}. "
    "Reference material:\n{section_context}\n\n"
    "For each learner message: give specific feedback on what they got right, "
    "identify misunderstandings or missing concepts, "
    "then ask one targeted follow-up question. "
    "NEVER give the answer directly -- guide the learner to discover it. "
    "At the END of your response, output a line: gaps: [\"gap1\", \"gap2\"] "
    "listing concepts the learner misunderstood or omitted in this message. "
    "Output an empty list if the explanation was complete. "
    "Keep the gaps list concise (1-4 items max)."
)

_FEYNMAN_OPENING_TMPL = (
    "Start the Feynman session. Ask the learner to explain '{concept}' as if "
    "teaching it to someone who has never heard of it. "
    "Be encouraging and specific about what you want them to explain."
)

# Max chars for section context included in the system prompt
_SECTION_CONTEXT_CHAR_LIMIT = 3000

# Strong reference set for fire-and-forget background tasks
_background_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:  # type: ignore[no-untyped-def]
    """Schedule a coroutine as a fire-and-forget background task with strong ref."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ---------------------------------------------------------------------------
# Gap parsing
# ---------------------------------------------------------------------------


def _parse_gaps(raw: str) -> list[str]:
    """Extract the gaps JSON list from the end of a tutor response.

    Looks for a line starting with 'gaps:' and parses the JSON array.
    Returns [] if no gaps block is found or parsing fails.
    """
    m = re.search(r"gaps:\s*(\[.*?\])", raw, re.DOTALL)
    if not m:
        return []
    try:
        result = json.loads(m.group(1))
        if isinstance(result, list):
            return [str(g) for g in result if g]
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def _strip_gaps_block(raw: str) -> str:
    """Remove the trailing 'gaps: [...]' line from a tutor response for display."""
    # Find the last occurrence of 'gaps:' line and strip from there
    idx = raw.rfind("\ngaps:")
    if idx == -1:
        idx = raw.rfind("gaps:")
        if idx == 0 or (idx > 0 and raw[idx - 1] == "\n"):
            return raw[:idx].rstrip()
        return raw
    return raw[:idx].rstrip()


# ---------------------------------------------------------------------------
# FeynmanService
# ---------------------------------------------------------------------------


class FeynmanService:
    """Manages Feynman technique sessions."""

    async def _get_section_context(
        self,
        document_id: str,
        section_id: str | None,
        session: AsyncSession,
    ) -> str:
        """Fetch section summary or section preview for the tutor system prompt."""
        if section_id:
            # Try SectionSummaryModel first
            result = await session.execute(
                select(SectionSummaryModel)
                .where(SectionSummaryModel.document_id == document_id)
                .where(SectionSummaryModel.section_id == section_id)
                .limit(1)
            )
            summary = result.scalar_one_or_none()
            if summary and summary.content:
                return summary.content[:_SECTION_CONTEXT_CHAR_LIMIT]

            # Fallback to section preview
            result2 = await session.execute(
                select(SectionModel)
                .where(SectionModel.id == section_id)
                .limit(1)
            )
            section = result2.scalar_one_or_none()
            if section and section.preview:
                return section.preview[:_SECTION_CONTEXT_CHAR_LIMIT]

        return "(No reference material available for this section.)"

    def _build_system_prompt(self, concept: str, section_context: str) -> str:
        """Build the LLM system prompt for a Feynman tutor session."""
        return _FEYNMAN_SYSTEM_TMPL.format(
            concept=concept,
            section_context=section_context,
        )

    async def create_session(
        self,
        document_id: str,
        section_id: str | None,
        concept: str,
        session: AsyncSession,
    ) -> tuple[FeynmanSessionModel, str]:
        """Create a new Feynman session and return the opening tutor message.

        Raises HTTPException(503) if Ollama is unreachable.
        """
        llm = get_llm_service()
        section_context = await self._get_section_context(document_id, section_id, session)
        system_prompt = self._build_system_prompt(concept, section_context)

        opening_prompt = _FEYNMAN_OPENING_TMPL.format(concept=concept)

        try:
            raw = await llm.generate(
                prompt=opening_prompt,
                system=system_prompt,
                stream=False,
            )
        except (litellm.ServiceUnavailableError, litellm.APIConnectionError) as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Ollama is not running. "
                    "Start Ollama to use Feynman mode: ollama serve"
                ),
            ) from exc

        # Strip any accidental gaps: block from opening message
        opening_message = _strip_gaps_block(str(raw))

        # Persist session row
        session_row = FeynmanSessionModel(
            id=str(uuid.uuid4()),
            document_id=document_id,
            section_id=section_id,
            concept=concept,
            status="active",
            created_at=datetime.now(UTC),
        )
        session.add(session_row)

        # Persist opening tutor turn
        opening_turn = FeynmanTurnModel(
            id=str(uuid.uuid4()),
            session_id=session_row.id,
            turn_index=0,
            role="tutor",
            content=opening_message,
            gaps_identified=[],
            created_at=datetime.now(UTC),
        )
        session.add(opening_turn)

        await session.commit()
        await session.refresh(session_row)

        logger.info(
            "Feynman session created: session_id=%s document_id=%s concept=%r",
            session_row.id,
            document_id,
            concept[:50],
        )
        return session_row, opening_message

    async def stream_turn(
        self,
        session_id: str,
        learner_content: str,
        db_session: AsyncSession,
    ) -> AsyncGenerator[str]:
        """Stream a tutor response to a learner message.

        Yields SSE data strings:
          data: {"token": "..."}\n\n   — streaming tokens
          data: {"done": true, "gaps": [...]}\n\n  — completion event
          data: {"error": "llm_unavailable", "message": "..."}\n\n  — on 503

        The 'done' payload contains stripped text (gaps: block removed).
        """
        # Load session
        result = await db_session.execute(
            select(FeynmanSessionModel).where(FeynmanSessionModel.id == session_id)
        )
        feynman_session = result.scalar_one_or_none()
        if feynman_session is None:
            raise HTTPException(status_code=404, detail="Feynman session not found")

        # Load all prior turns for conversation history
        turns_result = await db_session.execute(
            select(FeynmanTurnModel)
            .where(FeynmanTurnModel.session_id == session_id)
            .order_by(FeynmanTurnModel.turn_index)
        )
        turns = list(turns_result.scalars().all())
        turn_count = len(turns)

        # Fetch section context for system prompt
        section_context = await self._get_section_context(
            feynman_session.document_id,
            feynman_session.section_id,
            db_session,
        )
        system_prompt = self._build_system_prompt(feynman_session.concept, section_context)

        # Build conversation messages
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for turn in turns:
            role = "assistant" if turn.role == "tutor" else "user"
            # Strip gaps block from history so model doesn't repeat the format
            content = _strip_gaps_block(turn.content)
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": learner_content})

        # Persist learner turn
        learner_turn = FeynmanTurnModel(
            id=str(uuid.uuid4()),
            session_id=session_id,
            turn_index=turn_count,
            role="learner",
            content=learner_content,
            gaps_identified=None,
            created_at=datetime.now(UTC),
        )
        db_session.add(learner_turn)
        await db_session.flush()

        # Stream LLM response
        accumulated = ""
        model = get_settings().LITELLM_DEFAULT_MODEL

        try:
            stream_resp = await litellm.acompletion(
                model=model,
                messages=messages,
                stream=True,
            )
            async for chunk in stream_resp:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    accumulated += delta
                    # Stream tokens but suppress the gaps: block once it starts
                    if "\ngaps:" not in accumulated and "gaps:" not in accumulated[-20:]:
                        yield f"data: {json.dumps({'token': delta})}\n\n"

        except (litellm.ServiceUnavailableError, litellm.APIConnectionError) as exc:
            logger.warning("Feynman stream_turn: Ollama unavailable: %s", exc)
            # Learner turn was flushed but not committed; roll back so no orphan row
            await db_session.rollback()
            error_msg = (
                "Ollama is not running. "
                "Start Ollama to use Feynman mode: ollama serve"
            )
            yield f"data: {json.dumps({'error': 'llm_unavailable', 'message': error_msg})}\n\n"
            return

        # Parse gaps and persist tutor turn
        gaps = _parse_gaps(accumulated)
        display_text = _strip_gaps_block(accumulated)

        tutor_turn = FeynmanTurnModel(
            id=str(uuid.uuid4()),
            session_id=session_id,
            turn_index=turn_count + 1,
            role="tutor",
            content=accumulated,  # Store raw (with gaps block) for later parsing
            gaps_identified=gaps,
            created_at=datetime.now(UTC),
        )
        db_session.add(tutor_turn)
        await db_session.commit()

        logger.info(
            "Feynman turn completed: session_id=%s turn=%d gaps=%d",
            session_id,
            turn_count + 1,
            len(gaps),
        )

        yield f"data: {json.dumps({'done': True, 'answer': display_text, 'gaps': gaps})}\n\n"

    async def complete_session(
        self,
        session_id: str,
        db_session: AsyncSession,
    ) -> dict:
        """Complete a Feynman session: generate gap flashcards and update objective coverage.

        Returns {"gap_count": N, "flashcard_ids": [...]}
        """
        result = await db_session.execute(
            select(FeynmanSessionModel).where(FeynmanSessionModel.id == session_id)
        )
        feynman_session = result.scalar_one_or_none()
        if feynman_session is None:
            raise HTTPException(status_code=404, detail="Feynman session not found")

        # Mark session complete
        feynman_session.status = "complete"

        # Collect all gaps from tutor turns
        turns_result = await db_session.execute(
            select(FeynmanTurnModel)
            .where(
                FeynmanTurnModel.session_id == session_id,
                FeynmanTurnModel.role == "tutor",
            )
        )
        turns = list(turns_result.scalars().all())

        all_gaps: list[str] = []
        seen: set[str] = set()
        for turn in turns:
            for gap in (turn.gaps_identified or []):
                if gap and gap not in seen:
                    seen.add(gap)
                    all_gaps.append(gap)

        await db_session.commit()

        flashcard_ids: list[str] = []

        if all_gaps:
            from app.services.flashcard import get_flashcard_service  # noqa: PLC0415
            fc_svc = get_flashcard_service()
            try:
                _count, flashcard_ids = await fc_svc.generate_from_feynman_gaps(
                    gaps=all_gaps,
                    document_id=feynman_session.document_id,
                    session=db_session,
                )
            except (litellm.ServiceUnavailableError, litellm.APIConnectionError):
                logger.warning(
                    "Feynman complete_session: Ollama unavailable; skipping flashcard generation"
                )

        # Fire-and-forget objective coverage update
        from app.services.objective_tracker import get_objective_tracker_service  # noqa: PLC0415
        tracker = get_objective_tracker_service()
        _fire_and_forget(tracker.update_coverage(feynman_session.document_id))

        logger.info(
            "Feynman session completed: session_id=%s gaps=%d flashcards=%d",
            session_id,
            len(all_gaps),
            len(flashcard_ids),
        )
        return {"gap_count": len(all_gaps), "flashcard_ids": flashcard_ids}

    async def list_sessions(
        self,
        document_id: str,
        db_session: AsyncSession,
    ) -> list[dict]:
        """Return all Feynman sessions for a document with gap_count per session."""
        sessions_result = await db_session.execute(
            select(FeynmanSessionModel)
            .where(FeynmanSessionModel.document_id == document_id)
            .order_by(FeynmanSessionModel.created_at.desc())
        )
        sessions = list(sessions_result.scalars().all())

        if not sessions:
            return []

        # Fetch all tutor turns for these sessions in one query
        session_ids = [s.id for s in sessions]
        turns_result = await db_session.execute(
            select(FeynmanTurnModel).where(
                FeynmanTurnModel.session_id.in_(session_ids),
                FeynmanTurnModel.role == "tutor",
            )
        )
        turns = list(turns_result.scalars().all())

        # Compute gap_count per session
        gap_counts: dict[str, int] = {}
        for turn in turns:
            sid = turn.session_id
            gaps = turn.gaps_identified or []
            gap_counts[sid] = gap_counts.get(sid, 0) + len(gaps)

        return [
            {
                "id": s.id,
                "concept": s.concept,
                "status": s.status,
                "gap_count": gap_counts.get(s.id, 0),
                "created_at": s.created_at,
            }
            for s in sessions
        ]


_service: FeynmanService | None = None


def get_feynman_service() -> FeynmanService:
    global _service  # noqa: PLW0603
    if _service is None:
        _service = FeynmanService()
    return _service
