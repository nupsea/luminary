"""Gap detection service — identifies book concepts absent from user notes.

GapDetectorService.detect_gaps:
  1. Fetch notes by note_ids from SQLite.
  2. Build query string from first 200 chars of combined notes.
  3. Retrieve top-k book chunks via hybrid RRF retriever.
  4. Call LiteLLM with structured prompt, parse JSON response.
  5. Return GapReport(gaps, covered, query_used).
"""

import json
import logging
import re
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import database as _database_module  # indirect: get_session_factory is patched
from app.models import NoteModel
from app.services import retriever as _retriever_module  # indirect: get_retriever is patched
from app.services.llm import LLMUnavailableError, get_llm_service
from app.services.mastery_service import get_mastery_service
from app.types import GapReport

logger = logging.getLogger(__name__)

_NOTES_CAP = 3_000
_BOOK_CAP = 3_000
_ANALYSIS_SYSTEM = (
    "You are a learning gap analyst. "
    "Given learner notes and book passages on the same topic, "
    'return JSON: {"gaps": ["..."], "covered": ["..."]}. '
    "Each item is one sentence max. "
    "Gaps are key concepts from the passages absent or barely mentioned in the notes. "
    "Covered are concepts the notes address well. "
    "Be specific -- name actual concepts."
)


def _extract_json(raw: str) -> dict:
    """Extract the first JSON object from raw LLM output."""
    raw = raw.strip()
    raw = re.sub(r"^```[^\n]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


class GapDetectorService:
    async def detect_gaps(
        self,
        note_ids: list[str],
        document_id: str,
        k: int = 8,
        session: AsyncSession | None = None,
    ) -> GapReport:
        """Detect gaps between user notes and a book document.

        Args:
            note_ids: list of note IDs to analyse
            document_id: book document to compare against
            k: number of book chunks to retrieve
            session: SQLAlchemy async session

        Raises:
            ValueError: if no notes found for the given IDs
            LLMUnavailableError: if the LLM is unreachable
        """
        if session is None:

            async with _database_module.get_session_factory()() as s:
                return await self.detect_gaps(note_ids, document_id, k=k, session=s)

        result = await session.execute(select(NoteModel).where(NoteModel.id.in_(note_ids)))
        notes = list(result.scalars().all())
        if not notes:
            raise ValueError("No notes found for given IDs")

        notes_text = "\n\n".join(n.content for n in notes)[:_NOTES_CAP]
        query_used = notes_text[:200]


        chunks = await _retriever_module.get_retriever().retrieve(query_used, [document_id], k=k)
        book_context = "\n\n".join(c.text for c in chunks)[:_BOOK_CAP]

        user_msg = f"NOTES:\n{notes_text}\n\nBOOK PASSAGES:\n{book_context}"

        try:
            raw = await get_llm_service().complete(
                messages=[
                    {"role": "system", "content": _ANALYSIS_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
            )
        except LLMUnavailableError:
            raise

        parsed = _extract_json(raw.strip())
        if not parsed or "gaps" not in parsed or "covered" not in parsed:
            logger.warning("detect_gaps: unexpected LLM JSON shape, raw=%r", raw[:200])
            return GapReport(
                gaps=["Gap analysis unavailable -- could not parse LLM response"],
                covered=[],
                query_used=query_used,
                weak=[],
            )

        gaps = parsed.get("gaps", [])
        covered = parsed.get("covered", [])

        if not isinstance(gaps, list) or not isinstance(covered, list):
            logger.warning("detect_gaps: non-list gaps/covered, raw=%r", raw[:200])
            return GapReport(
                gaps=["Gap analysis unavailable -- could not parse LLM response"],
                covered=[],
                query_used=query_used,
                weak=[],
            )

        # identify weak concepts (in notes but mastery < 0.3)
        weak: list[str] = []
        try:

            mastery_svc = get_mastery_service()
            for concept in covered:
                cm = await mastery_svc.compute_mastery(concept, [document_id], session)
                if not cm.no_flashcards and cm.mastery < 0.3:
                    weak.append(concept)
        except Exception:
            logger.debug("detect_gaps: mastery weak-spot check failed, skipping", exc_info=True)

        logger.info(
            "detect_gaps: doc=%s notes=%d gaps=%d covered=%d weak=%d",
            document_id,
            len(notes),
            len(gaps),
            len(covered),
            len(weak),
        )
        return GapReport(gaps=gaps, covered=covered, query_used=query_used, weak=weak)


@lru_cache
def get_gap_detector() -> GapDetectorService:
    return GapDetectorService()
