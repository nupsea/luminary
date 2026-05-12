"""Repository for `WebReferenceModel`."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import WebReferenceModel


class ReferenceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_document(
        self,
        document_id: str,
        *,
        include_invalid: bool = False,
    ) -> Sequence[WebReferenceModel]:
        """Refs ordered by source_quality then term. When include_invalid is
        False (the default), explicitly-invalid rows are dropped; unchecked
        (None) and valid (True) are kept."""
        query = (
            select(WebReferenceModel)
            .where(WebReferenceModel.document_id == document_id)
            .order_by(WebReferenceModel.source_quality, WebReferenceModel.term)
        )
        if not include_invalid:
            query = query.where(
                (WebReferenceModel.is_valid.is_(None))
                | (WebReferenceModel.is_valid == True)  # noqa: E712
            )
        result = await self.session.execute(query)
        return result.scalars().all()

    async def list_for_section(
        self, section_id: str
    ) -> Sequence[WebReferenceModel]:
        result = await self.session.execute(
            select(WebReferenceModel)
            .where(WebReferenceModel.section_id == section_id)
            .order_by(WebReferenceModel.source_quality, WebReferenceModel.term)
        )
        return result.scalars().all()

    async def delete_all_for_document(self, document_id: str) -> None:
        existing = await self.session.execute(
            select(WebReferenceModel).where(
                WebReferenceModel.document_id == document_id
            )
        )
        for row in existing.scalars().all():
            await self.session.delete(row)
        await self.session.commit()


def get_reference_repo(session: AsyncSession = Depends(get_db)) -> ReferenceRepo:
    return ReferenceRepo(session)
