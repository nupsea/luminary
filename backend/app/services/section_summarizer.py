"""Section-level summarization service for hierarchical ingestion pipeline.

Generates 1-2 sentence summaries for each qualifying section of a document,
grouped into at most 100 units to bound LLM call count for large books.
These summaries feed into the document-level summarization step (S76).
"""

import asyncio
import logging
import math
import uuid
from datetime import UTC, datetime

import litellm
from sqlalchemy import select

from app.database import get_session_factory
from app.models import SectionModel, SectionSummaryModel

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Summarize the following passage in 2 to 3 sentences. "
    "Be specific about names, events, and arguments. "
    "Output only the summary."
)

MIN_PREVIEW_LEN = 200
# 30 units per document: enough thematic coverage while keeping Ollama call count
# manageable (100 was causing >30 min ingestion times on local hardware).
MAX_UNITS = 30
TEXT_HARD_CAP = 10000

# Case-insensitive signals that indicate a metadata/legal section
_METADATA_SIGNALS = [
    "project gutenberg",
    "terms of use",
    "license",
    "disclaimer",
    "copyright",
    "trademark",
    "legal",
    "distribution",
    "reproduction",
    "permitted use",
    "electronic work",
    "archive foundation",
]


def _is_metadata_section(heading: str, text: str) -> bool:
    """Return True if this section is a metadata/legal section to be skipped.

    Checks the heading and the first 500 chars of text for known signals.
    Pure function — no I/O, no imports from other app layers.
    """
    combined = (heading + " " + text[:500]).lower()
    return any(signal in combined for signal in _METADATA_SIGNALS)


class SectionSummarizerService:
    async def generate(self, document_id: str, concurrency: int = 10) -> int:
        """Generate section summaries for the given document.

        Returns the number of SectionSummaryModel rows inserted.
        Returns 0 immediately (non-raising) if Ollama is unreachable.
        """
        # Invalidate the _section_reduce cache so pregenerate() recomputes the
        # document summary using the freshly generated section summaries.
        from app.services.summarizer import get_summarization_service  # noqa: PLC0415

        await get_summarization_service().invalidate_section_reduce_cache(document_id)

        # Fetch qualifying sections
        async with get_session_factory()() as session:
            result = await session.execute(
                select(SectionModel)
                .where(SectionModel.document_id == document_id)
                .order_by(SectionModel.section_order)
            )
            all_sections = list(result.scalars().all())

        # Filter metadata/legal sections before preview length check
        non_metadata: list[SectionModel] = []
        for s in all_sections:
            if _is_metadata_section(s.heading, s.preview):
                logger.debug(
                    "Skipping metadata section: %s",
                    s.heading,
                    extra={"doc_id": document_id},
                )
            else:
                non_metadata.append(s)

        qualifying = [s for s in non_metadata if len(s.preview) >= MIN_PREVIEW_LEN]

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
        total_inserted = 0

        async def _summarize_unit(unit_index: int, unit: dict) -> None:
            from app.services.settings_service import get_litellm_kwargs  # noqa: PLC0415

            nonlocal total_inserted
            async with semaphore:
                try:
                    response = await litellm.acompletion(
                        **get_litellm_kwargs(background=True),
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
                    created_at=datetime.now(UTC),
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
                "section_summarizer: LLM unavailable — skipping section summaries",
                extra={"doc_id": document_id},
            )
            return 0

        logger.info(
            "section_summarizer: inserted %d summaries",
            total_inserted,
            extra={"doc_id": document_id},
        )

        # Enqueue web_refs enrichment only when at least one section summary was written.
        # This guarantees the source data exists before the enrichment job runs.
        if total_inserted > 0:
            await self._enqueue_web_refs(document_id)

        return total_inserted

    async def _enqueue_web_refs(self, document_id: str) -> None:
        """Enqueue a web_refs enrichment job for document_id.

        Deduplication: skip if a pending/running job already exists.
        Non-fatal: exceptions are logged and swallowed.
        """
        try:
            from sqlalchemy import func as _func  # noqa: PLC0415
            from sqlalchemy import select as _select  # noqa: PLC0415

            from app.models import EnrichmentJobModel as _EJM  # noqa: PLC0415

            async with get_session_factory()() as session:
                dup_result = await session.execute(
                    _select(_func.count(_EJM.id)).where(
                        _EJM.document_id == document_id,
                        _EJM.job_type == "web_refs",
                        _EJM.status.in_(["pending", "running"]),
                    )
                )
                if dup_result.scalar_one() > 0:
                    logger.debug(
                        "section_summarizer: web_refs job already pending/running for doc=%s",
                        document_id,
                    )
                    return

                job = _EJM(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    job_type="web_refs",
                    status="pending",
                    created_at=datetime.now(UTC),
                )
                session.add(job)
                await session.commit()
                logger.info(
                    "section_summarizer: enqueued web_refs job for doc=%s", document_id
                )
        except Exception as exc:
            logger.warning(
                "section_summarizer: failed to enqueue web_refs for doc=%s: %s",
                document_id,
                exc,
            )

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
