"""CRUD endpoints for notes.

Routes: POST /notes, GET /notes, PUT /notes/{id}, DELETE /notes/{id}, GET /notes/groups.
"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import NoteModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notes", tags=["notes"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class NoteCreateRequest(BaseModel):
    document_id: str | None = None
    chunk_id: str | None = None
    content: str
    tags: list[str] = []
    group_name: str | None = None


class NoteUpdateRequest(BaseModel):
    content: str | None = None
    tags: list[str] | None = None
    group_name: str | None = None


class NoteResponse(BaseModel):
    id: str
    document_id: str | None
    chunk_id: str | None
    content: str
    tags: list[str]
    group_name: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GroupInfo(BaseModel):
    name: str
    count: int


class TagInfo(BaseModel):
    name: str
    count: int


class GroupsResponse(BaseModel):
    groups: list[GroupInfo]
    tags: list[TagInfo]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(note: NoteModel) -> NoteResponse:
    return NoteResponse(
        id=note.id,
        document_id=note.document_id,
        chunk_id=note.chunk_id,
        content=note.content,
        tags=note.tags or [],
        group_name=note.group_name,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=NoteResponse, status_code=201)
async def create_note(
    req: NoteCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> NoteResponse:
    """Create a new note."""
    note = NoteModel(
        id=str(uuid.uuid4()),
        document_id=req.document_id,
        chunk_id=req.chunk_id,
        content=req.content,
        tags=req.tags,
        group_name=req.group_name,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    logger.info("Created note", extra={"note_id": note.id})
    return _to_response(note)


@router.get("/groups", response_model=GroupsResponse)
async def get_groups(session: AsyncSession = Depends(get_db)) -> GroupsResponse:
    """Return distinct group names (with counts) and distinct tags (with counts)."""
    # Groups
    group_result = await session.execute(
        select(NoteModel.group_name, func.count(NoteModel.id))
        .where(NoteModel.group_name.isnot(None))
        .group_by(NoteModel.group_name)
        .order_by(NoteModel.group_name)
    )
    groups = [
        GroupInfo(name=row[0], count=row[1]) for row in group_result.fetchall()
    ]

    # Tags — use JSON_EACH to explode the JSON array stored in the tags column
    tag_result = await session.execute(
        text(
            "SELECT j.value, COUNT(*) as cnt "
            "FROM notes, json_each(notes.tags) AS j "
            "GROUP BY j.value "
            "ORDER BY j.value"
        )
    )
    tags = [TagInfo(name=row[0], count=row[1]) for row in tag_result.fetchall()]

    return GroupsResponse(groups=groups, tags=tags)


@router.get("", response_model=list[NoteResponse])
async def list_notes(
    document_id: str | None = Query(default=None),
    group: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[NoteResponse]:
    """List notes with optional filters."""
    stmt = select(NoteModel).order_by(NoteModel.updated_at.desc())

    if document_id:
        stmt = stmt.where(NoteModel.document_id == document_id)
    if group:
        stmt = stmt.where(NoteModel.group_name == group)
    if tag:
        # Filter notes whose tags JSON array contains the requested tag via EXISTS
        stmt = stmt.where(
            text(
                "EXISTS (SELECT 1 FROM json_each(notes.tags) WHERE json_each.value = :tag)"
            ).bindparams(tag=tag)
        )

    result = await session.execute(stmt)
    notes = result.scalars().all()
    return [_to_response(n) for n in notes]


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: str,
    req: NoteUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> NoteResponse:
    """Update a note's content, tags, or group."""
    result = await session.execute(select(NoteModel).where(NoteModel.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    if req.content is not None:
        note.content = req.content
    if req.tags is not None:
        note.tags = req.tags
    if req.group_name is not None:
        note.group_name = req.group_name
    note.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(note)
    logger.info("Updated note", extra={"note_id": note_id})
    return _to_response(note)


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a note by ID."""
    result = await session.execute(select(NoteModel).where(NoteModel.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    await session.execute(delete(NoteModel).where(NoteModel.id == note_id))
    await session.commit()
    logger.info("Deleted note", extra={"note_id": note_id})
