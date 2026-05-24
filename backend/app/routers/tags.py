"""CRUD endpoints for canonical tags.

Routes:
  GET    /tags                      -- flat list sorted by usage_count DESC
  GET    /tags/tree                 -- hierarchy with usage_count (includes descendants)
  GET    /tags/autocomplete?q=      -- prefix-search, up to 10 results
  GET    /tags/{tag_id}/notes       -- notes with this tag or any child tag
  POST   /tags                      -- create canonical tag
  PUT    /tags/{tag_id}             -- rename display_name or re-parent
  DELETE /tags/{tag_id}             -- 409 if usage_count > 0
"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db, get_session_factory
from app.models import CanonicalTagModel, NoteModel, NoteTagIndexModel
from app.repos.tag_repo import TagRepo, get_tag_repo
from app.routers.notes import _sync_tag_index
from app.services.naming import normalize_tag_slug
from app.services.repo_helpers import get_or_404
from app.services.tag_graph import build_tag_graph, invalidate_tag_graph_cache
from app.services.tag_merge_service import get_tag_merge_service
from app.services.tag_normalizer import get_tag_normalizer_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tags", tags=["tags"])


class TagResponse(BaseModel):
    id: str
    display_name: str
    parent_tag: str | None
    usage_count: int
    # Count restricted to the requested ?scope. Equal to usage_count for
    # scope='all'; equal to the per-content-type count for scope='note' or
    # 'document'. See redesign-phase-2-plan 2E.1a.
    scoped_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TagTreeItem(BaseModel):
    id: str
    display_name: str
    parent_tag: str | None
    usage_count: int  # inclusive of descendants, from canonical_tags.usage_count
    # Inclusive descendant count restricted to ?scope. Equal to usage_count
    # when scope='all'. Empty subtrees are pruned but ancestors with any
    # matching descendant are preserved. See redesign-phase-2-plan 2E.1b.
    scoped_count: int
    children: list["TagTreeItem"]


TagTreeItem.model_rebuild()


class TagAutocompleteResult(BaseModel):
    id: str
    display_name: str
    parent_tag: str | None
    usage_count: int


class TagCreateRequest(BaseModel):
    id: str  # full slug e.g. 'programming/python'
    display_name: str
    parent_tag: str | None = None


class TagUpdateRequest(BaseModel):
    display_name: str | None = None
    parent_tag: str | None = None


class TagMergeRequest(BaseModel):
    source_tag_id: str
    target_tag_id: str


class TagMergeResponse(BaseModel):
    affected_notes: int
    affected_documents: int = 0


class NoteItem(BaseModel):
    id: str
    content: str
    tags: list[str]

    model_config = {"from_attributes": True}


class TagCrossContentCounts(BaseModel):
    """Per-content-type usage for a single tag (plan 2E.4 spill-over chips)."""

    document_count: int
    note_count: int


class TagNodeItem(BaseModel):
    id: str
    display_name: str
    parent_tag: str | None
    usage_count: int


class TagEdgeItem(BaseModel):
    tag_a: str
    tag_b: str
    weight: int


class TagGraphResponse(BaseModel):
    nodes: list[TagNodeItem]
    edges: list[TagEdgeItem]
    generated_at: float


def _to_response(tag: CanonicalTagModel, scoped_count: int | None = None) -> TagResponse:
    return TagResponse(
        id=tag.id,
        display_name=tag.display_name,
        parent_tag=tag.parent_tag,
        usage_count=tag.usage_count,
        scoped_count=tag.usage_count if scoped_count is None else scoped_count,
        created_at=tag.created_at,
    )


def _compute_inclusive_count(
    tag_id: str,
    count_by_id: dict[str, int],
    children_by_parent: dict[str, list[str]],
) -> int:
    """Recursively sum usage_count for tag + all descendants."""
    direct = count_by_id.get(tag_id, 0)
    child_sum = sum(
        _compute_inclusive_count(child, count_by_id, children_by_parent)
        for child in children_by_parent.get(tag_id, [])
    )
    return direct + child_sum


@router.get("/graph", response_model=TagGraphResponse)
async def get_tag_graph_endpoint(
    session: AsyncSession = Depends(get_db),
) -> TagGraphResponse:
    """Return the tag co-occurrence graph (top-200 nodes, top-500 edges, weight >= 2).

    Result is cached in memory for 60 seconds. Cache is invalidated whenever
    _sync_tag_index writes new tag data (note create/update/delete or merge).

    Static path (/graph) registered before /{tag_id} to avoid route shadowing.
    """

    graph = await build_tag_graph(session)
    return TagGraphResponse(
        nodes=[
            TagNodeItem(
                id=n.id,
                display_name=n.display_name,
                parent_tag=n.parent_tag,
                usage_count=n.usage_count,
            )
            for n in graph.nodes
        ],
        edges=[TagEdgeItem(tag_a=e.tag_a, tag_b=e.tag_b, weight=e.weight) for e in graph.edges],
        generated_at=graph.generated_at,
    )


@router.get("/autocomplete", response_model=list[TagAutocompleteResult])
async def autocomplete_tags(
    q: str = Query(default=""),
    repo: TagRepo = Depends(get_tag_repo),
) -> list[TagAutocompleteResult]:
    """Return up to 10 canonical tags matching the prefix q, sorted by usage_count DESC."""

    normalized_q = normalize_tag_slug(q) if q else ""
    tags = await repo.autocomplete(normalized_q)
    return [
        TagAutocompleteResult(
            id=t.id,
            display_name=t.display_name,
            parent_tag=t.parent_tag,
            usage_count=t.usage_count,
        )
        for t in tags
    ]


@router.get("/tree", response_model=list[TagTreeItem])
async def get_tag_tree(
    scope: str = Query(
        default="all",
        description="'all' | 'note' | 'document' -- restrict scoped_count to that content type.",
    ),
    session: AsyncSession = Depends(get_db),
    repo: TagRepo = Depends(get_tag_repo),
) -> list[TagTreeItem]:
    """Return all canonical tags as a hierarchical tree.

    `usage_count` is the inclusive count (direct + descendants) from
    canonical_tags. `scoped_count` is the inclusive count restricted to the
    requested scope (equal to usage_count when scope='all'). When scoped,
    subtrees with zero matches are pruned but ancestors with any matching
    descendant are preserved.
    """
    if scope not in ("all", "note", "document"):
        raise HTTPException(status_code=422, detail="scope must be 'all', 'note', or 'document'")

    all_tags = list(await repo.list_by_id())

    global_count_by_id: dict[str, int] = {t.id: t.usage_count for t in all_tags}
    if scope == "all":
        scoped_count_by_id: dict[str, int] = dict(global_count_by_id)
    else:
        table = "note_tag_index" if scope == "note" else "document_tag_index"
        member_col = "note_id" if scope == "note" else "document_id"
        rows = (
            await session.execute(
                sa_text(
                    f"SELECT tag_full, COUNT(DISTINCT {member_col}) "
                    f"FROM {table} GROUP BY tag_full"
                )
            )
        ).all()
        scoped_count_by_id = {r[0]: int(r[1]) for r in rows}

    children_by_parent: dict[str, list[str]] = {}
    for t in all_tags:
        if t.parent_tag:
            children_by_parent.setdefault(t.parent_tag, []).append(t.id)

    tag_by_id: dict[str, CanonicalTagModel] = {t.id: t for t in all_tags}

    # Cap rendered depth at 2 (top-level + immediate children) to match the
    # pre-2E.1b contract; inclusive counts still cover the full descendant
    # subtree, so deeper grandchildren contribute to ancestor counts even
    # though they don't render as nodes.
    def build_node(tag_id: str, parent: str | None, depth: int) -> TagTreeItem | None:
        tag = tag_by_id.get(tag_id)
        if tag is None:
            return None
        inclusive_scoped = _compute_inclusive_count(
            tag_id, scoped_count_by_id, children_by_parent
        )
        if scope != "all" and inclusive_scoped == 0:
            return None
        children: list[TagTreeItem] = []
        if depth < 1:
            for child_id in children_by_parent.get(tag_id, []):
                child = build_node(child_id, tag_id, depth + 1)
                if child is not None:
                    children.append(child)
        inclusive_global = _compute_inclusive_count(
            tag_id, global_count_by_id, children_by_parent
        )
        return TagTreeItem(
            id=tag_id,
            display_name=tag.display_name,
            parent_tag=parent,
            usage_count=inclusive_global,
            scoped_count=inclusive_scoped,
            children=children,
        )

    top_level: list[TagTreeItem] = []
    for t in all_tags:
        if t.parent_tag is None:
            node = build_node(t.id, None, 0)
            if node is not None:
                top_level.append(node)

    return top_level


@router.get("", response_model=list[TagResponse])
async def list_tags(
    scope: str = Query(
        default="all",
        description="'all' | 'note' | 'document' -- restrict to tags used by that content type.",
    ),
    limit: int | None = Query(default=None, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    repo: TagRepo = Depends(get_tag_repo),
) -> list[TagResponse]:
    """Return canonical tags sorted by usage_count DESC.

    scope='document' filters to tags that appear in document_tag_index;
    scope='note' to tags in note_tag_index; default 'all' returns the full
    canonical list. `limit` caps the result (no cap by default).
    """
    if scope == "all":
        tags = await repo.list_by_count()
        out = [_to_response(t) for t in tags]
    elif scope in ("note", "document"):
        table = "note_tag_index" if scope == "note" else "document_tag_index"
        member_col = "note_id" if scope == "note" else "document_id"
        # Aggregate the scoped count in the same pass; order by it so a tag
        # mostly used on notes doesn't outrank doc-heavy tags when scope=document.
        rows = (
            await session.execute(
                sa_text(
                    "SELECT t.id, t.display_name, t.parent_tag, t.usage_count, "
                    "t.created_at, "
                    f"(SELECT COUNT(DISTINCT idx.{member_col}) FROM {table} idx "
                    "  WHERE idx.tag_full = t.id) AS scoped_count "
                    "FROM canonical_tags t "
                    f"WHERE EXISTS (SELECT 1 FROM {table} idx2 WHERE idx2.tag_full = t.id) "
                    "ORDER BY scoped_count DESC, t.usage_count DESC"
                )
            )
        ).all()
        out = [
            _to_response(
                CanonicalTagModel(
                    id=r[0],
                    display_name=r[1],
                    parent_tag=r[2],
                    usage_count=r[3],
                    created_at=r[4],
                ),
                scoped_count=r[5],
            )
            for r in rows
        ]
    else:
        raise HTTPException(status_code=422, detail="scope must be 'all', 'note', or 'document'")

    if limit is not None:
        out = out[:limit]
    return out


@router.post("", response_model=TagResponse, status_code=201)
async def create_tag(
    req: TagCreateRequest,
    repo: TagRepo = Depends(get_tag_repo),
) -> TagResponse:
    """Create a canonical tag. Returns 409 if the slug already exists."""

    normalized_id = normalize_tag_slug(req.id)
    if await repo.find_by_id(normalized_id) is not None:
        raise HTTPException(status_code=409, detail="Tag already exists")

    tag = await repo.create(
        id=normalized_id,
        display_name=req.display_name,
        parent_tag=req.parent_tag,
    )
    logger.info("Created canonical tag id=%r", tag.id)
    return _to_response(tag)


@router.post("/merge", response_model=TagMergeResponse)
async def merge_tags(
    req: TagMergeRequest,
    session: AsyncSession = Depends(get_db),
) -> TagMergeResponse:
    """Merge source_tag into target_tag atomically.

    For every note that contains source_tag_id in its tags list:
    - Replace source_tag_id with target_tag_id (deduplicating)
    - Update NoteTagIndexModel via _sync_tag_index

    Then creates a TagAliasModel (source -> target) and deletes the source
    CanonicalTagModel. All changes roll back if any step fails.
    """

    source_id = normalize_tag_slug(req.source_tag_id)
    target_id = normalize_tag_slug(req.target_tag_id)

    if source_id == target_id:
        raise HTTPException(status_code=422, detail="Source and target tags must differ")

    # Validate both tags exist
    await get_or_404(session, CanonicalTagModel, source_id, name=f"Source tag '{source_id}'")
    await get_or_404(session, CanonicalTagModel, target_id, name=f"Target tag '{target_id}'")

    try:
        result = await get_tag_merge_service().merge_tag(
            session, source_id=source_id, target_id=target_id
        )
        logger.info(
            "Successfully merged tag %r -> %r (affected_notes=%d, affected_documents=%d)",
            source_id,
            target_id,
            result.affected_notes,
            result.affected_documents,
        )
    except Exception as exc:
        logger.exception("Merge failed for tag %r -> %r", source_id, target_id)
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Merge failed: {exc}") from exc

    return TagMergeResponse(
        affected_notes=result.affected_notes,
        affected_documents=result.affected_documents,
    )


# Normalization schemas


class TagInfo(BaseModel):
    id: str
    display_name: str
    usage_count: int


class TagMergeSuggestionResponse(BaseModel):
    id: str
    tag_a: TagInfo
    tag_b: TagInfo
    similarity: float
    suggested_canonical_id: str
    status: str
    created_at: datetime


class NormalizationScanResponse(BaseModel):
    queued: bool


class NormalizationAcceptResponse(BaseModel):
    affected_notes: int


# Normalization endpoints — static paths must come before /{tag_id}


@router.post("/normalization/scan", response_model=NormalizationScanResponse)
async def scan_for_normalization(
    session: AsyncSession = Depends(get_db),
) -> NormalizationScanResponse:
    """Trigger an async scan for semantically similar tag pairs.

    The scan runs as a background task with its own DB session (the request
    session closes after the response returns). Returns immediately with
    {queued: true}.
    """

    service = get_tag_normalizer_service()

    async def _run_scan() -> None:
        async with get_session_factory()() as scan_session:
            try:
                count = await service.scan(scan_session)
                logger.info("Background tag normalization scan created %d suggestions", count)
            except Exception:
                logger.exception("Background tag normalization scan failed")

    asyncio.create_task(_run_scan())
    return NormalizationScanResponse(queued=True)


@router.get("/normalization/suggestions", response_model=list[TagMergeSuggestionResponse])
async def get_normalization_suggestions(
    session: AsyncSession = Depends(get_db),
) -> list[TagMergeSuggestionResponse]:
    """Return pending tag merge suggestions with expanded tag info."""

    service = get_tag_normalizer_service()
    details = await service.get_pending_suggestions(session)
    return [
        TagMergeSuggestionResponse(
            id=d.id,
            tag_a=TagInfo(
                id=d.tag_a_id,
                display_name=d.tag_a_display_name,
                usage_count=d.tag_a_usage_count,
            ),
            tag_b=TagInfo(
                id=d.tag_b_id,
                display_name=d.tag_b_display_name,
                usage_count=d.tag_b_usage_count,
            ),
            similarity=d.similarity,
            suggested_canonical_id=d.suggested_canonical_id,
            status=d.status,
            created_at=d.created_at,
        )
        for d in details
    ]


@router.post(
    "/normalization/suggestions/{suggestion_id}/accept",
    response_model=NormalizationAcceptResponse,
)
async def accept_normalization_suggestion(
    suggestion_id: str,
    session: AsyncSession = Depends(get_db),
) -> NormalizationAcceptResponse:
    """Accept a merge suggestion: merge source tag into the suggested canonical.

    Wraps TagMergeService.merge_tag() so the same cascade also runs
    behind `POST /tags/merge`. The endpoint additionally flips the
    suggestion's status (accepted vs rejected if a tag was deleted in
    the meantime) inside the same transaction.
    """

    service = get_tag_normalizer_service()
    try:
        suggestion, source_id, target_id = await service.get_suggestion_for_accept(
            suggestion_id, session
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Validate both tags still exist; these two checks share the session with the
    # suggestion status update below so all three land in one transaction.
    source_tag = (
        await session.execute(select(CanonicalTagModel).where(CanonicalTagModel.id == source_id))
    ).scalar_one_or_none()
    target_tag = (
        await session.execute(select(CanonicalTagModel).where(CanonicalTagModel.id == target_id))
    ).scalar_one_or_none()
    if source_tag is None or target_tag is None:
        # Tag was deleted -- mark suggestion rejected and return
        suggestion.status = "rejected"
        session.add(suggestion)
        await session.commit()
        return NormalizationAcceptResponse(affected_notes=0)

    try:
        # commit=False so the suggestion.status update lands in the same tx.
        result = await get_tag_merge_service().merge_tag(
            session, source_id=source_id, target_id=target_id, commit=False
        )
        suggestion.status = "accepted"
        session.add(suggestion)
        await session.commit()
        session.expire_all()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=500, detail="Merge failed -- rolled back"
        ) from exc

    invalidate_tag_graph_cache()
    logger.info(
        "Accepted tag normalization suggestion %s: %r -> %r, affected_notes=%d",
        suggestion_id,
        source_id,
        target_id,
        result.affected_notes,
    )
    return NormalizationAcceptResponse(affected_notes=result.affected_notes)


@router.post("/normalization/suggestions/{suggestion_id}/reject", status_code=204)
async def reject_normalization_suggestion(
    suggestion_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Reject a merge suggestion."""

    service = get_tag_normalizer_service()
    try:
        await service.reject_suggestion(suggestion_id, session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/migrate-naming")
async def migrate_tag_naming(
    session: AsyncSession = Depends(get_db),
) -> dict:
    """One-time migration: normalize all existing tag slugs.

    For canonical_tags: normalizes id and display_name.
    For note_tag_index: normalizes tag_full, tag_root, tag_parent.
    For NoteModel.tags: normalizes the JSON tags array on each note.
    Merges duplicates that collapse to the same normalized form (keeps higher usage_count).
    """

    # Bespoke multi-table normalization migration: rename/merge canonical_tags,
    # note_tag_index, and NoteModel.tags atomically. Too many conditional writes
    # (INSERT OR IGNORE, cascading deletes, JSON tag array updates) to express
    # via existing repo methods.
    all_tags_result = await session.execute(select(CanonicalTagModel))
    all_tags = list(all_tags_result.scalars().all())

    # Group by normalized id to detect merges
    groups: dict[str, list[CanonicalTagModel]] = {}
    for tag in all_tags:
        normalized = normalize_tag_slug(tag.id)
        if not normalized:
            continue
        groups.setdefault(normalized, []).append(tag)

    merged_count = 0
    renamed_count = 0

    for normalized_id, tag_group in groups.items():
        if len(tag_group) == 1:
            tag = tag_group[0]
            if tag.id != normalized_id:
                # Rename: update canonical_tags id, note_tag_index, and NoteModel.tags
                old_id = tag.id
                # Update all notes with this tag
                note_ids_result = await session.execute(
                    select(NoteTagIndexModel.note_id)
                    .where(NoteTagIndexModel.tag_full == old_id)
                    .distinct()
                )
                note_ids = [row[0] for row in note_ids_result.all()]

                # Delete old index rows
                await session.execute(
                    delete(NoteTagIndexModel).where(NoteTagIndexModel.tag_full == old_id)
                )
                # Delete old canonical tag
                await session.execute(
                    delete(CanonicalTagModel).where(CanonicalTagModel.id == old_id)
                )
                # Recreate canonical tag with normalized id
                segments = normalized_id.split("/")
                new_display = segments[-1]
                new_parent = "/".join(segments[:-1]) if len(segments) > 1 else None

                await session.execute(
                    sa_text(
                        "INSERT OR IGNORE INTO canonical_tags"
                        " (id, display_name, parent_tag, usage_count, created_at)"
                        " VALUES (:id, :display_name, :parent_tag, :usage_count, datetime('now'))"
                    ),
                    {
                        "id": normalized_id,
                        "display_name": new_display,
                        "parent_tag": new_parent,
                        "usage_count": tag.usage_count,
                    },
                )

                # Update NoteModel.tags and re-sync index
                if note_ids:
                    notes_result = await session.execute(
                        select(NoteModel).where(NoteModel.id.in_(note_ids))
                    )
                    for note in notes_result.scalars().all():
                        current_tags: list[str] = note.tags or []
                        new_tags = [normalize_tag_slug(t) for t in current_tags]
                        # Deduplicate preserving order
                        seen: set[str] = set()
                        deduped: list[str] = []
                        for t in new_tags:
                            if t and t not in seen:
                                seen.add(t)
                                deduped.append(t)
                        note.tags = deduped

                        flag_modified(note, "tags")
                        session.add(note)
                        await _sync_tag_index(note.id, deduped, session)

                renamed_count += 1
        else:
            # Multiple tags collapse to same normalized form -- merge
            # Sort by usage_count desc so merged count reflects the best variant
            tag_group.sort(key=lambda t: t.usage_count, reverse=True)

            # Collect all note_ids from all variants
            all_note_ids: set[str] = set()
            for tag in tag_group:
                note_ids_result = await session.execute(
                    select(NoteTagIndexModel.note_id)
                    .where(NoteTagIndexModel.tag_full == tag.id)
                    .distinct()
                )
                for row in note_ids_result.all():
                    all_note_ids.add(row[0])

            # Delete all old index rows and canonical tags for all variants
            for tag in tag_group:
                await session.execute(
                    delete(NoteTagIndexModel).where(NoteTagIndexModel.tag_full == tag.id)
                )
                await session.execute(
                    delete(CanonicalTagModel).where(CanonicalTagModel.id == tag.id)
                )

            # Create the normalized canonical tag
            segments = normalized_id.split("/")
            new_display = segments[-1]
            new_parent = "/".join(segments[:-1]) if len(segments) > 1 else None

            await session.execute(
                sa_text(
                    "INSERT OR IGNORE INTO canonical_tags"
                    " (id, display_name, parent_tag, usage_count, created_at)"
                    " VALUES (:id, :display_name, :parent_tag, :usage_count, datetime('now'))"
                ),
                {
                    "id": normalized_id,
                    "display_name": new_display,
                    "parent_tag": new_parent,
                    "usage_count": len(all_note_ids),
                },
            )

            # Update all notes to use normalized tag
            if all_note_ids:
                notes_result = await session.execute(
                    select(NoteModel).where(NoteModel.id.in_(list(all_note_ids)))
                )
                for note in notes_result.scalars().all():
                    current_tags: list[str] = note.tags or []
                    new_tags_list: list[str] = []
                    seen_tags: set[str] = set()
                    for t in current_tags:
                        nt = normalize_tag_slug(t)
                        if nt and nt not in seen_tags:
                            seen_tags.add(nt)
                            new_tags_list.append(nt)
                    note.tags = new_tags_list

                    flag_modified(note, "tags")
                    session.add(note)
                    await _sync_tag_index(note.id, new_tags_list, session)

            merged_count += 1

    await session.commit()
    invalidate_tag_graph_cache()
    logger.info(
        "Tag naming migration complete: renamed=%d merged=%d",
        renamed_count,
        merged_count,
    )
    return {"renamed": renamed_count, "merged": merged_count}


@router.get("/{tag_id}/notes", response_model=list[NoteItem])
async def get_notes_for_tag(
    tag_id: str,
    repo: TagRepo = Depends(get_tag_repo),
) -> list[NoteItem]:
    """Return notes tagged with tag_id or any child tag (prefix match)."""
    note_ids = await repo.note_ids_with_tag(tag_id, include_descendants=True)
    if not note_ids:
        return []
    notes = await repo.load_notes(note_ids)
    return [NoteItem(id=n.id, content=n.content, tags=n.tags or []) for n in notes]


@router.get("/{tag_id}/cross-content-counts", response_model=TagCrossContentCounts)
async def get_tag_cross_content_counts(
    tag_id: str,
    session: AsyncSession = Depends(get_db),
) -> TagCrossContentCounts:
    """Per-content-type usage for a single tag.

    Drives the Library/Notes spill-over chip ("Also in N notes →") when a
    user has narrowed one surface and we want to surface the cross-content
    overflow without making them hop back to ⌘K (plan 2E.4).
    """
    row = (
        await session.execute(
            sa_text(
                "SELECT "
                "  (SELECT COUNT(DISTINCT document_id) FROM document_tag_index "
                "   WHERE tag_full = :tag) AS doc_count, "
                "  (SELECT COUNT(DISTINCT note_id) FROM note_tag_index "
                "   WHERE tag_full = :tag) AS note_count"
            ),
            {"tag": tag_id},
        )
    ).first()
    return TagCrossContentCounts(
        document_count=int(row[0] or 0) if row else 0,
        note_count=int(row[1] or 0) if row else 0,
    )


@router.put("/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: str,
    req: TagUpdateRequest,
    repo: TagRepo = Depends(get_tag_repo),
) -> TagResponse:
    """Rename a tag's display_name or re-parent it."""
    tag = await repo.get_or_404(tag_id)
    # Use model_fields_set to distinguish "not supplied" from "explicitly null".
    # Setting parent_tag=null in the request clears the tag to top-level.
    tag = await repo.update_fields(
        tag,
        display_name=req.display_name,
        parent_tag=req.parent_tag,
        parent_tag_set="parent_tag" in req.model_fields_set,
    )
    logger.info("Updated canonical tag id=%r", tag_id)
    return _to_response(tag)


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: str,
    repo: TagRepo = Depends(get_tag_repo),
) -> None:
    """Delete a canonical tag. Returns 409 if the tag has notes (usage_count > 0)."""
    tag = await repo.get_or_404(tag_id)
    if tag.usage_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Tag '{tag_id}' has {tag.usage_count} notes."
                " Remove notes from this tag before deleting."
            ),
        )
    await repo.delete_with_aliases(tag_id)
    logger.info("Deleted canonical tag id=%r", tag_id)
