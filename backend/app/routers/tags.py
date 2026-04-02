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

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_session_factory
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
    parent_tag: str | None
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


class TagMergeRequest(BaseModel):
    source_tag_id: str
    target_tag_id: str


class TagMergeResponse(BaseModel):
    affected_notes: int


class NoteItem(BaseModel):
    id: str
    content: str
    tags: list[str]

    model_config = {"from_attributes": True}


class TagNodeItem(BaseModel):
    id: str
    display_name: str
    parent_tag: str | None
    note_count: int


class TagEdgeItem(BaseModel):
    tag_a: str
    tag_b: str
    weight: int


class TagGraphResponse(BaseModel):
    nodes: list[TagNodeItem]
    edges: list[TagEdgeItem]
    generated_at: float


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


@router.get("/graph", response_model=TagGraphResponse)
async def get_tag_graph_endpoint(
    session: AsyncSession = Depends(get_db),
) -> TagGraphResponse:
    """Return the tag co-occurrence graph (top-200 nodes, top-500 edges, weight >= 2).

    Result is cached in memory for 60 seconds. Cache is invalidated whenever
    _sync_tag_index writes new tag data (note create/update/delete or merge).

    Static path (/graph) registered before /{tag_id} to avoid route shadowing.
    """
    from app.services.tag_graph import build_tag_graph  # noqa: PLC0415

    graph = await build_tag_graph(session)
    return TagGraphResponse(
        nodes=[
            TagNodeItem(
                id=n.id,
                display_name=n.display_name,
                parent_tag=n.parent_tag,
                note_count=n.note_count,
            )
            for n in graph.nodes
        ],
        edges=[
            TagEdgeItem(tag_a=e.tag_a, tag_b=e.tag_b, weight=e.weight)
            for e in graph.edges
        ],
        generated_at=graph.generated_at,
    )


