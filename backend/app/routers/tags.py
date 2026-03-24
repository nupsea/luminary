"""CRUD endpoints for canonical tags.

Routes:
  GET    /tags                      -- flat list sorted by note_count DESC
  GET    /tags/tree                 -- hierarchical structure with note_count (includes descendants)
  GET    /tags/autocomplete?q=      -- prefix-search, up to 10 results
  GET    /tags/{tag_id}/notes       -- notes with this tag or any child tag
  POST   /tags                      -- create canonical tag
  PUT    /tags/{tag_id}             -- rename display_name or re-parent
  DELETE /tags/{tag_id}             -- 409 if note_count > 0
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CanonicalTagModel, NoteModel, NoteTagIndexModel, TagAliasModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tags", tags=["tags"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TagResponse(BaseModel):
    id: str
    display_name: str
    parent_tag: str | None
    note_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TagTreeItem(BaseModel):
    id: str
    display_name: str
    note_count: int  # inclusive of descendants
    children: list["TagTreeItem"]


TagTreeItem.model_rebuild()


class TagAutocompleteResult(BaseModel):
    id: str
    display_name: str
    parent_tag: str | None
    note_count: int


class TagCreateRequest(BaseModel):
    id: str  # full slug e.g. 'programming/python'
    display_name: str
    parent_tag: str | None = None


class TagUpdateRequest(BaseModel):
    display_name: str | None = None
    parent_tag: str | None = None


class NoteItem(BaseModel):
    id: str
    content: str
    tags: list[str]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(tag: CanonicalTagModel) -> TagResponse:
    return TagResponse(
        id=tag.id,
        display_name=tag.display_name,
        parent_tag=tag.parent_tag,
        note_count=tag.note_count,
        created_at=tag.created_at,
    )


def _compute_inclusive_count(
    tag_id: str,
    count_by_id: dict[str, int],
    children_by_parent: dict[str, list[str]],
) -> int:
    """Recursively sum note_count for tag + all descendants."""
    direct = count_by_id.get(tag_id, 0)
    child_sum = sum(
        _compute_inclusive_count(child, count_by_id, children_by_parent)
        for child in children_by_parent.get(tag_id, [])
    )
    return direct + child_sum


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/autocomplete", response_model=list[TagAutocompleteResult])
async def autocomplete_tags(
    q: str = Query(default=""),
    session: AsyncSession = Depends(get_db),
) -> list[TagAutocompleteResult]:
    """Return up to 10 canonical tags matching the prefix q, sorted by note_count DESC."""
    result = await session.execute(
        select(CanonicalTagModel)
        .where(CanonicalTagModel.id.like(f"{q}%"))
        .order_by(CanonicalTagModel.note_count.desc())
        .limit(10)
    )
    tags = result.scalars().all()
    return [
        TagAutocompleteResult(
            id=t.id,
            display_name=t.display_name,
            parent_tag=t.parent_tag,
            note_count=t.note_count,
        )
        for t in tags
    ]


@router.get("/tree", response_model=list[TagTreeItem])
async def get_tag_tree(
    session: AsyncSession = Depends(get_db),
) -> list[TagTreeItem]:
    """Return all canonical tags as a hierarchical tree.

    node.note_count is the inclusive count (direct notes + all descendants).
    """
    all_tags_result = await session.execute(
        select(CanonicalTagModel).order_by(CanonicalTagModel.id)
    )
    all_tags = list(all_tags_result.scalars().all())

    count_by_id: dict[str, int] = {t.id: t.note_count for t in all_tags}
    children_by_parent: dict[str, list[str]] = {}
    for t in all_tags:
        if t.parent_tag:
            children_by_parent.setdefault(t.parent_tag, []).append(t.id)

    # Build tree: top-level nodes only (no parent_tag)
    top_level: list[TagTreeItem] = []
    for t in all_tags:
        if t.parent_tag is None:
            children = [
                TagTreeItem(
                    id=child_id,
                    display_name=next(
                        (x.display_name for x in all_tags if x.id == child_id), child_id
                    ),
                    note_count=_compute_inclusive_count(child_id, count_by_id, children_by_parent),
                    children=[],  # max 2 levels supported in query; deeper children truncated
                )
                for child_id in children_by_parent.get(t.id, [])
            ]
            top_level.append(
                TagTreeItem(
                    id=t.id,
                    display_name=t.display_name,
                    note_count=_compute_inclusive_count(t.id, count_by_id, children_by_parent),
                    children=children,
                )
            )

    return top_level


@router.get("", response_model=list[TagResponse])
async def list_tags(
    session: AsyncSession = Depends(get_db),
) -> list[TagResponse]:
    """Return all canonical tags sorted by note_count DESC."""
    result = await session.execute(
        select(CanonicalTagModel).order_by(CanonicalTagModel.note_count.desc())
    )
    tags = result.scalars().all()
    return [_to_response(t) for t in tags]


@router.post("", response_model=TagResponse, status_code=201)
async def create_tag(
    req: TagCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> TagResponse:
    """Create a canonical tag. Returns 409 if the slug already exists."""
    existing = (
        await session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id == req.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Tag already exists")

    tag = CanonicalTagModel(
        id=req.id,
        display_name=req.display_name,
        parent_tag=req.parent_tag,
        note_count=0,
        created_at=datetime.now(UTC),
    )
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    logger.info("Created canonical tag id=%r", tag.id)
    return _to_response(tag)


@router.get("/{tag_id}/notes", response_model=list[NoteItem])
async def get_notes_for_tag(
    tag_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[NoteItem]:
    """Return notes tagged with tag_id or any child tag (prefix match)."""
    note_ids_result = await session.execute(
        select(NoteTagIndexModel.note_id)
        .where(
            (NoteTagIndexModel.tag_full == tag_id)
            | NoteTagIndexModel.tag_full.like(f"{tag_id}/%")
        )
        .distinct()
    )
    note_ids = [row[0] for row in note_ids_result.all()]
    if not note_ids:
        return []
    notes_result = await session.execute(
        select(NoteModel).where(NoteModel.id.in_(note_ids))
    )
    notes = notes_result.scalars().all()
    return [NoteItem(id=n.id, content=n.content, tags=n.tags or []) for n in notes]


@router.put("/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: str,
    req: TagUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> TagResponse:
    """Rename a tag's display_name or re-parent it."""
    tag = (
        await session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id == tag_id)
        )
    ).scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")

    if req.display_name is not None:
        tag.display_name = req.display_name
    if req.parent_tag is not None:
        tag.parent_tag = req.parent_tag

    await session.commit()
    await session.refresh(tag)
    logger.info("Updated canonical tag id=%r", tag_id)
    return _to_response(tag)


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a canonical tag. Returns 409 if the tag has notes (note_count > 0)."""
    tag = (
        await session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id == tag_id)
        )
    ).scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.note_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Tag '{tag_id}' has {tag.note_count} notes."
                " Remove notes from this tag before deleting."
            ),
        )

    # Remove any aliases pointing to this tag
    await session.execute(
        delete(TagAliasModel).where(TagAliasModel.canonical_tag_id == tag_id)
    )
    await session.execute(
        delete(CanonicalTagModel).where(CanonicalTagModel.id == tag_id)
    )
    await session.commit()
    logger.info("Deleted canonical tag id=%r", tag_id)
