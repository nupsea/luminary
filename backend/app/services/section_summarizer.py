"""Section-level summarization service for hierarchical ingestion pipeline.

Generates a 1-2 sentence summary per qualifying section. Retrieval, suggestions,
Feynman and concept linking all look these up per section, so a section without
one is absent from each. Grouping is therefore only for the inline path.
"""

import asyncio
import logging
import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select

from app.database import get_session_factory
from app.models import EnrichmentJobModel, SectionModel, SectionSummaryModel
from app.services.llm import LLMUnavailableError, get_llm_service

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

# Unit count alone does not bound the work; total prompt characters do. The
# per-unit cap shrinks as a document grows, trading detail for a bounded wait.
TOTAL_TEXT_BUDGET = 90000
MIN_UNIT_CHARS = 1500

# Above this many qualifying sections, summarisation moves off the ingestion
# path entirely and runs after the document is readable.
#
# A count is the wrong unit for the decision and this number had no measured
# basis. On a CPU-only host one summary is an LLM call at 5-7 tok/s: measured
# end to end in Docker, alice_in_wonderland.txt produced 12 qualifying sections
# and spent 330 of its 390-second ingest on them -- comfortably under 40, so
# they ran inline and held `stage=complete` for five and a half minutes on a
# document that was already readable. At 40 the same host would block for
# roughly twenty.
#
# So the gate is the model, not the count: see `defer_section_summaries`.
DEFER_ABOVE_SECTIONS = 40


def defer_section_summaries(qualifying_sections: int, model: str) -> bool:
    """Whether summarisation should run behind `stage=complete`.

    Local generation is the cost. A hosted model answers in a second or two and
    a small document is genuinely nicer with its summaries already there, so the
    count threshold still applies to cloud. A local model on CPU makes every
    section minutes of blocked ingest, and the deferred path exists precisely
    because the document does not need them to be readable.
    """
    from app.services.connectivity import is_cloud_model  # noqa: PLC0415

    if not is_cloud_model(model):
        return True
    return qualifying_sections > DEFER_ABOVE_SECTIONS


