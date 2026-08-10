"""Reference enricher service for web reference grounding.

Generates LLM-suggested canonical web references for key concepts and terms
extracted from section summaries. Works across all document types (technical,
philosophy, history, science, literature, etc.). Stored in WebReferenceModel.

No live HTTP calls when WEB_SEARCH_PROVIDER == 'none' (default).
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import get_session_factory
from app.exceptions import DependencyUnavailable
from app.models import SectionSummaryModel, WebReferenceModel
from app.services.llm import LLMUnavailableError, get_llm_service
from app.services.llm_json import parse_llm_json_array
from app.services.settings_service import get_llm_error_message

logger = logging.getLogger(__name__)

_SOURCE_QUALITY_RANK: dict[str, int] = {
    "official_docs": 0,
    "spec": 1,
    "academic": 1,
    "encyclopedia": 2,
    "wiki": 3,
    "tutorial": 4,
    "blog": 5,
    "unknown": 6,
}

_MAX_REFS_PER_SECTION = 3

# No `excerpt`: generation is the whole cost here, and it was the largest field
# -- an invented quotation for a page the model never fetched.
_SYSTEM_PROMPT = (
    "You are a research librarian with expertise across all domains. "
    "For each key concept or term found in the provided section summary, output a JSON array "
    f"of up to {_MAX_REFS_PER_SECTION} canonical reference objects from the most authoritative "
    "sources for that domain. "
    "Give each object a different URL -- do not repeat one source across several terms. "
    "Domain guidance: philosophy/ethics -> Stanford Encyclopedia of Philosophy, PhilPapers; "
    "science/medicine -> peer-reviewed journals, PubMed, authoritative textbook publishers; "
    "history/humanities -> encyclopedias, academic publishers (OUP, Cambridge); "
    "mathematics -> MathWorld, arXiv, textbook publishers; "
    "software/technology -> official language/framework docs, specs/RFCs; "
    "general -> Wikipedia or trusted encyclopedias, then tutorials, then blogs. "
    "Order them: domain-specific authoritative source first, then encyclopedia/wiki, "
    "then tutorial or explainer, then blog. "
    "Prefer a stable root or section URL you are confident exists over a deep link you are "
    "guessing at. "
    "For each reference use this exact JSON shape: "
    '{"term": "...", "url": "...", "title": "...", '
    '"source_quality": "official_docs|spec|academic|encyclopedia|wiki|tutorial|blog|unknown"}. '
    "Return only the JSON array with no prose or markdown fences outside the array. "
    "If the section contains no concepts or terms worth referencing, return an empty array []."
)

# Generous: nobody waits on this, and a tight timeout only fails the call while
# queued behind interactive work, restarting the handler from section one.
_EXTRACT_TIMEOUT_S = 600.0


def sort_by_quality(refs: list[dict]) -> list[dict]:
    """Sort reference dicts by source_quality ascending (official_docs first).

    Pure function -- no I/O.
    """
    return sorted(
        refs,
        key=lambda r: _SOURCE_QUALITY_RANK.get(r.get("source_quality", "unknown"), 5),
    )


def dedupe_by_url(refs: list[dict]) -> list[dict]:
    """Drop repeats of a URL already claimed by an earlier term.

    Pure function. A small model routinely answers one section's terms with one
    source restated several times, displacing real sources before the truncate.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for ref in refs:
        url = str(ref.get("url", "")).rstrip("/").lower()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(ref)
    return out


def select_sections(summaries: list, limit: int) -> list:
    """The `limit` most substantial summaries, returned in document order.

    One LLM call per section, so a long book is sampled rather than exhausted.
    Longest-summary-first beats document order, which would spend the budget on
    the preface. Ties break on unit_index so reruns pick the same sections.
    """
    if limit <= 0 or len(summaries) <= limit:
        return sorted(summaries, key=lambda s: s.unit_index)
    ranked = sorted(summaries, key=lambda s: (-len(s.content or ""), s.unit_index))
    return sorted(ranked[:limit], key=lambda s: s.unit_index)


async def _extract_references(section_content: str) -> list[dict]:
    """Call the LLM to extract canonical references from a section summary.

    Returns list of dicts on success, [] on parse failure (non-fatal).
    Raises LLMUnavailableError if the LLM is unreachable.
    """
    user_prompt = (
        f"Section summary:\n{section_content}\n\n"
        f"Extract up to {_MAX_REFS_PER_SECTION} key concepts or terms and for each provide "
        "a canonical reference."
    )
    from app.services.enrichment_concurrency import get_enrichment_llm_semaphore  # noqa: PLC0415

    async with get_enrichment_llm_semaphore():
        raw = await get_llm_service().complete(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            timeout=_EXTRACT_TIMEOUT_S,
            background=True,
        )
    refs = [r for r in parse_llm_json_array(raw) if isinstance(r, dict) and r.get("url")]
    if not refs and raw.strip() not in ("", "[]"):
        logger.warning(
            "reference_enricher: no references recovered from response -- raw=%s",
            raw[:200],
        )
    return refs


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

        total = len(summaries)
        summaries = select_sections(summaries, settings.WEB_REFS_MAX_SECTIONS)
        if len(summaries) < total:
            logger.info(
                "reference_enricher: doc=%s has %d sections, covering the %d most "
                "substantial (WEB_REFS_MAX_SECTIONS)",
                document_id,
                total,
                len(summaries),
            )

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

            refs = dedupe_by_url(refs)
            if not refs:
                continue

            # Validate URLs via HEAD request
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
            raise DependencyUnavailable(get_llm_error_message()) from exc

        refs = dedupe_by_url(refs)
        if not refs:
            return 0

        # Validate URLs via HEAD request
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
        """Validate URLs via HEAD requests Returns {url: is_reachable}."""
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
                        logger.debug("reference HEAD failed: %s", url, exc_info=True)
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