@router.get("/autocomplete", response_model=list[TagAutocompleteResult])
async def autocomplete_tags(
    q: str = Query(default=""),
    session: AsyncSession = Depends(get_db),
) -> list[TagAutocompleteResult]:
    """Return up to 10 canonical tags matching the prefix q, sorted by note_count DESC."""
    from app.services.naming import normalize_tag_slug  # noqa: PLC0415

    normalized_q = normalize_tag_slug(q) if q else ""
    result = await session.execute(
        select(CanonicalTagModel)
        .where(CanonicalTagModel.id.like(f"{normalized_q}%"))
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

    # Build lookup for display_name and parent_tag by id
    tag_by_id: dict[str, CanonicalTagModel] = {t.id: t for t in all_tags}

    # Build tree: top-level nodes only (no parent_tag)
    top_level: list[TagTreeItem] = []
    for t in all_tags:
        if t.parent_tag is None:
            children = [
                TagTreeItem(
                    id=child_id,
                    display_name=(
                        tag_by_id[child_id].display_name if child_id in tag_by_id else child_id
                    ),
                    parent_tag=t.id,
                    note_count=_compute_inclusive_count(child_id, count_by_id, children_by_parent),
                    children=[],  # max 2 levels supported in query; deeper children truncated
                )
                for child_id in children_by_parent.get(t.id, [])
            ]
            top_level.append(
                TagTreeItem(
                    id=t.id,
                    display_name=t.display_name,
                    parent_tag=None,
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
    from app.services.naming import normalize_tag_slug  # noqa: PLC0415

    normalized_id = normalize_tag_slug(req.id)
    existing = (
        await session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id == normalized_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Tag already exists")

    tag = CanonicalTagModel(
        id=normalized_id,
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
    from app.routers.notes import _sync_tag_index  # noqa: PLC0415

    source_id = req.source_tag_id
    target_id = req.target_tag_id

    if source_id == target_id:
        raise HTTPException(status_code=422, detail="Source and target tags must differ")

    # Validate both tags exist
    source_tag = (
        await session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id == source_id)
        )
    ).scalar_one_or_none()
    if source_tag is None:
        raise HTTPException(status_code=404, detail=f"Source tag '{source_id}' not found")

    target_tag = (
        await session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id == target_id)
        )
    ).scalar_one_or_none()
    if target_tag is None:
        raise HTTPException(status_code=404, detail=f"Target tag '{target_id}' not found")

    # Find all notes with the source tag via NoteTagIndexModel
    note_ids_result = await session.execute(
        select(NoteTagIndexModel.note_id)
        .where(NoteTagIndexModel.tag_full == source_id)
        .distinct()
    )
    note_ids = [row[0] for row in note_ids_result.all()]

    try:
        if note_ids:
            # Ensure we are not using stale objects
            session.expire_all()
            # Load notes
            notes_result = await session.execute(
                select(NoteModel).where(NoteModel.id.in_(note_ids))
            )
            notes = list(notes_result.scalars().all())
            logger.info(
                "Merging tag %r -> %r in %d notes: %r",
                source_id, target_id, len(notes), note_ids
            )

            for note in notes:
                current_tags: list[str] = note.tags or []
                # Replace source with target, deduplicate, preserve order
                new_tags: list[str] = []
                seen: set[str] = set()
                for tag in current_tags:
                    replacement = target_id if tag == source_id else tag
                    if replacement not in seen:
                        seen.add(replacement)
                        new_tags.append(replacement)

                if new_tags != current_tags:
                    logger.debug("Updating note %s tags: %r -> %r", note.id, current_tags, new_tags)
                    note.tags = list(new_tags)
                    from sqlalchemy.orm.attributes import flag_modified  # noqa: PLC0415
                    flag_modified(note, "tags")
                    session.add(note)
                    await session.flush()
                
                # Always sync index even if tags didn't change (idempotent)
                await _sync_tag_index(note.id, new_tags, session)

        # Create alias: source -> target
        alias = TagAliasModel(alias=source_id, canonical_tag_id=target_id)
        session.add(alias)

        # Delete source canonical tag
        await session.execute(
            delete(CanonicalTagModel).where(CanonicalTagModel.id == source_id)
        )

        await session.commit()
        session.expire_all()
        logger.info("Successfully merged tag %r -> %r", source_id, target_id)
    except Exception as exc:
        logger.exception("Merge failed for tag %r -> %r", source_id, target_id)
        await session.rollback()
        raise HTTPException(
            status_code=500, detail=f"Merge failed: {exc}"
        )

    return TagMergeResponse(affected_notes=len(note_ids))


# ---------------------------------------------------------------------------
# Normalization schemas
# ---------------------------------------------------------------------------


class TagInfo(BaseModel):
    id: str
    display_name: str
    note_count: int


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


# ---------------------------------------------------------------------------
# Normalization endpoints (static paths -- must come before /{tag_id})
# ---------------------------------------------------------------------------


@router.post("/normalization/scan", response_model=NormalizationScanResponse)
async def scan_for_normalization(
    session: AsyncSession = Depends(get_db),
) -> NormalizationScanResponse:
    """Trigger an async scan for semantically similar tag pairs.

    The scan runs as a background task with its own DB session (the request
    session closes after the response returns). Returns immediately with
    {queued: true}.
    """
    from app.services.tag_normalizer import get_tag_normalizer_service  # noqa: PLC0415

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


@router.get(
    "/normalization/suggestions", response_model=list[TagMergeSuggestionResponse]
)
async def get_normalization_suggestions(
    session: AsyncSession = Depends(get_db),
) -> list[TagMergeSuggestionResponse]:
    """Return pending tag merge suggestions with expanded tag info."""
    from app.services.tag_normalizer import get_tag_normalizer_service  # noqa: PLC0415

    service = get_tag_normalizer_service()
    details = await service.get_pending_suggestions(session)
    return [
        TagMergeSuggestionResponse(
            id=d.id,
            tag_a=TagInfo(
                id=d.tag_a_id,
                display_name=d.tag_a_display_name,
                note_count=d.tag_a_note_count,
            ),
            tag_b=TagInfo(
                id=d.tag_b_id,
                display_name=d.tag_b_display_name,
                note_count=d.tag_b_note_count,
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

    Merge logic lives here (not in the service layer) because _sync_tag_index is
    a router-layer helper and Services must not import from the API/Router layer
    (six-layer invariant).
    """
    from app.routers.notes import _sync_tag_index  # noqa: PLC0415
    from app.services.tag_graph import invalidate_tag_graph_cache  # noqa: PLC0415
    from app.services.tag_normalizer import get_tag_normalizer_service  # noqa: PLC0415

    service = get_tag_normalizer_service()
    try:
        suggestion, source_id, target_id = await service.get_suggestion_for_accept(
            suggestion_id, session
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Validate both tags still exist
    source_tag = (
        await session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id == source_id)
        )
    ).scalar_one_or_none()
    target_tag = (
        await session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id == target_id)
        )
    ).scalar_one_or_none()
    if source_tag is None or target_tag is None:
        # Tag was deleted -- mark suggestion rejected and return
        suggestion.status = "rejected"
        session.add(suggestion)
        await session.commit()
        return NormalizationAcceptResponse(affected_notes=0)

    # Find and update notes with the source tag (same logic as POST /tags/merge)
    note_ids_result = await session.execute(
        select(NoteTagIndexModel.note_id)
        .where(NoteTagIndexModel.tag_full == source_id)
        .distinct()
    )
    note_ids = [row[0] for row in note_ids_result.all()]

    affected_notes = 0
    if note_ids:
        notes_result = await session.execute(
            select(NoteModel).where(NoteModel.id.in_(note_ids))
        )
        notes = list(notes_result.scalars().all())
        try:
            for note in notes:
                current_tags: list[str] = note.tags or []
                new_tags: list[str] = []
                seen: set[str] = set()
                for tag in current_tags:
                    replacement = target_id if tag == source_id else tag
                    if replacement not in seen:
                        seen.add(replacement)
                        new_tags.append(replacement)
                note.tags = list(new_tags)
                from sqlalchemy.orm.attributes import flag_modified  # noqa: PLC0415
                flag_modified(note, "tags")
                session.add(note)
                await _sync_tag_index(note.id, new_tags, session)
            affected_notes = len(notes)
        except Exception:
            await session.rollback()
            raise HTTPException(
                status_code=500, detail="Merge failed during note updates -- rolled back"
            )

    try:
        alias = TagAliasModel(alias=source_id, canonical_tag_id=target_id)
        session.add(alias)
        await session.execute(
            delete(CanonicalTagModel).where(CanonicalTagModel.id == source_id)
        )
        suggestion.status = "accepted"
        session.add(suggestion)
        await session.commit()
        session.expire_all()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=500, detail="Merge failed during alias/cleanup -- rolled back"
        )

    invalidate_tag_graph_cache()
    logger.info(
        "Accepted tag normalization suggestion %s: %r -> %r, affected_notes=%d",
        suggestion_id,
        source_id,
        target_id,
        affected_notes,
    )
    return NormalizationAcceptResponse(affected_notes=affected_notes)


@router.post("/normalization/suggestions/{suggestion_id}/reject", status_code=204)
async def reject_normalization_suggestion(
    suggestion_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Reject a merge suggestion."""
    from app.services.tag_normalizer import get_tag_normalizer_service  # noqa: PLC0415

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
    Merges duplicates that collapse to the same normalized form (keeps higher note_count).
    """
    from app.routers.notes import _sync_tag_index  # noqa: PLC0415
    from app.services.naming import normalize_tag_slug  # noqa: PLC0415
    from app.services.tag_graph import invalidate_tag_graph_cache  # noqa: PLC0415

    # Step 1: Load all canonical tags
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
                from sqlalchemy import text as sa_text  # noqa: PLC0415

                await session.execute(
                    sa_text(
                        "INSERT OR IGNORE INTO canonical_tags"
                        " (id, display_name, parent_tag, note_count, created_at)"
                        " VALUES (:id, :display_name, :parent_tag, :note_count, datetime('now'))"
                    ),
                    {
                        "id": normalized_id,
                        "display_name": new_display,
                        "parent_tag": new_parent,
                        "note_count": tag.note_count,
                    },
                )

                # Update NoteModel.tags and re-sync index
                if note_ids:
                    notes_result = await session.execute(
                        select(NoteModel).where(NoteModel.id.in_(note_ids))
                    )
                    for note in notes_result.scalars().all():
                        current_tags: list[str] = note.tags or []
                        new_tags = [
                            normalize_tag_slug(t) for t in current_tags
                        ]
                        # Deduplicate preserving order
                        seen: set[str] = set()
                        deduped: list[str] = []
                        for t in new_tags:
                            if t and t not in seen:
                                seen.add(t)
                                deduped.append(t)
                        note.tags = deduped
                        from sqlalchemy.orm.attributes import flag_modified  # noqa: PLC0415

                        flag_modified(note, "tags")
                        session.add(note)
                        await _sync_tag_index(note.id, deduped, session)

                renamed_count += 1
        else:
            # Multiple tags collapse to same normalized form -- merge
            # Sort by note_count desc so merged count reflects the best variant
            tag_group.sort(key=lambda t: t.note_count, reverse=True)

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
            from sqlalchemy import text as sa_text  # noqa: PLC0415

            await session.execute(
                sa_text(
                    "INSERT OR IGNORE INTO canonical_tags"
                    " (id, display_name, parent_tag, note_count, created_at)"
                    " VALUES (:id, :display_name, :parent_tag, :note_count, datetime('now'))"
                ),
                {
                    "id": normalized_id,
                    "display_name": new_display,
                    "parent_tag": new_parent,
                    "note_count": len(all_note_ids),
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
                    from sqlalchemy.orm.attributes import flag_modified  # noqa: PLC0415

                    flag_modified(note, "tags")
                    session.add(note)
                    await _sync_tag_index(note.id, new_tags_list, session)

            merged_count += 1

    await session.commit()
    invalidate_tag_graph_cache()
    logger.info(
        "Tag naming migration complete: renamed=%d merged=%d",
        renamed_count, merged_count,
    )
    return {"renamed": renamed_count, "merged": merged_count}


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
    # Use model_fields_set to distinguish "not supplied" from "explicitly null".
    # Setting parent_tag=null in the request clears the tag to top-level.
    if "parent_tag" in req.model_fields_set:
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