def unit_text_cap(unit_count: int) -> int:
    """Per-unit character cap for a document split into `unit_count` units."""
    if unit_count <= 0:
        return TEXT_HARD_CAP
    return max(MIN_UNIT_CHARS, min(TEXT_HARD_CAP, TOTAL_TEXT_BUDGET // unit_count))

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


def section_text(section: SectionModel) -> str:
    """The section's reading text.

    `body` is uncapped (I-29); `preview` is a 10,000-character snippet, and
    summarising from it dropped 47.5% of `art_of_unix`. `unit_text_cap` is the
    intended bound; preview's cap was a second, invisible one underneath it.

    The fallback covers rows written before `body` existed, where the snippet is
    the only text there is. Re-ingesting restores them; this is not a repair.
    """
    return section.body or section.preview


class SectionSummarizerService:
    async def qualifying_section_count(self, document_id: str) -> int:
        """How many sections `generate` would summarise, without calling an LLM.

        Lets the ingestion graph decide whether to defer, using the same filters
        the run itself applies rather than a raw section count.
        """
        async with get_session_factory()() as session:
            result = await session.execute(
                select(SectionModel).where(SectionModel.document_id == document_id)
            )
            sections = list(result.scalars().all())
        return sum(
            1
            for s in sections
            if len(section_text(s)) >= MIN_PREVIEW_LEN
            and not _is_metadata_section(s.heading, s.preview)
        )

    async def generate(
        self, document_id: str, concurrency: int = 3, *, per_section: bool = False
    ) -> int:
        """Generate section summaries for the given document.

        `per_section` gives every qualifying section its own summary rather
        than grouping into MAX_UNITS. Consumers look summaries up per section,
        so grouping leaves the unsummarised ones invisible to them; background
        callers pass True and trade time for coverage.

        Returns the number of SectionSummaryModel rows inserted.
        Returns 0 immediately (non-raising) if Ollama is unreachable.
        """
        # Invalidate the _section_reduce cache so pregenerate() recomputes the
        # document summary using the freshly generated section summaries.

        # Circular: app.services.summarizer imports _is_metadata_section from
        # this module, so this lookup has to stay lazy.
        from app.services.summarizer import get_summarization_service  # noqa: PLC0415

        await get_summarization_service().invalidate_section_reduce_cache(document_id)

        # Replace, never append. `finalize` reaches this from two paths and
        # neither cleared the other, so `ml_notes` held 20 rows for 10 sections
        # and the surplus inflated the executive summary's input by ~0.08 theme
        # coverage. Invalidating the reduce cache above without this is half the
        # job -- the cache is rebuilt from exactly these rows.
        async with get_session_factory()() as session:
            stale = await session.execute(
                delete(SectionSummaryModel).where(
                    SectionSummaryModel.document_id == document_id
                )
            )
            await session.commit()
        if stale.rowcount:
            logger.info(
                "section_summarizer: replacing %d existing summaries",
                stale.rowcount,
                extra={"doc_id": document_id},
            )

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

        qualifying = [s for s in non_metadata if len(section_text(s)) >= MIN_PREVIEW_LEN]

        if not qualifying:
            logger.info(
                "section_summarizer: no qualifying sections (preview < %d chars)",
                MIN_PREVIEW_LEN,
                extra={"doc_id": document_id},
            )
            return 0

        # Group sections so total units <= MAX_UNITS
        units = self._as_units(qualifying) if per_section else self._group_sections(qualifying)

        logger.info(
            "section_summarizer: %d qualifying sections → %d units",
            len(qualifying),
            len(units),
            extra={"doc_id": document_id},
        )

        semaphore = asyncio.Semaphore(concurrency)
        # The shrinking cap only bounds grouped runs on the blocking path.
        text_cap = TEXT_HARD_CAP if per_section else unit_text_cap(len(units))
        total_inserted = 0

        async def _summarize_unit(unit_index: int, unit: dict) -> None:
            nonlocal total_inserted
            async with semaphore:
                try:
                    summary_text = await get_llm_service().complete(
                        messages=[
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": unit["text"][:text_cap]},
                        ],
                        temperature=0.0,
                        timeout=300.0,
                        background=True,
                    )
                except LLMUnavailableError:
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
            await asyncio.gather(*[_summarize_unit(i, unit) for i, unit in enumerate(units)])
        except LLMUnavailableError:
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


            async with get_session_factory()() as session:
                dup_result = await session.execute(
                    select(func.count(EnrichmentJobModel.id)).where(
                        EnrichmentJobModel.document_id == document_id,
                        EnrichmentJobModel.job_type == "web_refs",
                        EnrichmentJobModel.status.in_(["pending", "running"]),
                    )
                )
                if dup_result.scalar_one() > 0:
                    logger.debug(
                        "section_summarizer: web_refs job already pending/running for doc=%s",
                        document_id,
                    )
                    return

                job = EnrichmentJobModel(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    job_type="web_refs",
                    status="pending",
                    created_at=datetime.now(UTC),
                )
                session.add(job)
                await session.commit()
                logger.info("section_summarizer: enqueued web_refs job for doc=%s", document_id)
        except Exception as exc:
            logger.warning(
                "section_summarizer: failed to enqueue web_refs for doc=%s: %s",
                document_id,
                exc,
            )






    def _as_units(self, sections: list[SectionModel]) -> list[dict]:
        """One unit per section, so every section gets its own summary."""
        return [
            {"heading": s.heading, "text": section_text(s), "section_id": s.id}
            for s in sections
        ]

    def _group_sections(self, sections: list[SectionModel]) -> list[dict]:
        """Group qualifying sections into at most MAX_UNITS summarization units."""
        count = len(sections)
        if count <= MAX_UNITS:
            return [
                {
                    "heading": s.heading,
                    "text": section_text(s),
                    "section_id": s.id,
                }
                for s in sections
            ]

        group_size = math.ceil(count / MAX_UNITS)
        units: list[dict] = []
        for start in range(0, count, group_size):
            group = sections[start : start + group_size]
            heading = group[0].heading
            text = "\n\n".join(section_text(s) for s in group)
            units.append({"heading": heading, "text": text, "section_id": None})

        return units


_service: SectionSummarizerService | None = None


def get_section_summarizer_service() -> SectionSummarizerService:
    global _service
    if _service is None:
        _service = SectionSummarizerService()
    return _service


async def resummarize_documents_missing_summaries(limit: int = 20) -> int:
    """Regenerate summaries for completed documents that have none.

    Deferred summarisation runs as a background task, so a shutdown between
    `stage='complete'` and the task finishing loses the work with nothing
    recording that it was owed. This is the repair: a completed document that
    has qualifying sections and no summary rows gets another pass.

    Bounded per boot, because each document is one LLM call per section and a
    library that has never been summarised must not turn startup into an hours
    long job that competes with the user's first question.
    """
    from app.models import DocumentModel  # noqa: PLC0415

    async with get_session_factory()() as session:
        summarised = select(SectionSummaryModel.document_id).distinct().scalar_subquery()
        result = await session.execute(
            select(DocumentModel.id)
            .join(SectionModel, SectionModel.document_id == DocumentModel.id)
            .where(DocumentModel.stage == "complete")
            .where(DocumentModel.id.notin_(summarised))
            .group_by(DocumentModel.id)
            .limit(limit)
        )
        doc_ids = [row[0] for row in result.all()]

    repaired = 0
    for doc_id in doc_ids:
        try:
            if await get_section_summarizer_service().generate(doc_id, per_section=True):
                repaired += 1
        except Exception as exc:
            logger.warning(
                "section summary repair failed (non-fatal): %s", exc, extra={"doc_id": doc_id}
            )
    return repaired
