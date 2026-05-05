"""Reference enricher service for S138: web reference grounding.

Generates LLM-suggested canonical web references per technical term
extracted from section summaries. Stored in WebReferenceModel table.

No live HTTP calls when WEB_SEARCH_PROVIDER == 'none' (default).
"""

import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import get_session_factory
from app.models import SectionSummaryModel, WebReferenceModel
from app.services.llm import LLMUnavailableError, get_llm_service

logger = logging.getLogger(__name__)

_SOURCE_QUALITY_RANK: dict[str, int] = {
    "official_docs": 0,
    "spec": 1,
    "wiki": 2,
    "tutorial": 3,
    "blog": 4,
    "unknown": 5,
}

_MAX_REFS_PER_SECTION = 5

_SYSTEM_PROMPT = (
    "You are a technical documentation expert. "
    "For each technical term found in the provided section summary, output a JSON array "
    "of up to 5 canonical reference objects. "
    "Order them: official language/framework docs first, then specification/RFC, "
    "then recognized book publisher, then trusted community wiki, then tutorial, then blog. "
    "For each reference use this exact JSON shape: "
    '{"term": "...", "url": "...", "title": "...", "excerpt": "...", '
    '"source_quality": "official_docs|spec|wiki|tutorial|blog|unknown"}. '
    "Return only the JSON array with no prose or markdown fences outside the array. "
    "If the section contains no recognizable technical terms, return an empty array []."
)


def sort_by_quality(refs: list[dict]) -> list[dict]:
    """Sort reference dicts by source_quality ascending (official_docs first).

    Pure function -- no I/O.
    """
    return sorted(
        refs,
        key=lambda r: _SOURCE_QUALITY_RANK.get(r.get("source_quality", "unknown"), 5),
    )


