"""CRUD endpoints for notes.

Routes: POST /notes, GET /notes, PUT /notes/{id}, DELETE /notes/{id}, GET /notes/groups,
        GET /notes/search.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_session_factory
from app.models import (
    CollectionMemberModel,
    NoteLinkModel,
    NoteModel,
    NoteSourceModel,
    NoteTagIndexModel,
)

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()

router = APIRouter(prefix="/notes", tags=["notes"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class NoteCreateRequest(BaseModel):
    document_id: str | None = None
    chunk_id: str | None = None
    section_id: str | None = None
    content: str
    tags: list[str] = []
    group_name: str | None = None
    # S175: multi-document source linkage; legacy document_id still accepted
    source_document_ids: list[str] = []


class NoteUpdateRequest(BaseModel):
    content: str | None = None
    tags: list[str] | None = None
    group_name: str | None = None
    # section_id=None means "field not sent" (PATCH semantics — cannot clear via PATCH)
    section_id: str | None = None
    # S175: None means "not supplied" (do not change); [] means "remove all sources"
    source_document_ids: list[str] | None = None


class NoteResponse(BaseModel):
    id: str
    document_id: str | None
    chunk_id: str | None
    section_id: str | None
    content: str
    tags: list[str]
    group_name: str | None
    collection_ids: list[str] = []
    # S175: all source document IDs from NoteSourceModel pivot
    source_document_ids: list[str] = []
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
    total_notes: int


class SuggestedTagsResponse(BaseModel):
    tags: list[str]


class NoteSearchItem(BaseModel):
    note_id: str
    content: str
    tags: list[str]
    group_name: str | None
    document_id: str | None
    score: float
    source: str  # "fts" | "vector" | "both"


class NoteSearchResponse(BaseModel):
    query: str
    results: list[NoteSearchItem]
    total: int


class NoteEntityItem(BaseModel):
    name: str
    type: str
    confidence: float
    edge_type: str  # "WRITTEN_ABOUT" | "TAG_IS_CONCEPT"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(
    note: NoteModel,
    collection_ids: list[str] | None = None,
    source_document_ids: list[str] | None = None,
) -> NoteResponse:
    return NoteResponse(
        id=note.id,
        document_id=note.document_id,
        chunk_id=note.chunk_id,
        section_id=note.section_id,
        content=note.content,
        tags=note.tags or [],
        group_name=note.group_name,
        collection_ids=collection_ids or [],
        source_document_ids=source_document_ids or [],
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


async def _fts_insert(
    note_id: str, content: str, document_id: str | None, session: AsyncSession
) -> None:
    await session.execute(
        text("INSERT INTO notes_fts(note_id, content, document_id) VALUES (:nid, :content, :doc)"),
        {"nid": note_id, "content": content, "doc": document_id or ""},
    )


async def _fts_delete(note_id: str, session: AsyncSession) -> None:
    """Delete rows from the FTS5 virtual table for a given note_id.

    Note_id is UNINDEXED. We find the rowid(s) from the virtual table itself
    and delete by rowid for maximum compatibility.
    """
    await session.execute(
        text(
            "DELETE FROM notes_fts WHERE rowid IN "
            "(SELECT rowid FROM notes_fts WHERE note_id = :nid)"
        ),
        {"nid": note_id},
    )


async def _fts_update(
    note_id: str, content: str, document_id: str | None, session: AsyncSession
) -> None:
    await _fts_delete(note_id, session)
    await _fts_insert(note_id, content, document_id, session)


async def _sync_tag_index(note_id: str, tags: list[str], session: AsyncSession) -> None:
    """Sync NoteTagIndexModel and CanonicalTagModel for a note.

    Called synchronously within the same DB write transaction as the note.
    Handles create (empty -> new tags), update (old -> new tags), and delete
    (call with tags=[] to remove all rows for this note).
    """
    from app.services.naming import normalize_tag_slug  # noqa: PLC0415

    # Normalize all incoming tags before comparison
    tags = [normalize_tag_slug(t) for t in tags if normalize_tag_slug(t)]

    # Load currently indexed tags for this note
    old_rows = (
        await session.execute(
            select(NoteTagIndexModel.tag_full).where(NoteTagIndexModel.note_id == note_id)
        )
    ).scalars().all()
    old_tags: set[str] = set(old_rows)
    new_tags: set[str] = set(tags)

    removed = old_tags - new_tags
    added = new_tags - old_tags

    # Remove rows for deleted tags and decrement canonical counts
    for tag in removed:
        await session.execute(
            delete(NoteTagIndexModel).where(
                NoteTagIndexModel.note_id == note_id,
                NoteTagIndexModel.tag_full == tag,
            )
        )
        await session.execute(
            text(
                "UPDATE canonical_tags SET note_count = MAX(0, note_count - 1) WHERE id = :tag"
            ),
            {"tag": tag},
        )

    # Insert rows for new tags and upsert canonical registry
    for tag in added:
        segments = tag.split("/")
        tag_root = segments[0]
        tag_parent = "/".join(segments[:-1]) if len(segments) > 1 else ""
        display_name = segments[-1]
        canonical_parent = tag_parent if tag_parent else None

        await session.execute(
            text(
                "INSERT OR IGNORE INTO note_tag_index"
                " (note_id, tag_full, tag_root, tag_parent)"
                " VALUES (:note_id, :tag_full, :tag_root, :tag_parent)"
            ),
            {
                "note_id": note_id,
                "tag_full": tag,
                "tag_root": tag_root,
                "tag_parent": tag_parent,
            },
        )
        # Upsert canonical tag: insert or increment note_count atomically.
        await session.execute(
            text(
                "INSERT INTO canonical_tags"
                " (id, display_name, parent_tag, note_count, created_at)"
                " VALUES (:id, :display_name, :parent_tag, 1, datetime('now'))"
                " ON CONFLICT(id) DO UPDATE SET"
                " note_count = canonical_tags.note_count + 1"
            ),
            {
                "id": tag,
                "display_name": display_name,
                "parent_tag": canonical_parent,
            },
        )

    # Invalidate tag graph cache when tag index changes (S167)
    if removed or added:
        from app.services.tag_graph import invalidate_tag_graph_cache  # noqa: PLC0415

        invalidate_tag_graph_cache()


async def _sync_note_sources(
    note_id: str, source_document_ids: list[str], session: AsyncSession
) -> None:
    """Sync NoteSourceModel rows for a note (S175).

    Deletes rows not in new list; inserts new rows via INSERT OR IGNORE (idempotent).
    """
    if source_document_ids:
        # Delete rows for document_ids no longer in the list
        await session.execute(
            delete(NoteSourceModel).where(
                NoteSourceModel.note_id == note_id,
                NoteSourceModel.document_id.not_in(source_document_ids),
            )
        )
        # Insert new rows (INSERT OR IGNORE for composite PK dedup)
        for doc_id in source_document_ids:
            await session.execute(
                text(
                    "INSERT OR IGNORE INTO note_sources (note_id, document_id, added_at)"
                    " VALUES (:note_id, :document_id, :added_at)"
                ),
                {
                    "note_id": note_id,
                    "document_id": doc_id,
                    "added_at": datetime.now(UTC).isoformat(),
                },
            )
    else:
        # Empty list: remove all source rows for this note
        await session.execute(
            delete(NoteSourceModel).where(NoteSourceModel.note_id == note_id)
        )


async def _upsert_note_graph(
    note_id: str,
    content: str,
    document_id: str | None,
    tags: list[str],
    source_document_ids: list[str] | None = None,
) -> None:
    """Fire-and-forget: upsert Note node and edges in Kuzu graph."""
    try:
        from app.services.note_graph import get_note_graph_service  # noqa: PLC0415

        await get_note_graph_service().upsert_note_node(
            note_id, content, document_id, tags, source_document_ids or []
        )
        logger.debug("Note graph upserted note_id=%s", note_id)
    except Exception as exc:
        logger.warning("_upsert_note_graph failed (non-fatal): %s", exc)


async def _embed_and_store_note(note_id: str, content: str, document_id: str | None) -> None:
    """Embed note content and upsert vector. Non-fatal if embedding model unavailable.

    Checks the note's current content before upserting to avoid overwriting a
    newer embedding with a stale one (race between create and rapid update).
    """
    try:
        from app.services.embedder import get_embedding_service  # noqa: PLC0415
        from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

        loop = asyncio.get_event_loop()
        embedder = get_embedding_service()
        vector = await loop.run_in_executor(None, lambda: embedder.encode([content])[0])

        # Guard: if the note was updated after this task was created, the
        # content we embedded is stale -- skip the upsert.
        async with get_session_factory()() as session:
            row = (
                await session.execute(
                    select(NoteModel.content).where(NoteModel.id == note_id)
                )
            ).scalar_one_or_none()
        if row is None:
            logger.debug("Note %s deleted before embedding completed, skipping", note_id)
            return
        if row != content:
            logger.debug("Note %s content changed, skipping stale embedding", note_id)
            return

        get_lancedb_service().upsert_note_vector(note_id, document_id, content, vector)
        logger.debug("Note vector stored note_id=%s", note_id)
    except Exception as exc:
        logger.warning("_embed_and_store_note failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=NoteResponse, status_code=201)
async def create_note(
    req: NoteCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> NoteResponse:
    """Create a new note."""
    from app.services.naming import normalize_tag_slug  # noqa: PLC0415

    # Dedup: if a note with identical (document_id, section_id, content_hash) was
    # created within the last 5 seconds, return the existing note instead.
    content_hash = hashlib.sha256(req.content.encode()).hexdigest()[:16]
    dedup_cutoff = datetime.now(UTC) - timedelta(seconds=5)
    existing_result = await session.execute(
        select(NoteModel).where(
            NoteModel.document_id == req.document_id,
            NoteModel.section_id == req.section_id,
            NoteModel.content_hash == content_hash,
            NoteModel.created_at >= dedup_cutoff,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        logger.info("Dedup: returning existing note %s", existing.id)
        return _to_response(existing)

    note = NoteModel(
        id=str(uuid.uuid4()),
        document_id=req.document_id,
        chunk_id=req.chunk_id,
        section_id=req.section_id,
        content=req.content,
        content_hash=content_hash,
        group_name=req.group_name,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    # S208: Automatic tag saving for new notes if none provided
    tags = [_nt for t in (req.tags or []) if (_nt := normalize_tag_slug(t))]
    if not tags and req.content.strip():
        from app.services.note_tagger import get_note_tagger  # noqa: PLC0415
        try:
            raw_tags = await get_note_tagger().suggest_tags(req.content)
            tags = [_nt for t in raw_tags if (_nt := normalize_tag_slug(t))]
            logger.info("Auto-tagged new note %s with %d tags", note.id, len(tags))
        except Exception:
            logger.warning("Auto-tagging failed for new note %s", note.id, exc_info=True)

    note.tags = tags
    session.add(note)
    await _fts_insert(note.id, note.content, note.document_id, session)
    await _sync_tag_index(note.id, note.tags or [], session)
    # S175: sync multi-document source pivot
    await _sync_note_sources(note.id, req.source_document_ids, session)
    await session.commit()
    task = asyncio.create_task(_embed_and_store_note(note.id, note.content, note.document_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    graph_task = asyncio.create_task(
        _upsert_note_graph(
            note.id, note.content, note.document_id, note.tags or [], req.source_document_ids
        )
    )
    _background_tasks.add(graph_task)
    graph_task.add_done_callback(_background_tasks.discard)
    logger.info("Created note", extra={"note_id": note.id})
    return _to_response(note, source_document_ids=req.source_document_ids)


@router.get("/search", response_model=NoteSearchResponse)
async def search_notes(
    q: str = Query(..., min_length=1),
    k: int = Query(default=10, ge=1, le=50),
) -> NoteSearchResponse:
    """Hybrid FTS + semantic search over notes. Returns 422 if q is empty."""
    from app.services.note_search import get_note_search_service  # noqa: PLC0415

    results = await get_note_search_service().search(q, k=k)
    return NoteSearchResponse(
        query=q,
        results=[
            NoteSearchItem(
                note_id=r.note_id,
                content=r.content,
                tags=r.tags,
                group_name=r.group_name,
                document_id=r.document_id,
                score=round(r.score, 6),
                source=r.source,
            )
            for r in results
        ],
        total=len(results),
    )


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

    # Total notes count (unarchived)
    total_result = await session.execute(
        select(func.count()).select_from(NoteModel).where(NoteModel.archived.is_(False))
    )
    total_notes = total_result.scalar_one()

    return GroupsResponse(groups=groups, tags=tags, total_notes=total_notes)


@router.get("", response_model=list[NoteResponse])
async def list_notes(
    document_id: str | None = Query(default=None),
    group: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    collection_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[NoteResponse]:
    """List notes with optional filters."""
    stmt = (
        select(NoteModel)
        .where(NoteModel.archived.is_(False))
        .order_by(NoteModel.updated_at.desc())
    )

    if document_id:
        # S175: match notes via legacy document_id OR via NoteSourceModel pivot
        stmt = stmt.where(
            or_(
                NoteModel.document_id == document_id,
                NoteModel.id.in_(
                    select(NoteSourceModel.note_id).where(
                        NoteSourceModel.document_id == document_id
                    )
                ),
            )
        )
    if group:
        stmt = stmt.where(NoteModel.group_name == group)
    if tag:
        # Filter notes using NoteTagIndexModel prefix query.
        # 'science' matches notes tagged 'science', 'science/biology', 'science/physics/quantum'.
        stmt = stmt.where(
            NoteModel.id.in_(
                select(NoteTagIndexModel.note_id).where(
                    or_(
                        NoteTagIndexModel.tag_full == tag,
                        NoteTagIndexModel.tag_full.like(f"{tag}/%"),
                    )
                )
            )
        )
    if collection_id:
        stmt = stmt.where(
            NoteModel.id.in_(
                select(CollectionMemberModel.member_id).where(
                    CollectionMemberModel.collection_id == collection_id,
                    CollectionMemberModel.member_type == "note",
                )
            )
        )

    result = await session.execute(stmt)
    notes = list(result.scalars().all())

    # Bulk-load collection memberships and source_document_ids in one query each.
    coll_map: dict[str, list[str]] = {}
    src_map: dict[str, list[str]] = {}
    if notes:
        note_ids = [n.id for n in notes]
        member_rows = (
            await session.execute(
                select(
                    CollectionMemberModel.member_id,
                    CollectionMemberModel.collection_id,
                ).where(
                    CollectionMemberModel.member_id.in_(note_ids),
                    CollectionMemberModel.member_type == "note",
                )
            )
        ).all()
        for row in member_rows:
            coll_map.setdefault(row[0], []).append(row[1])

        # S175: bulk-load source_document_ids from pivot
        src_rows = (
            await session.execute(
                select(
                    NoteSourceModel.note_id,
                    NoteSourceModel.document_id,
                ).where(NoteSourceModel.note_id.in_(note_ids))
            )
        ).all()
        for row in src_rows:
            src_map.setdefault(row[0], []).append(row[1])

    return [
        _to_response(n, coll_map.get(n.id, []), src_map.get(n.id, []))
        for n in notes
    ]


async def _apply_note_update(
    note_id: str, req: NoteUpdateRequest, session: AsyncSession
) -> NoteResponse:
    result = await session.execute(select(NoteModel).where(NoteModel.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    if req.content is not None:
        note.content = req.content
    if req.tags is not None:
        from app.services.naming import normalize_tag_slug as _norm  # noqa: PLC0415
        note.tags = [_norm(t) for t in req.tags if _norm(t)]
    if req.group_name is not None:
        note.group_name = req.group_name
    if req.section_id is not None:
        note.section_id = req.section_id
    note.updated_at = datetime.now(UTC)

    await session.flush()  # Ensure content update is visible to other queries if needed
    await _fts_update(note.id, note.content, note.document_id, session)
    if req.tags is not None:
        await _sync_tag_index(note.id, note.tags or [], session)
    # S175: sync source document pivot only when field is explicitly supplied
    if req.source_document_ids is not None:
        await _sync_note_sources(note.id, req.source_document_ids, session)
    await session.commit()
    # Fetch updated source_document_ids for response
    src_rows = (
        await session.execute(
            select(NoteSourceModel.document_id).where(NoteSourceModel.note_id == note.id)
        )
    ).scalars().all()
    # Delete stale vector synchronously so hybrid search doesn't return the
    # old embedding while the background task re-embeds the new content.
    from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

    get_lancedb_service().delete_note_vector(note.id)
    task = asyncio.create_task(_embed_and_store_note(note.id, note.content, note.document_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    graph_task = asyncio.create_task(
        _upsert_note_graph(
            note.id, note.content, note.document_id, note.tags or [], list(src_rows)
        )
    )
    _background_tasks.add(graph_task)
    graph_task.add_done_callback(_background_tasks.discard)
    # Re-fetch relevant IDs for a fully populated response
    coll_rows = (
        await session.execute(
            select(CollectionMemberModel.collection_id).where(
                CollectionMemberModel.member_id == note.id,
                CollectionMemberModel.member_type == "note",
            )
        )
    ).scalars().all()

    logger.info("Updated note", extra={"note_id": note_id})
    return _to_response(
        note,
        collection_ids=list(coll_rows),
        source_document_ids=list(src_rows),
    )


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: str,
    req: NoteUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> NoteResponse:
    """Update a note's content, tags, or group."""
    return await _apply_note_update(note_id, req, session)


