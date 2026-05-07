"""Repository for `AnnotationModel` (persistent text highlights)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AnnotationModel
from app.services.repo_helpers import get_or_404


class AnnotationRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        document_id: str,
        section_id: str,
        chunk_id: str | None,
        selected_text: str,
        start_offset: int,
        end_offset: int,
        color: Literal["yellow", "green", "blue", "pink"],
        note_text: str | None,
        page_number: int | None,
    ) -> AnnotationModel:
        annotation = AnnotationModel(
            id=str(uuid.uuid4()),
            document_id=document_id,
            section_id=section_id,
            chunk_id=chunk_id,
            selected_text=selected_text,
            start_offset=start_offset,
            end_offset=end_offset,
            color=color,
            note_text=note_text,
            page_number=page_number,
            created_at=datetime.now(UTC),
        )
        self.session.add(annotation)
        await self.session.commit()
        await self.session.refresh(annotation)
        return annotation

    async def list_for_document(self, document_id: str) -> Sequence[AnnotationModel]:
        result = await self.session.execute(
            select(AnnotationModel)
            .where(AnnotationModel.document_id == document_id)
            .order_by(AnnotationModel.created_at)
        )
        return result.scalars().all()

    async def delete(self, annotation_id: str) -> None:
        row = await get_or_404(
            self.session, AnnotationModel, annotation_id, name="Annotation"
        )
        await self.session.delete(row)
        await self.session.commit()


def get_annotation_repo(session: AsyncSession = Depends(get_db)) -> AnnotationRepo:
    return AnnotationRepo(session)
