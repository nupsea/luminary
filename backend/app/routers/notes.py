"""CRUD endpoints for notes.

Routes: POST /notes, GET /notes, PUT /notes/{id}, DELETE /notes/{id}, GET /notes/groups,
        GET /notes/search.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_session_factory
from app.models import NoteCollectionMemberModel, NoteModel, NoteTagIndexModel

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


class NoteUpdateRequest(BaseModel):
    content: str | None = None
    tags: list[str] | None = None
    group_name: str | None = None
    # section_id=None means "field not sent" (PATCH semantics — cannot clear via PATCH)
    section_id: str | None = None


class NoteResponse(BaseModel):
    id: str
    document_id: str | None
    chunk_id: str | None
    section_id: str | None
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


def _to_response(note: NoteModel) -> NoteResponse:
    return NoteResponse(
        id=note.id,
        document_id=note.document_id,
        chunk_id=note.chunk_id,
        section_id=note.section_id,
        content=note.content,
        tags=note.tags or [],
        group_name=note.group_name,
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


async def _upsert_note_graph(
    note_id: str, content: str, document_id: str | None, tags: list[str]
) -> None:
    """Fire-and-forget: upsert Note node and edges in Kuzu graph."""
    try:
        from app.services.note_graph import get_note_graph_service  # noqa: PLC0415

        await get_note_graph_service().upsert_note_node(note_id, content, document_id, tags)
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
    note = NoteModel(
        id=str(uuid.uuid4()),
        document_id=req.document_id,
        chunk_id=req.chunk_id,
        section_id=req.section_id,
        content=req.content,
        tags=req.tags,
        group_name=req.group_name,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(note)
    await _fts_insert(note.id, note.content, note.document_id, session)
    await _sync_tag_index(note.id, note.tags or [], session)
    await session.commit()
    task = asyncio.create_task(_embed_and_store_note(note.id, note.content, note.document_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    graph_task = asyncio.create_task(
        _upsert_note_graph(note.id, note.content, note.document_id, note.tags or [])
    )
    _background_tasks.add(graph_task)
    graph_task.add_done_callback(_background_tasks.discard)
    logger.info("Created note", extra={"note_id": note.id})
    return _to_response(note)


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

    return GroupsResponse(groups=groups, tags=tags)


@router.get("", response_model=list[NoteResponse])
async def list_notes(
    document_id: str | None = Query(default=None),
    group: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    collection_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[NoteResponse]:
    """List notes with optional filters."""
    stmt = select(NoteModel).order_by(NoteModel.updated_at.desc())

    if document_id:
        stmt = stmt.where(NoteModel.document_id == document_id)
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
                select(NoteCollectionMemberModel.note_id).where(
                    NoteCollectionMemberModel.collection_id == collection_id
                )
            )
        )

    result = await session.execute(stmt)
    notes = result.scalars().all()
    return [_to_response(n) for n in notes]


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
        note.tags = req.tags
    if req.group_name is not None:
        note.group_name = req.group_name
    if req.section_id is not None:
        note.section_id = req.section_id
    note.updated_at = datetime.now(UTC)

    await session.flush()  # Ensure content update is visible to other queries if needed
    await _fts_update(note.id, note.content, note.document_id, session)
    if req.tags is not None:
        await _sync_tag_index(note.id, note.tags or [], session)
    await session.commit()
    # Delete stale vector synchronously so hybrid search doesn't return the
    # old embedding while the background task re-embeds the new content.
    from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

    get_lancedb_service().delete_note_vector(note.id)
    task = asyncio.create_task(_embed_and_store_note(note.id, note.content, note.document_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    graph_task = asyncio.create_task(
        _upsert_note_graph(note.id, note.content, note.document_id, note.tags or [])
    )
    _background_tasks.add(graph_task)
    graph_task.add_done_callback(_background_tasks.discard)
    logger.info("Updated note", extra={"note_id": note_id})
    return _to_response(note)


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
    count: int = 5
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class NoteFlashcardItem(BaseModel):
    id: str
    question: str
    answer: str
    source_excerpt: str
    source: str

    model_config = {"from_attributes": True}


@router.post("/flashcards/generate", response_model=list[NoteFlashcardItem], status_code=201)
async def generate_note_flashcards(
    req: NoteFlashcardGenerateRequest,
    session: AsyncSession = Depends(get_db),
) -> list[NoteFlashcardItem]:
    """Generate flashcards from user notes scoped by tag or explicit note IDs."""
    import litellm  # noqa: PLC0415

    from app.services.flashcard import get_flashcard_service  # noqa: PLC0415

    try:
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

    from app.services.note_tagger import get_note_tagger  # noqa: PLC0415

    tags = await get_note_tagger().suggest_tags(note.content)
    logger.debug("suggest_tags note_id=%s returned %d tags", note_id, len(tags))
    return SuggestedTagsResponse(tags=tags)