@router.patch("/{note_id}", response_model=NoteResponse)
async def patch_note(
    note_id: str,
    req: NoteUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> NoteResponse:
    """Partially update a note's content, tags, or group."""
    return await _apply_note_update(note_id, req, session)


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

    await _fts_delete(note_id, session)
    await _sync_tag_index(note_id, [], session)
    # Delete Note graph node synchronously before removing the SQL row
    from app.services.note_graph import get_note_graph_service  # noqa: PLC0415

    await get_note_graph_service().delete_note_node(note_id)
    await session.execute(delete(NoteModel).where(NoteModel.id == note_id))
    await session.commit()
    from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

    get_lancedb_service().delete_note_vector(note_id)
    logger.info("Deleted note", extra={"note_id": note_id})


@router.get("/{note_id}/entities", response_model=list[NoteEntityItem])
async def get_note_entities(note_id: str) -> list[NoteEntityItem]:
    """Return entities linked to a note via WRITTEN_ABOUT or TAG_IS_CONCEPT Kuzu edges."""
    from app.services.note_graph import get_note_graph_service  # noqa: PLC0415

    entities = await get_note_graph_service().get_entities_for_note(note_id)
    return [NoteEntityItem(**e) for e in entities]


class NoteFlashcardGenerateRequest(BaseModel):
    tag: str | None = None
    note_ids: list[str] | None = None
    collection_id: str | None = None
    count: int = 5
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    force_regenerate: bool = False


class NoteFlashcardItem(BaseModel):
    id: str
    question: str
    answer: str
    source_excerpt: str
    source: str

    model_config = {"from_attributes": True}


class NoteFlashcardGenerateResponse(BaseModel):
    created: int
    skipped: int
    deck: str


@router.get("/flashcards/generate/preview")
async def preview_note_flashcard_generation(
    collection_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Return {total_notes, already_covered} for a collection without generating (S169)."""
    from sqlalchemy import func as sa_func  # noqa: PLC0415

    from app.models import (  # noqa: PLC0415
        FlashcardModel,
        CollectionMemberModel,
        CollectionModel,
    )

    coll_result = await session.execute(
        select(CollectionModel).where(CollectionModel.id == collection_id)
    )
    collection = coll_result.scalar_one_or_none()
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    member_result = await session.execute(
        select(sa_func.count()).select_from(CollectionMemberModel).where(
            CollectionMemberModel.collection_id == collection_id,
            CollectionMemberModel.member_type == "note",
        )
    )
    total_notes = member_result.scalar_one()

    covered_result = await session.execute(
        select(sa_func.count(FlashcardModel.source_content_hash.distinct())).where(
            FlashcardModel.deck == collection.name,
            FlashcardModel.source == "note",
            FlashcardModel.source_content_hash.is_not(None),
        )
    )
    already_covered = covered_result.scalar_one()

    return {"total_notes": total_notes, "already_covered": already_covered}


@router.post("/flashcards/generate", status_code=201)
async def generate_note_flashcards(
    req: NoteFlashcardGenerateRequest,
    session: AsyncSession = Depends(get_db),
) -> list[NoteFlashcardItem] | NoteFlashcardGenerateResponse:
    """Generate flashcards from user notes scoped by tag, note IDs, or collection (S169)."""
    import litellm  # noqa: PLC0415

    from app.services.flashcard import get_flashcard_service  # noqa: PLC0415

    # 422 guard: collection_id and note_ids are mutually exclusive
    if req.collection_id and req.note_ids:
        raise HTTPException(
            status_code=422,
            detail="Provide either collection_id or note_ids, not both",
        )

    try:
        if req.collection_id:
            result = await get_flashcard_service().generate_from_collection(
                collection_id=req.collection_id,
                count_per_note=req.count,
                difficulty=req.difficulty,
                session=session,
                force_regenerate=req.force_regenerate,
            )
            logger.info(
                "Collection flashcard gen: created=%d skipped=%d deck=%s",
                result["created"],
                result["skipped"],
                result["deck"],
            )
            return NoteFlashcardGenerateResponse(**result)

        cards = await get_flashcard_service().generate_from_notes(
            tag=req.tag,
            note_ids=req.note_ids,
            count=req.count,
            difficulty=req.difficulty,
            session=session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.APIConnectionError,
        ConnectionRefusedError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unavailable. Start it with: ollama serve",
        ) from exc

    logger.info("Generated %d note flashcards tag=%s", len(cards), req.tag)
    return [NoteFlashcardItem.model_validate(c) for c in cards]


@router.get("/flashcards", response_model=list[NoteFlashcardItem])
async def list_note_flashcards(
    session: AsyncSession = Depends(get_db),
) -> list[NoteFlashcardItem]:
    """Return all flashcards generated from notes (source='note'), newest first."""
    from app.models import FlashcardModel  # noqa: PLC0415

    result = await session.execute(
        select(FlashcardModel)
        .where(FlashcardModel.source == "note")
        .order_by(FlashcardModel.created_at.desc())
    )
    cards = list(result.scalars().all())
    return [NoteFlashcardItem.model_validate(c) for c in cards]


# ---------------------------------------------------------------------------
# Cluster endpoints (static paths must come before /{note_id} catch-all)
# ---------------------------------------------------------------------------


class ClusterNotePreview(BaseModel):
    note_id: str
    excerpt: str


class ClusterSuggestionResponse(BaseModel):
    id: str
    suggested_name: str
    note_ids: list[str] = []
    note_count: int
    confidence_score: float
    status: str
    created_at: datetime
    previews: list[ClusterNotePreview]


class BatchAcceptItem(BaseModel):
    suggestion_id: str
    name_override: str | None = None
    note_ids: list[str] | None = None  # If set, overrides the suggestion's note_ids (drag-and-drop)


class BatchAcceptRequest(BaseModel):
    items: list[BatchAcceptItem]


@router.post("/cluster", status_code=202)
async def trigger_cluster(
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Fire-and-forget HDBSCAN clustering over note_vectors_v2.

    Returns {queued: True, total_notes: int} or {cached: True, last_run: ISO str}
    if a pending suggestion was created within the last hour.
    """
    from app.services.clustering_service import get_clustering_service  # noqa: PLC0415

    svc = get_clustering_service()

    # Check rate-limit synchronously before spawning task
    last_run = await svc.get_pending_last_run(session)
    if last_run is not None:
        from datetime import timedelta  # noqa: PLC0415

        now = datetime.now(UTC)
        age = now - (last_run.replace(tzinfo=UTC) if last_run.tzinfo is None else last_run)
        if age < timedelta(hours=1):
            return {"cached": True, "last_run": last_run.isoformat()}

    # Count total notes
    total_notes = (
        await session.execute(select(func.count(NoteModel.id)))
    ).scalar_one()

    # Spawn fire-and-forget task with its own session
    async def _run_clustering() -> None:
        try:
            async with get_session_factory()() as new_session:
                count = await get_clustering_service().cluster_notes(new_session)
                logger.info("Background clustering finished: %d suggestions", count)
        except Exception as exc:
            logger.error("Background clustering task failed: %s", exc)

    task = asyncio.create_task(_run_clustering())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"queued": True, "total_notes": total_notes}


@router.get("/cluster/suggestions", response_model=list[ClusterSuggestionResponse])
async def list_cluster_suggestions(
    session: AsyncSession = Depends(get_db),
) -> list[ClusterSuggestionResponse]:
    """Return pending cluster suggestions sorted by confidence_score DESC with note previews."""
    from app.services.clustering_service import get_clustering_service  # noqa: PLC0415

    items = await get_clustering_service().get_pending_suggestions(session)
    return [
        ClusterSuggestionResponse(
            id=item["id"],
            suggested_name=item["suggested_name"],
            note_ids=item.get("note_ids", []),
            note_count=item["note_count"],
            confidence_score=item["confidence_score"],
            status=item["status"],
            created_at=item["created_at"],
            previews=[ClusterNotePreview(**p) for p in item["previews"]],
        )
        for item in items
    ]


# NOTE: batch-accept must be registered BEFORE /{suggestion_id} routes
@router.post("/cluster/suggestions/batch-accept")
async def batch_accept_cluster_suggestions(
    req: BatchAcceptRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Accept multiple cluster suggestions in a single transaction.

    Returns list of created collection IDs.
    """
    from app.services.clustering_service import get_clustering_service  # noqa: PLC0415

    items_dicts = [
        {
            "suggestion_id": it.suggestion_id,
            "name_override": it.name_override,
            "note_ids": it.note_ids,
        }
        for it in req.items
    ]
    created_ids = await get_clustering_service().batch_accept_suggestions(items_dicts, session)
    return {"collection_ids": created_ids}


# ---------------------------------------------------------------------------
# S207: Naming normalization check & apply
# ---------------------------------------------------------------------------


class NamingViolation(BaseModel):
    type: str  # "tag" or "collection"
    id: str
    current_name: str
    suggested_name: str
    action: str  # "rename" or "merge"
    merge_target_id: str | None = None


class NamingFixItem(BaseModel):
    type: str
    id: str
    current_name: str
    suggested_name: str
    action: str = "rename"


class NamingFixRequest(BaseModel):
    fixes: list[NamingFixItem]


# NOTE: These routes registered BEFORE /{suggestion_id} to prevent path collision
@router.post("/cluster/normalize-check", response_model=list[NamingViolation])
async def normalize_check(
    session: AsyncSession = Depends(get_db),
) -> list[NamingViolation]:
    """Return naming violation suggestions for tags and collections."""
    from app.services.clustering_service import get_clustering_service  # noqa: PLC0415

    violations = await get_clustering_service().detect_naming_violations(session)
    return [NamingViolation(**v) for v in violations]


@router.post("/cluster/normalize-apply")
async def normalize_apply(
    req: NamingFixRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Apply naming fixes transactionally."""
    from app.services.clustering_service import get_clustering_service  # noqa: PLC0415

    fixes_dicts = [f.model_dump() for f in req.fixes]
    result = await get_clustering_service().apply_naming_fixes(fixes_dicts, session)
    return result


@router.post("/cluster/suggestions/{suggestion_id}/accept")
async def accept_cluster_suggestion(
    suggestion_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Accept a cluster suggestion: create Collection + member rows."""
    from app.services.clustering_service import get_clustering_service  # noqa: PLC0415

    collection_id = await get_clustering_service().accept_suggestion(suggestion_id, session)
    if collection_id is None:
        raise HTTPException(status_code=404, detail="Cluster suggestion not found")
    return {"collection_id": collection_id}


@router.post("/cluster/suggestions/{suggestion_id}/reject")
async def reject_cluster_suggestion(
    suggestion_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Reject a cluster suggestion."""
    from app.services.clustering_service import get_clustering_service  # noqa: PLC0415

    found = await get_clustering_service().reject_suggestion(suggestion_id, session)
    if not found:
        raise HTTPException(status_code=404, detail="Cluster suggestion not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# S171: Note links and autocomplete
# NOTE: GET /notes/autocomplete is a static path and MUST be registered before
# the /{note_id} catch-all to prevent FastAPI from matching "autocomplete" as a
# note ID.
# ---------------------------------------------------------------------------


class NoteLinkCreateRequest(BaseModel):
    target_note_id: str
    link_type: str = "see-also"


class NoteLinkItem(BaseModel):
    id: str
    note_id: str
    preview: str
    link_type: str
    created_at: datetime


class NoteLinksResponse(BaseModel):
    outgoing: list[NoteLinkItem]
    incoming: list[NoteLinkItem]


class NoteAutocompleteItem(BaseModel):
    id: str
    preview: str


@router.get("/autocomplete", response_model=list[NoteAutocompleteItem])
async def autocomplete_notes(
    q: str = Query(default="", max_length=200),
    session: AsyncSession = Depends(get_db),
) -> list[NoteAutocompleteItem]:
    """Return up to 8 notes whose content starts with q (case-insensitive). (S171)

    Registered BEFORE /{note_id} to prevent FastAPI from matching "autocomplete"
    as a note ID wildcard.
    """
    if not q.strip():
        result = await session.execute(
            select(NoteModel.id, NoteModel.content)
            .order_by(NoteModel.updated_at.desc())
            .limit(8)
        )
    else:
        result = await session.execute(
            select(NoteModel.id, NoteModel.content)
            .where(NoteModel.content.ilike(f"{q}%"))
            .order_by(NoteModel.updated_at.desc())
            .limit(8)
        )
    return [
        NoteAutocompleteItem(id=row[0], preview=row[1][:100])
        for row in result.all()
    ]


@router.post("/{note_id}/links", response_model=NoteLinkItem, status_code=201)
async def create_note_link(
    note_id: str,
    req: NoteLinkCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> NoteLinkItem:
    """Create a typed link from note_id to req.target_note_id. (S171)

    Fires an async Kuzu edge upsert. Returns 404 if source or target note missing.
    Returns 409 if the (source, target, link_type) triple already exists.
    """
    from app.services.note_graph import get_note_graph_service  # noqa: PLC0415

    # Validate source and target exist
    source = (
        await session.execute(select(NoteModel).where(NoteModel.id == note_id))
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source note not found")

    target = (
        await session.execute(
            select(NoteModel).where(NoteModel.id == req.target_note_id)
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Target note not found")

    # Check uniqueness
    existing = (
        await session.execute(
            select(NoteLinkModel).where(
                NoteLinkModel.source_note_id == note_id,
                NoteLinkModel.target_note_id == req.target_note_id,
                NoteLinkModel.link_type == req.link_type,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Link already exists")

    link = NoteLinkModel(
        id=str(uuid.uuid4()),
        source_note_id=note_id,
        target_note_id=req.target_note_id,
        link_type=req.link_type,
        created_at=datetime.now(UTC),
    )
    session.add(link)
    await session.commit()
    await session.refresh(link)

    # Fire-and-forget Kuzu edge upsert
    task = asyncio.create_task(
        get_note_graph_service().upsert_links_to_edge(
            note_id, req.target_note_id, req.link_type
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return NoteLinkItem(
        id=link.id,
        note_id=req.target_note_id,
        preview=target.content[:100],
        link_type=link.link_type,
        created_at=link.created_at,
    )


@router.delete("/{note_id}/links/{target_note_id}", status_code=204)
async def delete_note_link(
    note_id: str,
    target_note_id: str,
    link_type: str = Query(default="see-also"),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a typed link from note_id to target_note_id. (S171)

    Fires an async Kuzu edge delete. Returns 404 if link not found.
    """
    from app.services.note_graph import get_note_graph_service  # noqa: PLC0415

    link = (
        await session.execute(
            select(NoteLinkModel).where(
                NoteLinkModel.source_note_id == note_id,
                NoteLinkModel.target_note_id == target_note_id,
                NoteLinkModel.link_type == link_type,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")

    await session.delete(link)
    await session.commit()

    task = asyncio.create_task(
        get_note_graph_service().delete_links_to_edge(note_id, target_note_id, link_type)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.get("/{note_id}/links", response_model=NoteLinksResponse)
async def get_note_links(
    note_id: str,
    session: AsyncSession = Depends(get_db),
) -> NoteLinksResponse:
    """Return outgoing and incoming links for a note. (S171)

    Outgoing: links WHERE source_note_id = note_id
    Incoming: links WHERE target_note_id = note_id (backlinks)
    Each item includes a 100-char preview from the linked note's content.
    """
    # Outgoing links
    out_rows = (
        await session.execute(
            select(NoteLinkModel, NoteModel.content)
            .join(NoteModel, NoteLinkModel.target_note_id == NoteModel.id)
            .where(NoteLinkModel.source_note_id == note_id)
            .order_by(NoteLinkModel.created_at.desc())
        )
    ).all()

    # Incoming links (backlinks)
    in_rows = (
        await session.execute(
            select(NoteLinkModel, NoteModel.content)
            .join(NoteModel, NoteLinkModel.source_note_id == NoteModel.id)
            .where(NoteLinkModel.target_note_id == note_id)
            .order_by(NoteLinkModel.created_at.desc())
        )
    ).all()

    outgoing = [
        NoteLinkItem(
            id=row[0].id,
            note_id=row[0].target_note_id,
            preview=row[1][:100],
            link_type=row[0].link_type,
            created_at=row[0].created_at,
        )
        for row in out_rows
    ]
    incoming = [
        NoteLinkItem(
            id=row[0].id,
            note_id=row[0].source_note_id,
            preview=row[1][:100],
            link_type=row[0].link_type,
            created_at=row[0].created_at,
        )
        for row in in_rows
    ]
    return NoteLinksResponse(outgoing=outgoing, incoming=incoming)


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: str,
    session: AsyncSession = Depends(get_db),
) -> NoteResponse:
    """Get a single note by ID, including collection_ids.

    Registered AFTER all static-path GET routes (/search, /groups, /flashcards)
    to prevent the dynamic {note_id} segment from shadowing them.
    """
    note = (
        await session.execute(select(NoteModel).where(NoteModel.id == note_id))
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    member_rows = (
        await session.execute(
            select(CollectionMemberModel.collection_id).where(
                CollectionMemberModel.member_id == note_id,
                CollectionMemberModel.member_type == "note",
            )
        )
    ).scalars().all()

    # S175: fetch source_document_ids from pivot
    src_rows = (
        await session.execute(
            select(NoteSourceModel.document_id).where(NoteSourceModel.note_id == note_id)
        )
    ).scalars().all()

    return _to_response(note, list(member_rows), list(src_rows))


class GapDetectRequest(BaseModel):
    note_ids: list[str] = []
    document_id: str


class GapDetectResponse(BaseModel):
    gaps: list[str]
    covered: list[str]
    query_used: str


@router.post("/gap-detect", response_model=GapDetectResponse)
async def gap_detect(
    req: GapDetectRequest,
    session: AsyncSession = Depends(get_db),
) -> GapDetectResponse:
    """Identify book concepts absent from the user's notes."""
    if not req.note_ids:
        raise HTTPException(status_code=422, detail="note_ids must be non-empty")

    import litellm  # noqa: PLC0415

    from app.services.gap_detector import get_gap_detector  # noqa: PLC0415

    try:
        report = await get_gap_detector().detect_gaps(
            note_ids=req.note_ids,
            document_id=req.document_id,
            session=session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        litellm.ServiceUnavailableError,
        litellm.APIConnectionError,
        ConnectionRefusedError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unavailable. Start it with: ollama serve",
        ) from exc

    logger.info(
        "gap_detect: doc=%s gaps=%d covered=%d",
        req.document_id,
        len(report["gaps"]),
        len(report["covered"]),
    )
    return GapDetectResponse(
        gaps=report["gaps"],
        covered=report["covered"],
        query_used=report["query_used"],
    )


@router.post("/{note_id}/suggest-tags", response_model=SuggestedTagsResponse)
async def suggest_tags(
    note_id: str,
    session: AsyncSession = Depends(get_db),
) -> SuggestedTagsResponse:
    """Return LLM-suggested tags for an existing note. Always HTTP 200 when note exists."""
    result = await session.execute(select(NoteModel).where(NoteModel.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    # Grab content before releasing DB session to avoid holding a connection
    # during a potentially slow LLM call.
    note_content = note.content

    from app.services.naming import normalize_tag_slug as _norm_tag  # noqa: PLC0415
    from app.services.note_tagger import get_note_tagger  # noqa: PLC0415

    raw_tags = await get_note_tagger().suggest_tags(note_content)
    tags = [n for t in raw_tags if (n := _norm_tag(t))]
    logger.debug("suggest_tags note_id=%s returned %d tags", note_id, len(tags))
    return SuggestedTagsResponse(tags=tags)
