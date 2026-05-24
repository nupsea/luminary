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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CollectionMemberModel, CollectionModel, DocumentModel
from app.repos.collection_repo import CollectionRepo, get_collection_repo
from app.schemas.home import (
    CollectionOverviewResponse,
    CollectionTagChip,
    RecentItem,
)
from app.services.collection_health import get_collection_health_service
from app.services.export_service import get_export_service
from app.services.naming import normalize_collection_name
from app.services.repo_helpers import get_or_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collections", tags=["collections"])


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
    # Inclusive count (direct + descendants) restricted to the requested
    # ?contains member_type. Equals note_count+document_count for the node
    # itself when unscoped (?contains absent). See plan 2E.1c.
    scoped_count: int
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
    contains: str | None = Query(
        default=None,
        description="'document' | 'note' -- restrict scoped_count to that member type "
        "and prune subtrees with zero matches (ancestors with matching descendants are kept).",
    ),
    repo: CollectionRepo = Depends(get_collection_repo),
) -> list[CollectionTreeItem]:
    """Return all collections as a 2-level nested tree with item counts.

    scoped_count semantics:
      - unscoped: equals direct note_count + document_count for each node
      - ?contains=document: equals inclusive descendant document count
      - ?contains=note:     equals inclusive descendant note count
    """
    if contains is not None and contains not in ("document", "note"):
        raise HTTPException(
            status_code=422, detail="contains must be 'document' or 'note'"
        )

    all_cols = list(await repo.list_all())
    counts = await repo.member_counts()
    note_counts: dict[str, int] = {
        cid: c for (cid, mtype), c in counts.items() if mtype == "note"
    }
    doc_counts: dict[str, int] = {
        cid: c for (cid, mtype), c in counts.items() if mtype == "document"
    }

    children_by_parent: dict[str, list[str]] = {}
    for col in all_cols:
        if col.parent_collection_id is not None:
            children_by_parent.setdefault(col.parent_collection_id, []).append(col.id)

    def direct_scoped(cid: str) -> int:
        if contains == "document":
            return doc_counts.get(cid, 0)
        if contains == "note":
            return note_counts.get(cid, 0)
        return note_counts.get(cid, 0) + doc_counts.get(cid, 0)

    def direct_total(cid: str) -> int:
        return note_counts.get(cid, 0) + doc_counts.get(cid, 0)

    def inclusive_scoped(cid: str) -> int:
        total = direct_scoped(cid)
        for child_id in children_by_parent.get(cid, []):
            total += inclusive_scoped(child_id)
        return total

    def inclusive_total(cid: str) -> int:
        total = direct_total(cid)
        for child_id in children_by_parent.get(cid, []):
            total += inclusive_total(child_id)
        return total

    col_by_id: dict[str, CollectionModel] = {c.id: c for c in all_cols}

    # Cap rendered depth at 2 (top + immediate children) to match the
    # pre-2E.1c contract. Inclusive counts still cover the full subtree.
    def build_node(cid: str, depth: int) -> CollectionTreeItem | None:
        col = col_by_id.get(cid)
        if col is None:
            return None
        scoped = inclusive_scoped(cid)
        # Empty collections (no members of any type) must survive every scope
        # filter -- otherwise a brand-new collection vanishes from the rail
        # that created it before any members are added.
        if contains is not None and scoped == 0 and inclusive_total(cid) > 0:
            return None
        children: list[CollectionTreeItem] = []
        if depth < 1:
            for child_id in children_by_parent.get(cid, []):
                node = build_node(child_id, depth + 1)
                if node is not None:
                    children.append(node)
        return CollectionTreeItem(
            id=col.id,
            name=col.name,
            color=col.color,
            icon=col.icon,
            note_count=note_counts.get(col.id, 0),
            document_count=doc_counts.get(col.id, 0),
            scoped_count=scoped,
            children=children,
        )

    top_level: list[CollectionTreeItem] = []
    for col in all_cols:
        if col.parent_collection_id is None:
            node = build_node(col.id, 0)
            if node is not None:
                top_level.append(node)

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


