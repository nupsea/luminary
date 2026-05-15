"""Reference validator service for S194: URL validation and dead link pruning.

Performs async HEAD requests to verify web reference URLs.
Concurrency limited via asyncio.Semaphore, max 20 URLs per run.
"""

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.database import get_session_factory
from app.models import WebReferenceModel

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = 5
_MAX_URLS_PER_RUN = 20
_TIMEOUT_SECONDS = 5.0


class ReferenceValidatorService:
    """Validate web reference URLs via async HEAD requests."""

    async def validate_references(self, document_id: str) -> dict[str, int]:
        """Validate all unchecked or all references for a document.

        Returns {"valid": N, "invalid": M}.
        """
        async with get_session_factory()() as session:
            result = await session.execute(
                select(WebReferenceModel)
                .where(WebReferenceModel.document_id == document_id)
                .limit(_MAX_URLS_PER_RUN)
            )
            refs = list(result.scalars().all())

        if not refs:
            return {"valid": 0, "invalid": 0}

        semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
        results: list[tuple[str, bool]] = []

        async def _check_one(ref_id: str, url: str) -> tuple[str, bool]:
            async with semaphore:
                try:
                    async with httpx.AsyncClient(
                        timeout=_TIMEOUT_SECONDS, follow_redirects=True
                    ) as client:
                        resp = await client.head(url)
                        return (ref_id, resp.status_code < 400)
                except Exception:
                    return (ref_id, False)

        tasks = [_check_one(r.id, r.url) for r in refs]
        results = await asyncio.gather(*tasks)

        now = datetime.now(UTC)
        valid_count = 0
        invalid_count = 0

        async with get_session_factory()() as session:
            for ref_id, is_reachable in results:
                ref_result = await session.execute(
                    select(WebReferenceModel).where(WebReferenceModel.id == ref_id)
                )
                ref = ref_result.scalar_one_or_none()
                if ref is None:
                    continue
                ref.is_valid = is_reachable
                ref.last_checked_at = now
                if is_reachable:
                    valid_count += 1
                else:
                    invalid_count += 1
            await session.commit()

        logger.info(
            "reference_validator: doc=%s valid=%d invalid=%d",
            document_id,
            valid_count,
            invalid_count,
        )
        return {"valid": valid_count, "invalid": invalid_count}

    async def validate_urls(self, urls: list[str]) -> dict[str, bool]:
        """Validate a list of URLs and return {url: is_reachable}.

        Used by reference extraction to pre-validate before persisting.
        """
        semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
        results: dict[str, bool] = {}

        async def _check(url: str) -> None:
            async with semaphore:
                try:
                    async with httpx.AsyncClient(
                        timeout=_TIMEOUT_SECONDS, follow_redirects=True
                    ) as client:
                        resp = await client.head(url)
                        results[url] = resp.status_code < 400
                except Exception:
                    results[url] = False

        tasks = [_check(u) for u in urls[:_MAX_URLS_PER_RUN]]
        await asyncio.gather(*tasks)
        return results
