"""Repository for `CollectionModel` and `CollectionMemberModel`."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CollectionMemberModel, CollectionModel
from app.services.repo_helpers import get_or_404


class CollectionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- single-row reads --------------------------------------------------

    async def get_or_404(self, collection_id: str) -> CollectionModel:
        return await get_or_404(
            self.session, CollectionModel, collection_id, name="Collection"
        )

    async def find_by_auto_document_id(self, document_id: str) -> CollectionModel | None:
        result = await self.session.execute(
            select(CollectionModel).where(CollectionModel.auto_document_id == document_id)
        )
        return result.scalar_one_or_none()

    # -- list reads --------------------------------------------------------

    async def list_all(self) -> Sequence[CollectionModel]:
        result = await self.session.execute(
            select(CollectionModel).order_by(
                CollectionModel.sort_order, CollectionModel.name
            )
        )
        return result.scalars().all()

    async def member_counts(self) -> dict[tuple[str, str], int]:
        """Return {(collection_id, member_type): count}."""
        result = await self.session.execute(
            select(
                CollectionMemberModel.collection_id,
                CollectionMemberModel.member_type,
                func.count(CollectionMemberModel.member_id),
            ).group_by(
                CollectionMemberModel.collection_id, CollectionMemberModel.member_type
            )
        )
        return {(cid, mtype): count for cid, mtype, count in result.all()}

    async def child_ids(self, parent_id: str) -> list[str]:
        result = await self.session.execute(
            select(CollectionModel.id).where(
                CollectionModel.parent_collection_id == parent_id
            )
        )
        return [row[0] for row in result.all()]

    # -- writes ------------------------------------------------------------

    async def create(
        self,
        *,
        name: str,
        description: str | None = None,
        color: str = "#6366F1",
        icon: str | None = None,
        parent_collection_id: str | None = None,
        sort_order: int = 0,
        auto_document_id: str | None = None,
    ) -> CollectionModel:
        now = datetime.now(UTC)
        col = CollectionModel(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            color=color,
            icon=icon,
            parent_collection_id=parent_collection_id,
            sort_order=sort_order,
            auto_document_id=auto_document_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(col)
        await self.session.commit()
        await self.session.refresh(col)
        return col

    async def update_fields(
        self,
        col: CollectionModel,
        *,
        name: str | None = None,
        description: str | None = None,
        color: str | None = None,
        icon: str | None = None,
        sort_order: int | None = None,
    ) -> CollectionModel:
        if name is not None:
            col.name = name
        if description is not None:
            col.description = description
        if color is not None:
            col.color = color
        if icon is not None:
            col.icon = icon
        if sort_order is not None:
            col.sort_order = sort_order
        col.updated_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(col)
        return col

    async def delete_with_children(self, collection_id: str) -> None:
        """Delete collection, its members, and all child collections + members.

        Caller is expected to have validated that the collection exists.
        """
        child_ids = await self.child_ids(collection_id)
        for child_id in child_ids:
            await self.session.execute(
                delete(CollectionMemberModel).where(
                    CollectionMemberModel.collection_id == child_id
                )
            )
        await self.session.execute(
            delete(CollectionMemberModel).where(
                CollectionMemberModel.collection_id == collection_id
            )
        )
        for child_id in child_ids:
            await self.session.execute(
                delete(CollectionModel).where(CollectionModel.id == child_id)
            )
        await self.session.execute(
            delete(CollectionModel).where(CollectionModel.id == collection_id)
        )
        await self.session.commit()

    # -- members -----------------------------------------------------------

    async def add_members(
        self,
        collection_id: str,
        member_ids: list[str],
        *,
        member_type: str,
    ) -> int:
        """Idempotent INSERT OR IGNORE. Returns number of rows attempted."""
        added = 0
        now_iso = datetime.now(UTC).isoformat()
        for mid in member_ids:
            await self.session.execute(
                text(
                    "INSERT OR IGNORE INTO collection_members"
                    " (id, member_id, collection_id, member_type, added_at)"
                    " VALUES (:id, :member_id, :collection_id, :member_type, :added_at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "member_id": mid,
                    "collection_id": collection_id,
                    "member_type": member_type,
                    "added_at": now_iso,
                },
            )
            added += 1
        await self.session.commit()
        return added

    async def remove_member(
        self,
        collection_id: str,
        member_id: str,
        member_type: str | None = None,
    ) -> None:
        """Remove a member from a collection.

        When member_type is None the legacy behaviour is preserved and every
        membership row matching (collection_id, member_id) is deleted -- this
        was safe when notes and documents lived in disjoint UUID spaces. When
        member_type is given the delete is scoped to that type, which is what
        cross-content membership requires.
        """
        stmt = delete(CollectionMemberModel).where(
            CollectionMemberModel.collection_id == collection_id,
            CollectionMemberModel.member_id == member_id,
        )
        if member_type is not None:
            stmt = stmt.where(CollectionMemberModel.member_type == member_type)
        await self.session.execute(stmt)
        await self.session.commit()

    async def members_of(
        self, collection_id: str
    ) -> list[tuple[str, str]]:
        """Return list of (member_id, member_type) for a collection."""
        result = await self.session.execute(
            select(
                CollectionMemberModel.member_id, CollectionMemberModel.member_type
            ).where(CollectionMemberModel.collection_id == collection_id)
        )
        return [(mid, mtype) for mid, mtype in result.all()]

    async def count_members(self, collection_id: str) -> int:
        result = await self.session.execute(
            select(func.count(CollectionMemberModel.member_id)).where(
                CollectionMemberModel.collection_id == collection_id
            )
        )
        return result.scalar() or 0

    async def refs_for_members(
        self, member_ids: list[str], *, member_type: str
    ) -> dict[str, list[tuple[str, str, str]]]:
        """Batch-load collection refs for a list of members.

        Returns {member_id: [(collection_id, name, color), ...]} where the
        inner list is ordered by CollectionModel.sort_order ASC, name ASC --
        the same order as list_all(). Used by /documents and /notes list
        endpoints to populate membership chips without N+1 queries.
        """
        if not member_ids:
            return {}
        # Raw SQL bypasses any SQLAlchemy from-clause auto-detection quirks
        # that have surfaced in cross-test runs; the query is simple enough.
        placeholders = ",".join(f":m{i}" for i in range(len(member_ids)))
        params: dict[str, str] = {"member_type": member_type}
        for i, mid in enumerate(member_ids):
            params[f"m{i}"] = mid
        rows = (
            await self.session.execute(
                text(
                    "SELECT cm.member_id, c.id, c.name, c.color "
                    "FROM collection_members cm "
                    "JOIN collections c ON c.id = cm.collection_id "
                    f"WHERE cm.member_id IN ({placeholders}) "
                    "AND cm.member_type = :member_type "
                    "ORDER BY c.sort_order, c.name"
                ),
                params,
            )
        ).all()
        out: dict[str, list[tuple[str, str, str]]] = {}
        for member_id, cid, name, color in rows:
            out.setdefault(member_id, []).append((cid, name, color))
        return out


def get_collection_repo(session: AsyncSession = Depends(get_db)) -> CollectionRepo:
    return CollectionRepo(session)