@router.get("/{collection_id}/overview", response_model=CollectionOverviewResponse)
async def get_collection_overview(
    collection_id: str,
    recent_limit: int = Query(default=8, ge=1, le=50),
    tag_limit: int = Query(default=8, ge=1, le=20),
    session: AsyncSession = Depends(get_db),
    repo: CollectionRepo = Depends(get_collection_repo),
) -> CollectionOverviewResponse:
    """Overview tab on /collections/:id (plan 2E.6).

    Recent activity is the same interleaving as /home/overview but joined
    against this collection's members. Tag chips reflect the union of
    tags applied to those members, sorted by how often they appear within
    the collection.
    """
    await repo.get_or_404(collection_id)

    recent_rows = (
        await session.execute(
            text(
                """
                SELECT 'document' AS member_type, ca.member_id, d.title AS title,
                       NULL AS preview, ca.last_meaningful_at
                FROM collection_members cm
                JOIN content_activity ca
                  ON ca.member_id = cm.member_id AND ca.member_type = cm.member_type
                JOIN documents d ON d.id = cm.member_id
                WHERE cm.collection_id = :cid AND cm.member_type = 'document'
                UNION ALL
                SELECT 'note' AS member_type, ca.member_id,
                       COALESCE(NULLIF(n.title, ''), substr(n.content, 1, 60)) AS title,
                       substr(n.content, 1, 120) AS preview,
                       ca.last_meaningful_at
                FROM collection_members cm
                JOIN content_activity ca
                  ON ca.member_id = cm.member_id AND ca.member_type = cm.member_type
                JOIN notes n ON n.id = cm.member_id
                WHERE cm.collection_id = :cid AND cm.member_type = 'note' AND n.archived = 0
                ORDER BY last_meaningful_at DESC
                LIMIT :recent_limit
                """
            ),
            {"cid": collection_id, "recent_limit": recent_limit},
        )
    ).all()
    recent_items = [
        RecentItem(
            member_type=row[0],
            member_id=row[1],
            title=row[2] or "(untitled)",
            preview=row[3],
            last_meaningful_at=row[4],
        )
        for row in recent_rows
    ]

    # Tag chips: union of doc + note tags from this collection's members,
    # counted by how many *members* carry them (so a tag on 2 docs + 1 note
    # ranks as 3, regardless of how many index rows exist).
    tag_rows = (
        await session.execute(
            text(
                """
                SELECT t.id, t.display_name, COUNT(*) AS hit_count
                FROM (
                    SELECT dti.tag_full AS tag_id
                    FROM collection_members cm
                    JOIN document_tag_index dti ON dti.document_id = cm.member_id
                    WHERE cm.collection_id = :cid AND cm.member_type = 'document'
                    UNION ALL
                    SELECT nti.tag_full AS tag_id
                    FROM collection_members cm
                    JOIN note_tag_index nti ON nti.note_id = cm.member_id
                    WHERE cm.collection_id = :cid AND cm.member_type = 'note'
                ) AS hits
                JOIN canonical_tags t ON t.id = hits.tag_id
                GROUP BY t.id, t.display_name
                ORDER BY hit_count DESC, t.id
                LIMIT :tag_limit
                """
            ),
            {"cid": collection_id, "tag_limit": tag_limit},
        )
    ).all()
    tags = [
        CollectionTagChip(id=r[0], display_name=r[1], count=int(r[2]))
        for r in tag_rows
    ]

    # Member counts for the mini-stat row at the top of the tab.
    count_rows = (
        await session.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM collection_members
                    WHERE collection_id = :cid AND member_type = 'document') AS doc_count,
                  (SELECT COUNT(*) FROM collection_members
                    WHERE collection_id = :cid AND member_type = 'note') AS note_count,
                  (SELECT COUNT(DISTINCT fc.id) FROM collection_members cm
                    JOIN flashcards fc ON (
                      (cm.member_type = 'document' AND fc.document_id = cm.member_id)
                      OR (cm.member_type = 'note' AND fc.note_id = cm.member_id)
                    )
                    WHERE cm.collection_id = :cid) AS fc_count
                """
            ),
            {"cid": collection_id},
        )
    ).first()
    doc_count = int(count_rows[0] or 0) if count_rows else 0
    note_count = int(count_rows[1] or 0) if count_rows else 0
    fc_count = int(count_rows[2] or 0) if count_rows else 0

    return CollectionOverviewResponse(
        recent_items=recent_items,
        tags=tags,
        document_count=doc_count,
        note_count=note_count,
        flashcard_count=fc_count,
    )


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
    member_type: str | None = Query(
        default=None,
        description="When set ('note' or 'document'), scope the delete to that member type.",
    ),
    repo: CollectionRepo = Depends(get_collection_repo),
) -> None:
    """Remove a member (note or document) from a collection."""
    await repo.remove_member(collection_id, member_id, member_type=member_type)
