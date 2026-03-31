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
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DocumentModel, NoteCollectionMemberModel, NoteCollectionModel
from app.services.collection_health import get_collection_health_service
from app.services.export_service import get_export_service

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
    auto_document_id: str | None = None
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
        auto_document_id=getattr(col, "auto_document_id", None),
        sort_order=col.sort_order,
        created_at=col.created_at,
        updated_at=col.updated_at,
    )

# Color palette for auto-collections based on content_type
_AUTO_COLLECTION_COLORS: dict[str, str] = {
    "book": "#8B5CF6",       # violet
    "paper": "#3B82F6",      # blue
    "conversation": "#F59E0B",  # amber
    "notes": "#10B981",      # emerald
    "code": "#6366F1",       # indigo
}

# Human-readable doc type suffixes for collection names
_DOC_TYPE_LABELS: dict[str, str] = {
    "book": "Book",
    "paper": "Paper",
    "conversation": "Video",
    "notes": "Notes",
    "code": "Code",
}


def _make_collection_name(title: str, content_type: str) -> str:
    """Generate a concise collection name from a document title + type.

    Examples:
      - "DDIA.pdf" + "book"          -> "DDIA_Book"
      - "Designing Data-Intensive Applications" + "book" -> "DDIA_Book"
      - "Andrej Karpathy on Code Agents, AutoResearch, and the Loopy Era of AI"
            + "conversation" -> "Code_Agents_Karpathy_Video"
    """
    suffix = _DOC_TYPE_LABELS.get(content_type, content_type.capitalize())

    # Strip file extensions
    name = re.sub(r"\.(pdf|epub|docx?|txt|md)$", "", title, flags=re.IGNORECASE).strip()

    # If the remaining name is already short (≤ 20 chars, like "DDIA"), use as-is
    if len(name) <= 20:
        # Replace spaces/hyphens with underscores, collapse multiples
        short = re.sub(r"[\s\-]+", "_", name)
        short = re.sub(r"_+", "_", short).strip("_")
        return f"{short}_{suffix}"

    # For longer titles, extract key words (capitalized, acronyms, proper nouns)
    # Remove common filler words
    filler = {
        "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "with",
        "by", "is", "at", "from", "as", "into", "its", "this", "that", "how",
        "era", "about",
    }

    words = re.findall(r"[A-Za-z0-9]+", name)
    key_words: list[str] = []
    for w in words:
        # Always keep all-caps / acronyms (DDIA, AI, LLM)
        if w.isupper() and len(w) >= 2:
            key_words.append(w)
        # Keep capitalized words that aren't filler
        elif w[0].isupper() and w.lower() not in filler:
            key_words.append(w)

    # Fallback: if we filtered too aggressively, take first 3 significant words
    if len(key_words) < 2:
        key_words = [w for w in words if w.lower() not in filler][:3]

    # Cap at 3 key words to keep it short
    key_words = key_words[:3]
    short = "_".join(key_words)

    return f"{short}_{suffix}"


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


# NOTE: /by-document and /auto routes MUST be registered BEFORE /{collection_id}
# to prevent FastAPI from matching "by-document" or "auto" as a collection_id wildcard.


@router.get("/by-document/{document_id}", response_model=CollectionResponse)
async def get_auto_collection_by_document(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Return the auto-collection for a document, or 404 if none exists."""
    col = (
        await session.execute(
            select(NoteCollectionModel).where(
                NoteCollectionModel.auto_document_id == document_id
            )
        )
    ).scalar_one_or_none()
    if col is None:
        raise HTTPException(status_code=404, detail="No auto-collection for this document")
    return _to_response(col)


@router.post("/auto/{document_id}", response_model=CollectionResponse, status_code=201)
async def create_auto_collection(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Create auto-collection for a document. Idempotent -- returns existing."""
    # Check if one already exists
    existing = (
        await session.execute(
            select(NoteCollectionModel).where(
                NoteCollectionModel.auto_document_id == document_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _to_response(existing)

    # Fetch document title
    doc = (
        await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    color = _AUTO_COLLECTION_COLORS.get(doc.content_type, "#6366F1")
    col_name = _make_collection_name(doc.title, doc.content_type)
    col = NoteCollectionModel(
        id=str(uuid.uuid4()),
        name=col_name,
        color=color,
        auto_document_id=document_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(col)
    await session.commit()
    await session.refresh(col)
    logger.info("Created auto-collection id=%s for document=%s", col.id, document_id)
    return _to_response(col)


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


# NOTE: These export and health routes are registered BEFORE /{collection_id}/notes/{note_id}
# to avoid ambiguity. The /export and /health path segments are not note_id wildcards.
@router.get("/{collection_id}/export")
async def export_collection(
    collection_id: str,
    format: str = "markdown",
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Export a collection as a Markdown vault zip or Anki .apkg file.

    ?format=markdown  -- returns .zip with one .md per note and YAML frontmatter
    ?format=anki      -- returns .apkg (genanki) with flashcards in this collection's deck
    """
    if format not in ("markdown", "anki"):
        raise HTTPException(status_code=422, detail="format must be 'markdown' or 'anki'")

    svc = get_export_service()

    try:
        if format == "markdown":
            data = await svc.export_collection_markdown(collection_id, session)
            col = (
                await session.execute(
                    select(NoteCollectionModel).where(NoteCollectionModel.id == collection_id)
                )
            ).scalar_one_or_none()
            slug = col.name.lower().replace(" ", "-") if col else collection_id[:8]
            slug = re.sub(r"[^\w-]", "", slug)[:40] or "vault"
            filename = f"{slug}-vault.zip"
            return Response(
                content=data,
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
        else:
            data, card_count = await svc.export_collection_anki(collection_id, session)
            col = (
                await session.execute(
                    select(NoteCollectionModel).where(NoteCollectionModel.id == collection_id)
                )
            ).scalar_one_or_none()
            slug = col.name.lower().replace(" ", "-") if col else collection_id[:8]
            slug = re.sub(r"[^\w-]", "", slug)[:40] or "deck"
            filename = f"{slug}.apkg"
            headers: dict[str, str] = {
                "Content-Disposition": f"attachment; filename={filename}"
            }
            if card_count == 0:
                headers["X-Luminary-Warning"] = (
                    "No flashcards found for this collection -- generate some first"
                )
            return Response(
                content=data,
                media_type="application/octet-stream",
                headers=headers,
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# NOTE: These health routes are registered BEFORE /{collection_id}/notes/{note_id} to avoid
# any ambiguity. The /health path segment is not a note_id wildcard.
@router.get("/{collection_id}/health")
async def get_collection_health(
    collection_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Return CollectionHealthReport for the given collection (S173)."""
    try:
        report = await get_collection_health_service().analyze(collection_id, session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dict(report)


@router.post("/{collection_id}/health/archive-stale")
async def archive_stale_notes(
    collection_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Set archived=True for all stale notes in this collection (S173).

    Returns {archived: int}.
    """
    try:
        archived = await get_collection_health_service().archive_stale(collection_id, session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"archived": archived}


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
