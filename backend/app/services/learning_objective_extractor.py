"""LiteLLM-based learning objective extraction service.

Extracts learning objectives from chapter-introduction sections of tech books.
Results are stored as LearningObjectiveModel rows (idempotent: delete+insert per doc).
"""

import json
import logging
import re
import uuid

from sqlalchemy import delete

from app.database import get_session_factory
from app.models import LearningObjectiveModel
from app.services import llm as _llm_module  # indirect: get_llm_service is patched
from app.services.llm import LLMUnavailableError

logger = logging.getLogger(__name__)


class LearningObjectiveExtractorService:
    """Extract and store learning objectives for a document section."""

    async def extract(
        self,
        document_id: str,
        section_id: str,
        section_heading: str,
        text: str,
    ) -> list[str]:
        """Extract learning objectives from section text via LLM.

        Returns a list of objective strings (possibly empty).
        Never raises — returns [] on any failure.
        """

        prompt = (
            "Extract learning objectives from the following chapter introduction.\n"
            "Return a JSON array of strings. Maximum 5 items. Each item is one sentence.\n"
            "If none are present, return an empty array [].\n\n"
            f"Text:\n{text[:600]}"
        )
        try:
            raw = await _llm_module.get_llm_service().complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                background=True,
            )
            return _parse_objectives(raw)
        except LLMUnavailableError as exc:
            logger.warning(
                "LLM unavailable during objective extraction for section %s: %s",
                section_id,
                exc,
            )
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Objective extraction failed for section %s: %s",
                section_id,
                exc,
            )
            return []

    async def store_all(
        self,
        document_id: str,
        section_objectives: list[tuple[str, list[str]]],
    ) -> None:
        """Write LearningObjectiveModel rows for all sections; idempotent per document.

        Accepts a list of (section_id, objectives) pairs.
        Deletes ALL existing objectives for the document once, then inserts all new rows,
        ensuring re-ingestion does not duplicate rows and multi-section extraction
        does not clobber earlier sections' results.
        """
        if not section_objectives:
            return



        async with get_session_factory()() as session:
            await session.execute(
                delete(LearningObjectiveModel).where(
                    LearningObjectiveModel.document_id == document_id
                )
            )
            for section_id, objectives in section_objectives:
                for raw_text in objectives:
                    clean = raw_text.strip()
                    if not clean:
                        continue
                    session.add(
                        LearningObjectiveModel(
                            id=str(uuid.uuid4()),
                            document_id=document_id,
                            section_id=section_id,
                            text=clean,
                            covered=False,
                        )
                    )
            await session.commit()


def _parse_objectives(raw: str) -> list[str]:
    """Parse a JSON array from LLM output. Returns [] on parse failure."""
    # Find first [...] in the output
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
        if isinstance(data, list):
            return [str(item) for item in data if item]
    except Exception:  # noqa: BLE001
        pass
    return []
