"""CRUD endpoints for note collections.

Routes:
  POST   /collections               -- create a collection
  GET    /collections/tree          -- return full tree (2 levels)
  GET    /collections/{id}          -- get single collection
  PUT    /collections/{id}          -- rename / update a collection
  DELETE /collections/{id}          -- delete collection (members removed, notes preserved)
  POST   /collections/{id}/notes    -- add notes to collection (idempotent)
  DELETE /collections/{id}/notes/{note_id} -- remove a note from collection
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import NoteCollectionMemberModel, NoteCollectionModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collections", tags=["collections"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CollectionCreateRequest(BaseModel):
    name: str
    description: str | None = None
    color: str = "#6366F1"
    icon: str | None = None
    parent_collection_id: str | None = None
    sort_order: int = 0


class CollectionUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    sort_order: int | None = None


class CollectionResponse(BaseModel):
    id: str
    name: str
    description: str | None
    color: str
    icon: str | None
    parent_collection_id: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CollectionTreeItem(BaseModel):
    id: str
    name: str
    color: str
    icon: str | None
    note_count: int
    children: list["CollectionTreeItem"]


CollectionTreeItem.model_rebuild()


class AddNotesRequest(BaseModel):
    note_ids: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(col: NoteCollectionModel) -> CollectionResponse:
    return CollectionResponse(
        id=col.id,
        name=col.name,
        description=col.description,
        color=col.color,
        icon=col.icon,
        parent_collection_id=col.parent_collection_id,
        sort_order=col.sort_order,
        created_at=col.created_at,
        updated_at=col.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=CollectionResponse, status_code=201)
async def create_collection(
    req: CollectionCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Create a new collection. Parent must be a top-level collection (max 2-level nesting)."""
    if req.parent_collection_id is not None:
        parent = (
            await session.execute(
                select(NoteCollectionModel).where(
                    NoteCollectionModel.id == req.parent_collection_id
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise HTTPException(status_code=404, detail="Parent collection not found")
        if parent.parent_collection_id is not None:
            raise HTTPException(
                status_code=422,
                detail="Max nesting depth is 2. The parent already has a parent.",
            )

    col = NoteCollectionModel(
        id=str(uuid.uuid4()),
        name=req.name,
        description=req.description,
        color=req.color,
        icon=req.icon,
        parent_collection_id=req.parent_collection_id,
        sort_order=req.sort_order,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(col)
    await session.commit()
    await session.refresh(col)
    logger.info("Created collection id=%s name=%r", col.id, col.name)
    return _to_response(col)


@router.get("/tree", response_model=list[CollectionTreeItem])
async def get_collection_tree(
    session: AsyncSession = Depends(get_db),
) -> list[CollectionTreeItem]:
    """Return all collections as a 2-level nested tree with note counts."""
    # Load all collections
    all_cols_result = await session.execute(
        select(NoteCollectionModel).order_by(
            NoteCollectionModel.sort_order, NoteCollectionModel.name
        )
    )
    all_cols = list(all_cols_result.scalars().all())

    # Load note counts per collection
    count_rows = (
        await session.execute(
            select(
                NoteCollectionMemberModel.collection_id,
                func.count(NoteCollectionMemberModel.note_id),
            ).group_by(NoteCollectionMemberModel.collection_id)
        )
    ).all()
    note_counts: dict[str, int] = {row[0]: row[1] for row in count_rows}

    # Build lookup dict
    by_id: dict[str, NoteCollectionModel] = {c.id: c for c in all_cols}

    # Assemble tree: top-level first, then attach children
    top_level: list[CollectionTreeItem] = []
    for col in all_cols:
        if col.parent_collection_id is None:
            children = [
                CollectionTreeItem(
                    id=child.id,
                    name=child.name,
                    color=child.color,
                    icon=child.icon,
                    note_count=note_counts.get(child.id, 0),
                    children=[],
                )
                for child in all_cols
                if child.parent_collection_id == col.id
            ]
            top_level.append(
                CollectionTreeItem(
                    id=col.id,
                    name=col.name,
                    color=col.color,
                    icon=col.icon,
                    note_count=note_counts.get(col.id, 0),
                    children=children,
                )
            )

    # Suppress unused variable warning from by_id lookup
    _ = by_id
    return top_level


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: str,
    session: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    col = (
        await session.execute(
            select(NoteCollectionModel).where(NoteCollectionModel.id == collection_id)
        )
    ).scalar_one_or_none()
    if col is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return _to_response(col)


@router.put("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: str,
    req: CollectionUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    col = (
        await session.execute(
            select(NoteCollectionModel).where(NoteCollectionModel.id == collection_id)
        )
    ).scalar_one_or_none()
    if col is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    if req.name is not None:
        col.name = req.name
    if req.description is not None:
        col.description = req.description
    if req.color is not None:
        col.color = req.color
    if req.icon is not None:
        col.icon = req.icon
    if req.sort_order is not None:
        col.sort_order = req.sort_order
    col.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(col)
    logger.info("Updated collection id=%s", collection_id)
    return _to_response(col)


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a collection. Member rows are removed; notes themselves are NOT deleted."""
    col = (
        await session.execute(
            select(NoteCollectionModel).where(NoteCollectionModel.id == collection_id)
        )
    ).scalar_one_or_none()
    if col is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Delete child collections' members first
    child_ids_result = await session.execute(
        select(NoteCollectionModel.id).where(
            NoteCollectionModel.parent_collection_id == collection_id
        )
    )
    child_ids = [row[0] for row in child_ids_result.all()]
    for child_id in child_ids:
        await session.execute(
            delete(NoteCollectionMemberModel).where(
                NoteCollectionMemberModel.collection_id == child_id
            )
        )

    # Delete members of this collection
    await session.execute(
        delete(NoteCollectionMemberModel).where(
            NoteCollectionMemberModel.collection_id == collection_id
        )
    )

    # Delete child collections
    for child_id in child_ids:
        await session.execute(
            delete(NoteCollectionModel).where(NoteCollectionModel.id == child_id)
        )

    # Delete the collection itself
    await session.execute(
        delete(NoteCollectionModel).where(NoteCollectionModel.id == collection_id)
    )
    await session.commit()
    logger.info("Deleted collection id=%s", collection_id)


@router.post("/{collection_id}/notes", status_code=201)
async def add_notes_to_collection(
    collection_id: str,
    req: AddNotesRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Add notes to a collection. Duplicate memberships are silently ignored."""
    col = (
        await session.execute(
            select(NoteCollectionModel).where(NoteCollectionModel.id == collection_id)
        )
    ).scalar_one_or_none()
    if col is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    added = 0
    for note_id in req.note_ids:
        await session.execute(
            text(
                "INSERT OR IGNORE INTO note_collection_members"
                " (id, note_id, collection_id, added_at)"
                " VALUES (:id, :note_id, :collection_id, :added_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "note_id": note_id,
                "collection_id": collection_id,
                "added_at": datetime.now(UTC).isoformat(),
            },
        )
        added += 1

    await session.commit()
    logger.info("Added %d notes to collection id=%s", added, collection_id)
    return {"added": added, "collection_id": collection_id}


@router.delete("/{collection_id}/notes/{note_id}", status_code=204)
async def remove_note_from_collection(
    collection_id: str,
    note_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Remove a note from a collection (membership only; note is not deleted)."""
    await session.execute(
        delete(NoteCollectionMemberModel).where(
            NoteCollectionMemberModel.collection_id == collection_id,
            NoteCollectionMemberModel.note_id == note_id,
        )
    )
    await session.commit()