def _strip_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences from an LLM response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Drop first line (``` or ```json) and last line (```)
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    return cleaned


async def _extract_references(section_content: str) -> list[dict]:
    """Call the LLM to extract canonical references from a section summary.

    Returns list of dicts on success, [] on parse failure (non-fatal).
    Raises LLMUnavailableError if the LLM is unreachable.
    """
    user_prompt = (
        f"Section summary:\n{section_content}\n\n"
        "Extract up to 5 key technical terms and for each provide a canonical reference."
    )
    raw = await get_llm_service().complete(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        timeout=30.0,
        background=True,
    )
    cleaned = _strip_fences(raw)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        logger.warning("reference_enricher: LLM returned non-list JSON, ignoring")
        return []
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("reference_enricher: JSON parse failed: %s -- raw=%s", exc, raw[:200])
        return []


class ReferenceEnricherService:
    """Generate web references for all SectionSummaryModel rows of a document.

    When WEB_SEARCH_PROVIDER == 'none' (default) all rows have is_llm_suggested=True.
    When a non-none provider is configured, a HEAD request is issued per URL and
    is_llm_suggested is set False for reachable URLs.
    """

    async def enrich(self, document_id: str) -> int:
        """Generate web references for section summaries that have none yet.

        Returns count of new WebReferenceModel rows created.
        Raises LLMUnavailableError (propagates to worker to mark job failed).
        """
        settings = get_settings()
        provider = settings.WEB_SEARCH_PROVIDER

        async with get_session_factory()() as session:
            summaries_result = await session.execute(
                select(SectionSummaryModel).where(SectionSummaryModel.document_id == document_id)
            )
            summaries = list(summaries_result.scalars().all())

        if not summaries:
            logger.info(
                "reference_enricher: no section summaries for doc=%s, skipping",
                document_id,
            )
            return 0

        total_inserted = 0

        for summary in summaries:
            # Idempotency: skip if refs already exist for this (document_id, section_id)
            async with get_session_factory()() as session:
                existing_count_result = await session.execute(
                    select(func.count(WebReferenceModel.id)).where(
                        WebReferenceModel.document_id == document_id,
                        WebReferenceModel.section_id == summary.section_id,
                    )
                )
                if existing_count_result.scalar_one() > 0:
                    logger.debug(
                        "reference_enricher: skipping section_id=%s (already has refs)",
                        summary.section_id,
                    )
                    continue

            try:
                refs = await _extract_references(summary.content)
            except LLMUnavailableError:
                raise
            except Exception as exc:
                logger.warning(
                    "reference_enricher: extraction failed for section_id=%s: %s",
                    summary.section_id,
                    exc,
                )
                continue

            if not refs:
                continue

            # Validate URLs via HEAD request (S194)
            url_validity = await self._validate_urls(refs)

            # Optionally verify URLs via HEAD request (legacy provider check)
            if provider != "none":
                refs = await self._verify_urls(refs)

            # Sort and limit
            sorted_refs = sort_by_quality(refs)[:_MAX_REFS_PER_SECTION]

            # Write rows
            now = datetime.now(UTC)
            async with get_session_factory()() as session:
                for ref in sorted_refs:
                    url = str(ref.get("url", ""))
                    is_valid = url_validity.get(url)
                    row = WebReferenceModel(
                        id=str(uuid.uuid4()),
                        document_id=document_id,
                        section_id=summary.section_id,
                        term=str(ref.get("term", ""))[:200],
                        url=url,
                        title=str(ref.get("title", ""))[:300],
                        excerpt=str(ref.get("excerpt", "")),
                        source_quality=str(ref.get("source_quality", "unknown"))[:30],
                        is_llm_suggested=True,
                        is_valid=is_valid,
                        last_checked_at=now if is_valid is not None else None,
                        created_at=now,
                    )
                    session.add(row)
                try:
                    await session.commit()
                    total_inserted += len(sorted_refs)
                except IntegrityError:
                    await session.rollback()
                    logger.debug(
                        "reference_enricher: IntegrityError (duplicate) for "
                        "section_id=%s, skipping",
                        summary.section_id,
                    )

        logger.info(
            "reference_enricher: inserted %d refs for doc=%s",
            total_inserted,
            document_id,
        )
        return total_inserted

    async def refresh_section(self, section_id: str, document_id: str) -> int:
        """Delete existing refs for a section and re-run extraction.

        Returns count of new rows created.
        """
        settings = get_settings()
        provider = settings.WEB_SEARCH_PROVIDER

        # Delete existing refs
        async with get_session_factory()() as session:
            existing_result = await session.execute(
                select(WebReferenceModel).where(
                    WebReferenceModel.document_id == document_id,
                    WebReferenceModel.section_id == section_id,
                )
            )
            for row in existing_result.scalars().all():
                await session.delete(row)
            await session.commit()

        # Load the section summary
        async with get_session_factory()() as session:
            summary_result = await session.execute(
                select(SectionSummaryModel).where(
                    SectionSummaryModel.document_id == document_id,
                    SectionSummaryModel.section_id == section_id,
                )
            )
            summary = summary_result.scalar_one_or_none()

        if summary is None:
            logger.warning(
                "reference_enricher: no section_summary found for section_id=%s doc=%s",
                section_id,
                document_id,
            )
            return 0

        try:
            refs = await _extract_references(summary.content)
        except LLMUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail="Ollama is unreachable. Start it with: ollama serve",
            ) from exc

        if not refs:
            return 0

        # Validate URLs via HEAD request (S194)
        url_validity = await self._validate_urls(refs)

        if provider != "none":
            refs = await self._verify_urls(refs)

        sorted_refs = sort_by_quality(refs)[:_MAX_REFS_PER_SECTION]

        now = datetime.now(UTC)
        async with get_session_factory()() as session:
            for ref in sorted_refs:
                url = str(ref.get("url", ""))
                is_valid = url_validity.get(url)
                row = WebReferenceModel(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    section_id=section_id,
                    term=str(ref.get("term", ""))[:200],
                    url=url,
                    title=str(ref.get("title", ""))[:300],
                    excerpt=str(ref.get("excerpt", "")),
                    source_quality=str(ref.get("source_quality", "unknown"))[:30],
                    is_llm_suggested=True,
                    is_valid=is_valid,
                    last_checked_at=now if is_valid is not None else None,
                    created_at=now,
                )
                session.add(row)
            await session.commit()

        return len(sorted_refs)

    async def _validate_urls(self, refs: list[dict]) -> dict[str, bool]:
        """Validate URLs via HEAD requests (S194). Returns {url: is_reachable}."""
        from app.services.reference_validator import ReferenceValidatorService  # noqa: PLC0415

        urls = [str(r.get("url", "")) for r in refs if r.get("url")]
        if not urls:
            return {}
        svc = ReferenceValidatorService()
        return await svc.validate_urls(urls)

    async def _verify_urls(self, refs: list[dict]) -> list[dict]:
        """Issue HEAD requests to verify URLs when provider != 'none'.

        Sets is_llm_suggested=False on dicts for reachable URLs.
        Non-fatal: any error leaves is_llm_suggested=True.
        """
        try:
            import httpx  # noqa: PLC0415
        except ImportError:
            logger.warning("reference_enricher: httpx not available, skipping URL verification")
            return refs

        verified = []
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            for ref in refs:
                url = ref.get("url", "")
                is_llm_suggested = True
                if url:
                    try:
                        resp = await client.head(url)
                        if resp.status_code < 400:
                            is_llm_suggested = False
                    except Exception:
                        pass  # unreachable -- keep is_llm_suggested=True
                verified.append({**ref, "is_llm_suggested": is_llm_suggested})
        return verified


async def web_refs_handler(document_id: str, job_id: str) -> None:
    """Enrichment handler for job_type='web_refs'.

    Called by EnrichmentQueueWorker for each web_refs job.
    Delegates to ReferenceEnricherService.enrich().
    LLMUnavailableError propagates to mark job 'failed'.
    """
    logger.info("web_refs_handler: starting doc=%s job=%s", document_id, job_id)
    svc = ReferenceEnricherService()
    count = await svc.enrich(document_id)
    logger.info("web_refs_handler: done doc=%s inserted=%d", document_id, count)
