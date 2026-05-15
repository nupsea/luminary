"""Collection management endpoints.

Routes:
  POST   /collections               -- create a collection
  GET    /collections/tree          -- return full tree (2 levels)
  GET    /collections/{id}          -- get single collection
  PUT    /collections/{id}          -- rename / update a collection
  DELETE /collections/{id}          -- delete collection (members removed, items preserved)
  POST   /collections/{id}/members  -- add items (notes or docs) to collection (idempotent)
  DELETE /collections/{id}/members/{id} -- remove an item from collection
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
from app.models import CollectionMemberModel, CollectionModel, DocumentModel
from app.repos.collection_repo import CollectionRepo, get_collection_repo
from app.services.collection_health import get_collection_health_service
from app.services.export_service import get_export_service
from app.services.naming import normalize_collection_name
from app.services.repo_helpers import get_or_404

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
    document_count: int
    children: list["CollectionTreeItem"]


CollectionTreeItem.model_rebuild()


class AddMembersRequest(BaseModel):
    member_ids: list[str] | None = None
    note_ids: list[str] | None = None  # Backward compatibility
    member_type: str = "note"  # note | document

    @property
    def effective_member_ids(self) -> list[str]:
        if self.member_ids is not None:
            return self.member_ids
        if self.note_ids is not None:
            return self.note_ids
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(col: CollectionModel) -> CollectionResponse:
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
    "book": "#8B5CF6",  # violet
    "paper": "#3B82F6",  # blue
    "conversation": "#F59E0B",  # amber
    "notes": "#10B981",  # emerald
    "code": "#6366F1",  # indigo
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
        return normalize_collection_name(f"{short}_{suffix}")

    # For longer titles, extract key words (capitalized, acronyms, proper nouns)
    # Remove common filler words
    filler = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "in",
        "on",
        "for",
        "to",
        "with",
        "by",
        "is",
        "at",
        "from",
        "as",
        "into",
        "its",
        "this",
        "that",
        "how",
        "era",
        "about",
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

    return normalize_collection_name(f"{short}_{suffix}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=CollectionResponse, status_code=201)
async def create_collection(
    req: CollectionCreateRequest,
    repo: CollectionRepo = Depends(get_collection_repo),
) -> CollectionResponse:
    """Create a new collection. Parent must be a top-level collection (max 2-level nesting)."""
    if req.parent_collection_id is not None:
        parent = await get_or_404(
            repo.session, CollectionModel, req.parent_collection_id, name="Parent collection"
        )
        if parent.parent_collection_id is not None:
            raise HTTPException(
                status_code=422,
                detail="Max nesting depth is 2. The parent already has a parent.",
            )

    col = await repo.create(
        name=normalize_collection_name(req.name),
        description=req.description,
        color=req.color,
        icon=req.icon,
        parent_collection_id=req.parent_collection_id,
        sort_order=req.sort_order,
    )
    logger.info("Created collection id=%s name=%r", col.id, col.name)
    return _to_response(col)


@router.get("/tree", response_model=list[CollectionTreeItem])
async def get_collection_tree(
    repo: CollectionRepo = Depends(get_collection_repo),
) -> list[CollectionTreeItem]:
    """Return all collections as a 2-level nested tree with item counts."""
    all_cols = list(await repo.list_all())
    counts = await repo.member_counts()
    note_counts: dict[str, int] = {
        cid: c for (cid, mtype), c in counts.items() if mtype == "note"
    }
    doc_counts: dict[str, int] = {
        cid: c for (cid, mtype), c in counts.items() if mtype == "document"
    }

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
                    document_count=doc_counts.get(child.id, 0),
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
                    document_count=doc_counts.get(col.id, 0),
                    children=children,
                )
            )

    return top_level


# NOTE: /by-document and /auto routes MUST be registered BEFORE /{collection_id}
# to prevent FastAPI from matching "by-document" or "auto" as a collection_id wildcard.


@router.get("/by-document/{document_id}", response_model=CollectionResponse)
async def get_auto_collection_by_document(
    document_id: str,
    repo: CollectionRepo = Depends(get_collection_repo),
) -> CollectionResponse:
    """Return the auto-collection for a document, or 404 if none exists."""
    col = await repo.find_by_auto_document_id(document_id)
    if col is None:
        raise HTTPException(status_code=404, detail="No auto-collection for this document")
    return _to_response(col)


@router.post("/auto/{document_id}", response_model=CollectionResponse, status_code=201)
async def create_auto_collection(
    document_id: str,
    repo: CollectionRepo = Depends(get_collection_repo),
) -> CollectionResponse:
    """Create auto-collection for a document. Idempotent -- returns existing."""
    existing = await repo.find_by_auto_document_id(document_id)
    if existing is not None:
        return _to_response(existing)

    doc = await get_or_404(repo.session, DocumentModel, document_id, name="Document")
    color = _AUTO_COLLECTION_COLORS.get(doc.content_type, "#6366F1")
    col_name = _make_collection_name(doc.title, doc.content_type)
    col = await repo.create(name=col_name, color=color, auto_document_id=document_id)
    logger.info("Created auto-collection id=%s for document=%s", col.id, document_id)
    return _to_response(col)


@router.post("/migrate-naming")
async def migrate_collection_naming(
    session: AsyncSession = Depends(get_db),
) -> dict:
    """One-time migration: normalize all existing collection names.

    Merges duplicates that collapse to the same normalized form
    (keeps the collection with more members, reassigns members from the other).
    """
    # Bespoke multi-table merge: reads all collections, groups by normalized name,
    # then reassigns members and deletes duplicates atomically. Too many conditional
    # writes (INSERT OR IGNORE, cascading deletes) to express via CollectionRepo.
    all_cols_result = await session.execute(select(CollectionModel))
    all_cols = list(all_cols_result.scalars().all())

    # Group by normalized name
    groups: dict[str, list[CollectionModel]] = {}
    for col in all_cols:
        normalized = normalize_collection_name(col.name)
        if not normalized:
            continue
        groups.setdefault(normalized, []).append(col)

    renamed_count = 0
    merged_count = 0

    for normalized_name, col_group in groups.items():
        if len(col_group) == 1:
            col = col_group[0]
            if col.name != normalized_name:
                col.name = normalized_name
                col.updated_at = datetime.now(UTC)
                session.add(col)
                renamed_count += 1
        else:
            # Multiple collections collapse to same name -- merge
            # Count members for each to find keeper
            member_counts: list[tuple[CollectionModel, int]] = []
            for col in col_group:
                count_result = await session.execute(
                    select(func.count(CollectionMemberModel.member_id)).where(
                        CollectionMemberModel.collection_id == col.id
                    )
                )
                count = count_result.scalar() or 0
                member_counts.append((col, count))

            # Sort by member count desc -- keeper is first
            member_counts.sort(key=lambda x: x[1], reverse=True)
            keeper = member_counts[0][0]
            keeper.name = normalized_name
            keeper.updated_at = datetime.now(UTC)
            session.add(keeper)

            # Move members from losers to keeper, then delete losers
            for loser, _ in member_counts[1:]:
                # Get all members from loser
                loser_members_result = await session.execute(
                    select(
                        CollectionMemberModel.member_id,
                        CollectionMemberModel.member_type,
                    ).where(CollectionMemberModel.collection_id == loser.id)
                )
                loser_members = loser_members_result.all()

                # Reassign to keeper (idempotent via INSERT OR IGNORE)
                for member_id, member_type in loser_members:
                    await session.execute(
                        text(
                            "INSERT OR IGNORE INTO collection_members"
                            " (id, member_id, collection_id, member_type, added_at)"
                            " VALUES (:id, :member_id, :collection_id, :member_type, :added_at)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "member_id": member_id,
                            "collection_id": keeper.id,
                            "member_type": member_type,
                            "added_at": datetime.now(UTC).isoformat(),
                        },
                    )

                # Delete loser's members and the loser itself
                await session.execute(
                    delete(CollectionMemberModel).where(
                        CollectionMemberModel.collection_id == loser.id
                    )
                )
                # Also delete child collections of loser
                await session.execute(
                    delete(CollectionModel).where(CollectionModel.parent_collection_id == loser.id)
                )
                await session.execute(delete(CollectionModel).where(CollectionModel.id == loser.id))

            merged_count += 1

    await session.commit()
    logger.info(
        "Collection naming migration complete: renamed=%d merged=%d",
        renamed_count,
        merged_count,
    )
    return {"renamed": renamed_count, "merged": merged_count}


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: str,
    repo: CollectionRepo = Depends(get_collection_repo),
) -> CollectionResponse:
    col = await repo.get_or_404(collection_id)
    return _to_response(col)


@router.put("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: str,
    req: CollectionUpdateRequest,
    repo: CollectionRepo = Depends(get_collection_repo),
) -> CollectionResponse:
    col = await repo.get_or_404(collection_id)
    col = await repo.update_fields(
        col,
        name=normalize_collection_name(req.name) if req.name is not None else None,
        description=req.description,
        color=req.color,
        icon=req.icon,
        sort_order=req.sort_order,
    )
    logger.info("Updated collection id=%s", collection_id)
    return _to_response(col)


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: str,
    repo: CollectionRepo = Depends(get_collection_repo),
) -> None:
    """Delete a collection. Member rows are removed; items themselves are NOT deleted."""
    await repo.get_or_404(collection_id)
    await repo.delete_with_children(collection_id)
    logger.info("Deleted collection id=%s", collection_id)


@router.post("/{collection_id}/notes", status_code=201)
@router.post("/{collection_id}/members", status_code=201)
async def add_members_to_collection(
    collection_id: str,
    req: AddMembersRequest,
    repo: CollectionRepo = Depends(get_collection_repo),
) -> dict:
    """Add members (notes or documents) to a collection. Idempotent."""
    await repo.get_or_404(collection_id)

    member_ids = req.effective_member_ids
    if not member_ids:
        raise HTTPException(status_code=422, detail="member_ids or note_ids required")

    added = await repo.add_members(collection_id, member_ids, member_type=req.member_type)
    logger.info("Added %d %ss to collection id=%s", added, req.member_type, collection_id)
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
            # Fetch collection name for filename slug; not covered by export service return value.
            col = (
                await session.execute(
                    select(CollectionModel).where(CollectionModel.id == collection_id)
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
            # Fetch collection name for filename slug; not covered by export service return value.
            col = (
                await session.execute(
                    select(CollectionModel).where(CollectionModel.id == collection_id)
                )
            ).scalar_one_or_none()
            slug = col.name.lower().replace(" ", "-") if col else collection_id[:8]
            slug = re.sub(r"[^\w-]", "", slug)[:40] or "deck"
            filename = f"{slug}.apkg"
            headers: dict[str, str] = {"Content-Disposition": f"attachment; filename={filename}"}
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
    """Return CollectionHealthReport for the given collection"""
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
    """Set archived=True for all stale notes in this collection

    Returns {archived: int}.
    """
    try:
        archived = await get_collection_health_service().archive_stale(collection_id, session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"archived": archived}


@router.delete("/{collection_id}/members/{member_id}", status_code=204)
async def remove_member_from_collection(
    collection_id: str,
    member_id: str,
    repo: CollectionRepo = Depends(get_collection_repo),
) -> None:
    """Remove a member (note or document) from a collection."""
    await repo.remove_member(collection_id, member_id)
