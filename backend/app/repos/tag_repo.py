"""Repository for `CanonicalTagModel` and related tag tables.

Owns all `session.execute / add / commit / delete` calls for the simple
tag CRUD endpoints. The merge / normalization-accept / migrate-naming
endpoints in `routers/tags.py` are kept inline because they are
multi-entity transactional flows with bespoke rollback semantics
(same exception applied to `CollectionRepo.migrate-naming`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    CanonicalTagModel,
    NoteModel,
    NoteTagIndexModel,
    TagAliasModel,
)
from app.services.repo_helpers import get_or_404


class TagRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- single-row reads --------------------------------------------------

    async def find_by_id(self, tag_id: str) -> CanonicalTagModel | None:
        result = await self.session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id == tag_id)
        )
        return result.scalar_one_or_none()

    async def get_or_404(self, tag_id: str) -> CanonicalTagModel:
        return await get_or_404(self.session, CanonicalTagModel, tag_id, name="Tag")

    # -- list reads --------------------------------------------------------

    async def list_by_count(self) -> Sequence[CanonicalTagModel]:
        result = await self.session.execute(
            select(CanonicalTagModel).order_by(CanonicalTagModel.note_count.desc())
        )
        return result.scalars().all()

    async def list_by_id(self) -> Sequence[CanonicalTagModel]:
        result = await self.session.execute(
            select(CanonicalTagModel).order_by(CanonicalTagModel.id)
        )
        return result.scalars().all()

    async def autocomplete(self, prefix: str, *, limit: int = 10) -> Sequence[CanonicalTagModel]:
        result = await self.session.execute(
            select(CanonicalTagModel)
            .where(CanonicalTagModel.id.like(f"{prefix}%"))
            .order_by(CanonicalTagModel.note_count.desc())
            .limit(limit)
        )
        return result.scalars().all()

    # -- tag-index reads ---------------------------------------------------

    async def note_ids_with_tag(
        self, tag_id: str, *, include_descendants: bool = False
    ) -> list[str]:
        """Return note IDs that reference `tag_id` (optionally + descendants)."""
        stmt = select(NoteTagIndexModel.note_id).distinct()
        if include_descendants:
            stmt = stmt.where(
                (NoteTagIndexModel.tag_full == tag_id)
                | NoteTagIndexModel.tag_full.like(f"{tag_id}/%")
            )
        else:
            stmt = stmt.where(NoteTagIndexModel.tag_full == tag_id)
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def load_notes(self, note_ids: Sequence[str]) -> Sequence[NoteModel]:
        if not note_ids:
            return []
        result = await self.session.execute(
            select(NoteModel).where(NoteModel.id.in_(list(note_ids)))
        )
        return result.scalars().all()

    # -- writes ------------------------------------------------------------

    async def create(
        self,
        *,
        id: str,
        display_name: str,
        parent_tag: str | None,
    ) -> CanonicalTagModel:
        tag = CanonicalTagModel(
            id=id,
            display_name=display_name,
            parent_tag=parent_tag,
            note_count=0,
            created_at=datetime.now(UTC),
        )
        self.session.add(tag)
        await self.session.commit()
        await self.session.refresh(tag)
        return tag

    async def update_fields(
        self,
        tag: CanonicalTagModel,
        *,
        display_name: str | None = None,
        parent_tag: str | None = None,
        parent_tag_set: bool = False,
    ) -> CanonicalTagModel:
        """Update mutable fields on `tag`.

        `parent_tag_set` distinguishes "not supplied" from "explicitly null"
        for the optional parent_tag column.
        """
        if display_name is not None:
            tag.display_name = display_name
        if parent_tag_set:
            tag.parent_tag = parent_tag
        await self.session.commit()
        await self.session.refresh(tag)
        return tag

    async def delete_with_aliases(self, tag_id: str) -> None:
        """Delete the canonical tag and any aliases pointing to it.

        Caller is expected to have validated existence + note_count == 0.
        """
        await self.session.execute(
            delete(TagAliasModel).where(TagAliasModel.canonical_tag_id == tag_id)
        )
        await self.session.execute(
            delete(CanonicalTagModel).where(CanonicalTagModel.id == tag_id)
        )
        await self.session.commit()


def get_tag_repo(session: AsyncSession = Depends(get_db)) -> TagRepo:
    return TagRepo(session)
