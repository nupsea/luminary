"""Repository for `NoteModel`, `NoteLinkModel`, and `NoteSourceModel` reads.

Owns simple `session.execute / add / commit / delete` calls for the notes
router. Multi-step orchestration that flushes mid-transaction or fans out
to FTS / vector / graph services (e.g. `_apply_note_update`) stays in the
router because the ordering matters and the side-effects are not pure
data ops.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import NamedTuple

from fastapi import Depends
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    CollectionMemberModel,
    NoteLinkModel,
    NoteModel,
    NoteSourceModel,
)
from app.services.repo_helpers import get_or_404


class NoteLinkWithContent(NamedTuple):
    link: NoteLinkModel
    content: str


class NoteRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- single-row reads --------------------------------------------------

    async def get_or_404(self, note_id: str, *, name: str = "Note") -> NoteModel:
        return await get_or_404(self.session, NoteModel, note_id, name=name)

    async def find_for_dedup(
        self,
        *,
        document_id: str | None,
        section_id: str | None,
        content_hash: str,
        cutoff: datetime,
    ) -> NoteModel | None:
        result = await self.session.execute(
            select(NoteModel).where(
                NoteModel.document_id == document_id,
                NoteModel.section_id == section_id,
                NoteModel.content_hash == content_hash,
                NoteModel.created_at >= cutoff,
            )
        )
        return result.scalar_one_or_none()

    # -- list reads --------------------------------------------------------

    async def count_all(self) -> int:
        result = await self.session.execute(select(func.count(NoteModel.id)))
        return result.scalar_one()

    async def list_recent(self, limit: int = 8) -> list[tuple[str, str]]:
        result = await self.session.execute(
            select(NoteModel.id, NoteModel.content)
            .order_by(NoteModel.updated_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def autocomplete_content(self, prefix: str, limit: int = 8) -> list[tuple[str, str]]:
        result = await self.session.execute(
            select(NoteModel.id, NoteModel.content)
            .where(NoteModel.content.ilike(f"{prefix}%"))
            .order_by(NoteModel.updated_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    # -- writes ------------------------------------------------------------

    def stage(self, note: NoteModel) -> None:
        """Stage a NoteModel for insert/update without committing.

        Use when the caller needs to perform additional session work in the
        same transaction (FTS sync, tag index sync, etc.) before commit.
        """
        self.session.add(note)

    async def commit(self) -> None:
        await self.session.commit()

    async def delete_by_id(self, note_id: str) -> None:
        await self.session.execute(delete(NoteModel).where(NoteModel.id == note_id))
        await self.session.commit()

    # -- collection / source membership reads ------------------------------

    async def collection_ids_for(self, note_id: str) -> list[str]:
        result = await self.session.execute(
            select(CollectionMemberModel.collection_id).where(
                CollectionMemberModel.member_id == note_id,
                CollectionMemberModel.member_type == "note",
            )
        )
        return list(result.scalars().all())

    async def source_document_ids_for(self, note_id: str) -> list[str]:
        result = await self.session.execute(
            select(NoteSourceModel.document_id).where(NoteSourceModel.note_id == note_id)
        )
        return list(result.scalars().all())

    # -- note links --------------------------------------------------------

    async def find_link(
        self, source_note_id: str, target_note_id: str, link_type: str
    ) -> NoteLinkModel | None:
        result = await self.session.execute(
            select(NoteLinkModel).where(
                NoteLinkModel.source_note_id == source_note_id,
                NoteLinkModel.target_note_id == target_note_id,
                NoteLinkModel.link_type == link_type,
            )
        )
        return result.scalar_one_or_none()

    async def create_link(
        self,
        *,
        source_note_id: str,
        target_note_id: str,
        link_type: str,
        created_at: datetime,
    ) -> NoteLinkModel:
        link = NoteLinkModel(
            id=str(uuid.uuid4()),
            source_note_id=source_note_id,
            target_note_id=target_note_id,
            link_type=link_type,
            created_at=created_at,
        )
        self.session.add(link)
        await self.session.commit()
        await self.session.refresh(link)
        return link

    async def delete_link(self, link: NoteLinkModel) -> None:
        await self.session.delete(link)
        await self.session.commit()

    async def outgoing_links_with_content(self, note_id: str) -> Sequence[NoteLinkWithContent]:
        rows = (
            await self.session.execute(
                select(NoteLinkModel, NoteModel.content)
                .join(NoteModel, NoteLinkModel.target_note_id == NoteModel.id)
                .where(NoteLinkModel.source_note_id == note_id)
                .order_by(NoteLinkModel.created_at.desc())
            )
        ).all()
        return [NoteLinkWithContent(link=r[0], content=r[1]) for r in rows]

    async def incoming_links_with_content(self, note_id: str) -> Sequence[NoteLinkWithContent]:
        rows = (
            await self.session.execute(
                select(NoteLinkModel, NoteModel.content)
                .join(NoteModel, NoteLinkModel.source_note_id == NoteModel.id)
                .where(NoteLinkModel.target_note_id == note_id)
                .order_by(NoteLinkModel.created_at.desc())
            )
        ).all()
        return [NoteLinkWithContent(link=r[0], content=r[1]) for r in rows]


def get_note_repo(session: AsyncSession = Depends(get_db)) -> NoteRepo:
    return NoteRepo(session)
