"""Repository for `ClipModel` (Reading Journal passage clips)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ClipModel
from app.services.repo_helpers import get_or_404


class ClipRepo:
    """All `ClipModel` persistence in one place.

    Routers depend on this via `Depends(get_clip_repo)` so they never
    touch `session.execute / add / commit / delete` directly.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        document_id: str,
        section_id: str | None,
        section_heading: str | None,
        pdf_page_number: int | None,
        selected_text: str,
        user_note: str,
    ) -> ClipModel:
        now = datetime.now(UTC)
        clip = ClipModel(
            id=str(uuid.uuid4()),
            document_id=document_id,
            section_id=section_id,
            section_heading=section_heading,
            pdf_page_number=pdf_page_number,
            selected_text=selected_text,
            user_note=user_note,
            created_at=now,
            updated_at=now,
        )
        self.session.add(clip)
        await self.session.commit()
        await self.session.refresh(clip)
        return clip

    async def list(self, *, document_id: str | None = None) -> Sequence[ClipModel]:
        stmt = select(ClipModel).order_by(ClipModel.created_at.desc())
        if document_id:
            stmt = stmt.where(ClipModel.document_id == document_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_or_404(self, clip_id: str) -> ClipModel:
        return await get_or_404(self.session, ClipModel, clip_id, name="Clip")

    async def update_note(self, clip_id: str, *, user_note: str) -> ClipModel:
        clip = await self.get_or_404(clip_id)
        clip.user_note = user_note
        clip.updated_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(clip)
        return clip

    async def delete(self, clip_id: str) -> None:
        await self.get_or_404(clip_id)
        await self.session.execute(delete(ClipModel).where(ClipModel.id == clip_id))
        await self.session.commit()


def get_clip_repo(session: AsyncSession = Depends(get_db)) -> ClipRepo:
    return ClipRepo(session)
