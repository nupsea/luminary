"""Section-level summarization service for hierarchical ingestion pipeline.

Generates 1-2 sentence summaries for each qualifying section of a document,
grouped into at most 100 units to bound LLM call count for large books.
These summaries feed into the document-level summarization step (S76).
"""

import asyncio
import logging
import math
import uuid
from datetime import datetime

import litellm
from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.models import SectionModel, SectionSummaryModel

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Summarize the following passage in 1 to 2 sentences. "
    "Be specific about names, events, and arguments. "
    "Output only the summary."
)

MIN_PREVIEW_LEN = 200
MAX_UNITS = 100
TEXT_HARD_CAP = 4000


class SectionSummarizerService:
    async def generate(self, document_id: str, concurrency: int = 10) -> int:
        """Generate section summaries for the given document.

        Returns the number of SectionSummaryModel rows inserted.
        Returns 0 immediately (non-raising) if Ollama is unreachable.
        """
        # Fetch qualifying sections
        async with get_session_factory()() as session:
            result = await session.execute(
                select(SectionModel)
                .where(SectionModel.document_id == document_id)
                .order_by(SectionModel.section_order)
            )
            all_sections = list(result.scalars().all())

        qualifying = [s for s in all_sections if len(s.preview) >= MIN_PREVIEW_LEN]

        if not qualifying:
            logger.info(
                "section_summarizer: no qualifying sections (preview < %d chars)",
                MIN_PREVIEW_LEN,
                extra={"doc_id": document_id},
            )
            return 0

        # Group sections so total units <= MAX_UNITS
        units = self._group_sections(qualifying)

        logger.info(
            "section_summarizer: %d qualifying sections → %d units",
            len(qualifying),
            len(units),
            extra={"doc_id": document_id},
        )

        semaphore = asyncio.Semaphore(concurrency)
        model = get_settings().LITELLM_DEFAULT_MODEL
        total_inserted = 0

        async def _summarize_unit(unit_index: int, unit: dict) -> None:
            nonlocal total_inserted
            async with semaphore:
                try:
                    response = await litellm.acompletion(
                        model=model,
                        messages=[
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": unit["text"][:TEXT_HARD_CAP]},
                        ],
                        temperature=0.0,
                    )
                    summary_text = response.choices[0].message.content or ""
                except litellm.ServiceUnavailableError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "section_summarizer: unit %d failed, skipping: %s",
                        unit_index,
                        exc,
                        extra={"doc_id": document_id},
                    )
                    return

                row = SectionSummaryModel(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    section_id=unit.get("section_id"),
                    heading=unit["heading"][:200],
                    content=summary_text,
                    unit_index=unit_index,
                    created_at=datetime.utcnow(),
                )
                async with get_session_factory()() as session:
                    session.add(row)
                    await session.commit()

                total_inserted += 1

        try:
            await asyncio.gather(
                *[_summarize_unit(i, unit) for i, unit in enumerate(units)]
            )
        except litellm.ServiceUnavailableError:
            logger.warning(
                "section_summarizer: Ollama unreachable — skipping section summaries",
                extra={"doc_id": document_id},
            )
            return 0

        logger.info(
            "section_summarizer: inserted %d summaries",
            total_inserted,
            extra={"doc_id": document_id},
        )
        return total_inserted

    def _group_sections(self, sections: list[SectionModel]) -> list[dict]:
        """Group qualifying sections into at most MAX_UNITS summarization units."""
        count = len(sections)
        if count <= MAX_UNITS:
            return [
                {
                    "heading": s.heading,
                    "text": s.preview,
                    "section_id": s.id,
                }
                for s in sections
            ]

        group_size = math.ceil(count / MAX_UNITS)
        units: list[dict] = []
        for start in range(0, count, group_size):
            group = sections[start : start + group_size]
            heading = group[0].heading
            text = "\n\n".join(s.preview for s in group)
            units.append({"heading": heading, "text": text, "section_id": None})

        return units


_service: SectionSummarizerService | None = None


def get_section_summarizer_service() -> SectionSummarizerService:
    global _service
    if _service is None:
        _service = SectionSummarizerService()
    return _service
