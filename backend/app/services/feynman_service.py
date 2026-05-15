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

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FeynmanSessionModel,
    FeynmanTurnModel,
    SectionModel,
    SectionSummaryModel,
)
from app.services.feynman_strategies import (
    _FEYNMAN_OPENING_TMPL,
    _FEYNMAN_SYSTEM_TMPL,
    _MODEL_EXPLANATION_SYSTEM,
    _MODEL_EXPLANATION_USER_TMPL,
    _RUBRIC_SYSTEM,
    _RUBRIC_USER_TMPL,
    _SECTION_CONTEXT_CHAR_LIMIT,
    _fire_and_forget,
    _parse_gaps,
    _parse_key_points,
    _parse_rubric,
    _strip_gaps_block,
    _strip_key_points_block,
)
from app.services.llm import LLMUnavailableError, get_llm_service

logger = logging.getLogger(__name__)


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
                select(SectionModel).where(SectionModel.id == section_id).limit(1)
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

        await session.commit()  # Release read locks to prevent WAL deadlocks during LLM call

        try:
            raw = await llm.generate(
                prompt=opening_prompt,
                system=system_prompt,
                stream=False,
            )
        except LLMUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail="LLM unavailable. Check Settings — if using Ollama, run: ollama serve",
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
        await db_session.commit()  # Commit learner turn to release write locks during LLM stream

        accumulated = ""

        try:
            stream = await get_llm_service().stream_messages(messages=messages)
            async for delta in stream:
                if delta:
                    accumulated += delta
                    if "\ngaps:" not in accumulated and "gaps:" not in accumulated[-20:]:
                        yield f"data: {json.dumps({'token': delta})}\n\n"

        except LLMUnavailableError as exc:
            logger.warning("Feynman stream_turn: LLM unavailable: %s", exc)
            await db_session.rollback()
            error_msg = "LLM unavailable. Check Settings — if using Ollama, run: ollama serve"
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

        # Collect all turns (tutor for gaps, learner for rubric transcript)
        turns_result = await db_session.execute(
            select(FeynmanTurnModel).where(
                FeynmanTurnModel.session_id == session_id,
            )
        )
        all_turns = list(turns_result.scalars().all())
        tutor_turns = [t for t in all_turns if t.role == "tutor"]
        learner_turns = [t for t in all_turns if t.role == "learner"]

        all_gaps: list[str] = []
        seen: set[str] = set()
        for turn in tutor_turns:
            for gap in turn.gaps_identified or []:
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
            except LLMUnavailableError:
                logger.warning(
                    "Feynman complete_session: LLM unavailable; skipping flashcard generation"
                )

        # Fire-and-forget objective coverage update
        from app.services.objective_tracker import get_objective_tracker_service  # noqa: PLC0415

        tracker = get_objective_tracker_service()
        _fire_and_forget(tracker.update_coverage(feynman_session.document_id))

        # S156: rubric evaluation using full learner transcript as explanation
        rubric_dict: dict | None = None
        try:
            learner_texts = [t.content for t in learner_turns if t.content]
            explanation = "\n\n".join(learner_texts) if learner_texts else ""
            if explanation:
                section_context = await self._get_section_context(
                    feynman_session.document_id,
                    feynman_session.section_id,
                    db_session,
                )
                rubric_prompt = _RUBRIC_USER_TMPL.format(
                    source_context=section_context,
                    explanation=explanation,
                )
                llm = get_llm_service()
                raw_rubric = await llm.generate(prompt=rubric_prompt, system=_RUBRIC_SYSTEM)
                rubric_dict = _parse_rubric(raw_rubric)
                feynman_session.rubric_json = rubric_dict
                await db_session.commit()
        except Exception:  # noqa: BLE001 -- never raise 500 from rubric evaluation
            logger.warning("Feynman rubric evaluation failed for session=%s", session_id)
            rubric_dict = None

        logger.info(
            "Feynman session completed: session_id=%s gaps=%d flashcards=%d",
            session_id,
            len(all_gaps),
            len(flashcard_ids),
        )
        return {"gap_count": len(all_gaps), "flashcard_ids": flashcard_ids, "rubric": rubric_dict}

    async def generate_model_explanation(
        self,
        session_id: str,
        db_session: AsyncSession,
    ) -> AsyncGenerator[str]:
        """Generate and stream a model explanation for the Feynman session concept.

        Yields SSE data strings:
          data: {"token": "..."}\n\n        -- streaming tokens
          data: {"done": true, "explanation": "...", "key_points": [...]}\n\n
          data: {"error": "llm_unavailable", "message": "..."}\n\n

        Persists model_explanation_text and key_points_json on the session row.
        """
        result = await db_session.execute(
            select(FeynmanSessionModel).where(FeynmanSessionModel.id == session_id)
        )
        feynman_session = result.scalar_one_or_none()
        if feynman_session is None:
            not_found = {"error": "not_found", "message": "Feynman session not found"}
            yield f"data: {json.dumps(not_found)}\n\n"
            return

        section_context = await self._get_section_context(
            feynman_session.document_id,
            feynman_session.section_id,
            db_session,
        )

        prompt = _MODEL_EXPLANATION_USER_TMPL.format(
            concept=feynman_session.concept,
            section_context=section_context,
        )

        await db_session.commit()  # Release read locks to prevent WAL deadlocks during LLM stream

        accumulated = ""

        try:
            stream = await get_llm_service().stream_messages(
                messages=[
                    {"role": "system", "content": _MODEL_EXPLANATION_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            async for delta in stream:
                if delta:
                    accumulated += delta
                    tail = accumulated[-20:]
                    kp_started = "\nkey_points:" in accumulated or "key_points:" in tail
                    if not kp_started:
                        yield f"data: {json.dumps({'token': delta})}\n\n"

        except LLMUnavailableError as exc:
            logger.warning("generate_model_explanation: LLM unavailable: %s", exc)
            await db_session.rollback()
            error_msg = "LLM unavailable. Check Settings — if using Ollama, run: ollama serve"
            yield f"data: {json.dumps({'error': 'llm_unavailable', 'message': error_msg})}\n\n"
            return

        key_points = _parse_key_points(accumulated)
        explanation_text = _strip_key_points_block(accumulated)

        # Persist on session row
        feynman_session.model_explanation_text = explanation_text
        feynman_session.key_points_json = key_points
        try:
            await db_session.commit()
        except Exception:  # noqa: BLE001
            logger.warning("generate_model_explanation: commit failed for session=%s", session_id)
            await db_session.rollback()

        logger.info(
            "Model explanation generated: session_id=%s key_points=%d",
            session_id,
            len(key_points),
        )

        done_event = {"done": True, "explanation": explanation_text, "key_points": key_points}
        yield f"data: {json.dumps(done_event)}\n\n"

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
                "section_id": s.section_id,
            }
            for s in sessions
        ]


_service: FeynmanService | None = None


def get_feynman_service() -> FeynmanService:
    global _service  # noqa: PLW0603
    if _service is None:
        _service = FeynmanService()
    return _service
