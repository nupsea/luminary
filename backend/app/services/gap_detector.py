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

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import NoteModel
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
            litellm.ServiceUnavailableError: if Ollama is unreachable
        """
        if session is None:
            from app.database import get_session_factory  # noqa: PLC0415

            async with get_session_factory()() as s:
                return await self.detect_gaps(note_ids, document_id, k=k, session=s)

        result = await session.execute(
            select(NoteModel).where(NoteModel.id.in_(note_ids))
        )
        notes = list(result.scalars().all())
        if not notes:
            raise ValueError("No notes found for given IDs")

        notes_text = "\n\n".join(n.content for n in notes)[:_NOTES_CAP]
        query_used = notes_text[:200]

        from app.services.retriever import get_retriever  # noqa: PLC0415

        chunks = await get_retriever().retrieve(query_used, [document_id], k=k)
        book_context = "\n\n".join(c.text for c in chunks)[:_BOOK_CAP]

        model = get_settings().LITELLM_DEFAULT_MODEL
        user_msg = f"NOTES:\n{notes_text}\n\nBOOK PASSAGES:\n{book_context}"

        try:
            response = await litellm.acompletion(
                model=model,
                messages=[
                    {"role": "system", "content": _ANALYSIS_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
            )
        except (
            litellm.ServiceUnavailableError,
            litellm.APIConnectionError,
        ) as exc:
            raise exc  # propagated to API layer

        raw = (response.choices[0].message.content or "").strip()
        parsed = _extract_json(raw)
        if not parsed or "gaps" not in parsed or "covered" not in parsed:
            logger.warning("detect_gaps: unexpected LLM JSON shape, raw=%r", raw[:200])
            return GapReport(
                gaps=["Gap analysis unavailable -- could not parse LLM response"],
                covered=[],
                query_used=query_used,
            )

        gaps = parsed.get("gaps", [])
        covered = parsed.get("covered", [])

        if not isinstance(gaps, list) or not isinstance(covered, list):
            logger.warning("detect_gaps: non-list gaps/covered, raw=%r", raw[:200])
            return GapReport(
                gaps=["Gap analysis unavailable -- could not parse LLM response"],
                covered=[],
                query_used=query_used,
            )

        logger.info(
            "detect_gaps: doc=%s notes=%d gaps=%d covered=%d",
            document_id,
            len(notes),
            len(gaps),
            len(covered),
        )
        return GapReport(gaps=gaps, covered=covered, query_used=query_used)


@lru_cache
def get_gap_detector() -> GapDetectorService:
    return GapDetectorService()
