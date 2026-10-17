"""Enrichment jobs: the per-document background work queued after ingestion."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
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
