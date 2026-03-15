"""Async enrichment queue worker.

Polls the enrichment_jobs table for pending jobs and dispatches them to
registered job-type handlers.  One job at a time per document (sequential),
parallel across different documents.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from app.database import get_session_factory
from app.models import EnrichmentJobModel

logger = logging.getLogger(__name__)

# Type alias: (document_id, job_id) -> None (raises on failure)
JobHandler = Callable[[str, str], Coroutine[Any, Any, None]]


class EnrichmentQueueWorker:
    """Background worker that drains the enrichment_jobs table.

    Design:
    - One asyncio Task per document_id runs at a time.
    - Jobs for different documents run in parallel.
    - Jobs for the same document run sequentially (FIFO by created_at).
    - Handlers are registered per job_type via register().
    - poll_interval_s controls how often idle workers check for new jobs.
    """

    def __init__(self, poll_interval_s: float = 5.0) -> None:
        self._handlers: dict[str, JobHandler] = {}
        self._poll_interval_s = poll_interval_s
        self._running = False
        self._task: asyncio.Task | None = None
        # Strong reference set — prevents GC on running document tasks
        self._doc_tasks: set[asyncio.Task] = set()
        self._active_doc_ids: set[str] = set()

    def register(self, job_type: str, handler: JobHandler) -> None:
        """Register a handler for a job_type."""
        self._handlers[job_type] = handler
        logger.info("EnrichmentQueueWorker: registered handler for job_type=%s", job_type)

    async def start(self) -> None:
        """Start the background polling loop (called from lifespan)."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("EnrichmentQueueWorker: started")

    async def stop(self) -> None:
        """Stop the polling loop (called from lifespan shutdown)."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("EnrichmentQueueWorker: stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            await self._dispatch_pending()
            await asyncio.sleep(self._poll_interval_s)

    async def _dispatch_pending(self) -> None:
        """Find pending jobs and launch per-document task runners for any doc not already running."""
        async with get_session_factory()() as session:
            result = await session.execute(
                select(EnrichmentJobModel.document_id)
                .where(EnrichmentJobModel.status == "pending")
                .distinct()
            )
            doc_ids = [row[0] for row in result.all()]

        for doc_id in doc_ids:
            if doc_id in self._active_doc_ids:
                continue
            self._active_doc_ids.add(doc_id)
            task = asyncio.create_task(self._run_for_document(doc_id))
            self._doc_tasks.add(task)
            task.add_done_callback(self._doc_tasks.discard)
            task.add_done_callback(lambda t, d=doc_id: self._active_doc_ids.discard(d))

    async def _run_for_document(self, document_id: str) -> None:
        """Process all pending jobs for one document sequentially (FIFO)."""
        while True:
            async with get_session_factory()() as session:
                result = await session.execute(
                    select(EnrichmentJobModel)
                    .where(
                        EnrichmentJobModel.document_id == document_id,
                        EnrichmentJobModel.status == "pending",
                    )
                    .order_by(EnrichmentJobModel.created_at)
                    .limit(1)
                )
                job = result.scalar_one_or_none()

            if job is None:
                break

            await self._run_job(job.id, job.document_id, job.job_type)

    async def _run_job(self, job_id: str, document_id: str, job_type: str) -> None:
        handler = self._handlers.get(job_type)

        async with get_session_factory()() as session:
            await session.execute(
                update(EnrichmentJobModel)
                .where(EnrichmentJobModel.id == job_id)
                .values(status="running", started_at=datetime.now(UTC))
            )
            await session.commit()

        logger.info(
            "EnrichmentQueueWorker: starting job job_id=%s job_type=%s doc=%s",
            job_id,
            job_type,
            document_id,
        )

        if handler is None:
            error_msg = "No handler registered for job_type=%s" % job_type
            logger.warning(error_msg)
            async with get_session_factory()() as session:
                await session.execute(
                    update(EnrichmentJobModel)
                    .where(EnrichmentJobModel.id == job_id)
                    .values(
                        status="failed",
                        completed_at=datetime.now(UTC),
                        error_message=error_msg,
                    )
                )
                await session.commit()
            return

        try:
            await handler(document_id, job_id)
            async with get_session_factory()() as session:
                await session.execute(
                    update(EnrichmentJobModel)
                    .where(EnrichmentJobModel.id == job_id)
                    .values(status="done", completed_at=datetime.now(UTC))
                )
                await session.commit()
            logger.info(
                "EnrichmentQueueWorker: job done job_id=%s doc=%s", job_id, document_id
            )
        except Exception as exc:
            logger.warning(
                "EnrichmentQueueWorker: job failed job_id=%s doc=%s: %s",
                job_id,
                document_id,
                exc,
                exc_info=exc,
            )
            async with get_session_factory()() as session:
                await session.execute(
                    update(EnrichmentJobModel)
                    .where(EnrichmentJobModel.id == job_id)
                    .values(
                        status="failed",
                        completed_at=datetime.now(UTC),
                        error_message=str(exc),
                    )
                )
                await session.commit()


# Singleton worker instance (started in lifespan)
_worker: EnrichmentQueueWorker | None = None


def get_enrichment_worker() -> EnrichmentQueueWorker:
    global _worker  # noqa: PLW0603
    if _worker is None:
        _worker = EnrichmentQueueWorker()
    return _worker
