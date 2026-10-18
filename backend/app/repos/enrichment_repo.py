"""Enrichment jobs: per-document background work queued after ingestion. Nothing here commits."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, EnrichmentJobModel, ImageModel

_ACTIVE = ("pending", "running")


class EnrichmentRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def jobs_for_document(self, document_id: str) -> Sequence[EnrichmentJobModel]:
        result = await self.session.execute(
            select(EnrichmentJobModel)
            .where(EnrichmentJobModel.document_id == document_id)
            .order_by(EnrichmentJobModel.created_at)
        )
        return result.scalars().all()

    async def latest_status(self, document_id: str, job_type: str) -> str | None:
        result = await self.session.execute(
            select(EnrichmentJobModel.status)
            .where(
                EnrichmentJobModel.document_id == document_id,
                EnrichmentJobModel.job_type == job_type,
            )
            .order_by(EnrichmentJobModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def active_job(self, document_id: str, job_type: str) -> EnrichmentJobModel | None:
        result = await self.session.execute(
            select(EnrichmentJobModel)
            .where(
                EnrichmentJobModel.document_id == document_id,
                EnrichmentJobModel.job_type == job_type,
                EnrichmentJobModel.status.in_(_ACTIVE),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def supersede_pending(self, document_id: str, job_type: str, reason: str) -> list[str]:
        """Mark this document's pending jobs of a type done with `reason`; their ids."""
        result = await self.session.execute(
            update(EnrichmentJobModel)
            .where(
                EnrichmentJobModel.document_id == document_id,
                EnrichmentJobModel.job_type == job_type,
                EnrichmentJobModel.status == "pending",
            )
            .values(status="done", error_message=reason)
            .returning(EnrichmentJobModel.id)
        )
        return list(result.scalars())

    def enqueue(self, document_id: str, job_type: str) -> EnrichmentJobModel:
        """Add a pending job to the session; the caller commits."""
        job = EnrichmentJobModel(
            id=str(uuid.uuid4()), document_id=document_id, job_type=job_type, status="pending"
        )
        self.session.add(job)
        return job

    async def enqueue_unless_active(
        self, document_id: str, job_type: str
    ) -> EnrichmentJobModel | None:
        """Queue a job unless one of this type is already pending or running for the document."""
        if await self.active_job(document_id, job_type) is not None:
            return None
        return self.enqueue(document_id, job_type)

    async def update_job(self, job_id: str, **values: object) -> None:
        await self.session.execute(
            update(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id).values(**values)
        )

    async def documents_with_pending(self) -> list[str]:
        result = await self.session.execute(
            select(EnrichmentJobModel.document_id)
            .where(EnrichmentJobModel.status == "pending")
            .distinct()
        )
        return list(result.scalars().all())

    async def next_pending(self, document_id: str) -> EnrichmentJobModel | None:
        result = await self.session.execute(
            select(EnrichmentJobModel)
            .where(
                EnrichmentJobModel.document_id == document_id,
                EnrichmentJobModel.status == "pending",
            )
            .order_by(
                # Chapter cards before image analysis: a reader reaches chapter 1's end
                # long before every figure is analysed.
                case(
                    (EnrichmentJobModel.job_type == "image_extract", 1),
                    (EnrichmentJobModel.job_type == "chapter_cards", 2),
                    (EnrichmentJobModel.job_type == "image_analyze", 3),
                    else_=4,
                ),
                EnrichmentJobModel.created_at,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def requeue_for_boot(self, max_attempts: int) -> list[str]:
        """Back to pending: interrupted and skipped jobs, and failures under `max_attempts`."""
        result = await self.session.execute(
            update(EnrichmentJobModel)
            .where(
                or_(
                    EnrichmentJobModel.status == "running",
                    EnrichmentJobModel.status == "skipped",
                    and_(
                        EnrichmentJobModel.status == "failed",
                        EnrichmentJobModel.attempts < max_attempts,
                    ),
                )
            )
            .values(status="pending", started_at=None, error_message=None)
            .returning(EnrichmentJobModel.id)
        )
        return list(result.scalars())

    async def count_exhausted(self, max_attempts: int) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(EnrichmentJobModel)
            .where(
                EnrichmentJobModel.status == "failed",
                EnrichmentJobModel.attempts >= max_attempts,
            )
        )
        return int(result.scalar_one())

    async def requeue_skipped(self) -> list[str]:
        result = await self.session.execute(
            update(EnrichmentJobModel)
            .where(EnrichmentJobModel.status == "skipped")
            .values(status="pending", started_at=None, completed_at=None, error_message=None)
            .returning(EnrichmentJobModel.id)
        )
        return list(result.scalars())

    async def queue_counts(self) -> dict[str, tuple[int, int]]:
        """{status: (jobs, distinct documents)} across the library."""
        result = await self.session.execute(
            select(
                EnrichmentJobModel.status,
                func.count(),
                func.count(func.distinct(EnrichmentJobModel.document_id)),
            ).group_by(EnrichmentJobModel.status)
        )
        return {status: (jobs, docs) for status, jobs, docs in result.all()}

    async def images_with_sections(self, document_id: str) -> list[tuple[ImageModel, str | None]]:
        """Every image of a document with its chunk's section, in page order."""
        result = await self.session.execute(
            select(ImageModel, ChunkModel.section_id)
            .outerjoin(ChunkModel, ChunkModel.id == ImageModel.chunk_id)
            .where(ImageModel.document_id == document_id)
            .order_by(ImageModel.page, ImageModel.created_at)
        )
        return [(img, sid) for img, sid in result.all()]
