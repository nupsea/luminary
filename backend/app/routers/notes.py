"""CRUD endpoints for notes.

Routes: POST /notes, GET /notes, PUT /notes/{id}, DELETE /notes/{id}, GET /notes/groups,
        GET /notes/search.
"""

import asyncio
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

_background_tasks: set[asyncio.Task] = set()

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


async def _fts_insert(
    note_id: str, content: str, document_id: str | None, session: AsyncSession
) -> None:
    await session.execute(
        text("INSERT INTO notes_fts(note_id, content, document_id) VALUES (:nid, :content, :doc)"),
        {"nid": note_id, "content": content, "doc": document_id or ""},
    )


async def _fts_delete_rows(note_id: str, session: AsyncSession) -> None:
    """Delete FTS5 rows for a note_id using rowid-based deletion (reliable for FTS5)."""
    rows = (
        await session.execute(
            text("SELECT rowid FROM notes_fts WHERE note_id = :nid"),
            {"nid": note_id},
        )
    ).fetchall()
    for (rowid,) in rows:
        await session.execute(
            text("DELETE FROM notes_fts WHERE rowid = :rowid"),
            {"rowid": rowid},
        )


async def _fts_update(
    note_id: str, content: str, document_id: str | None, session: AsyncSession
) -> None:
    await _fts_delete_rows(note_id, session)
    await session.execute(
        text("INSERT INTO notes_fts(note_id, content, document_id) VALUES (:nid, :content, :doc)"),
        {"nid": note_id, "content": content, "doc": document_id or ""},
    )


async def _fts_delete(note_id: str, session: AsyncSession) -> None:
    await _fts_delete_rows(note_id, session)


async def _embed_and_store_note(note_id: str, content: str, document_id: str | None) -> None:
    """Embed note content and upsert vector. Non-fatal if embedding model unavailable."""
    try:
        from app.services.embedder import get_embedding_service  # noqa: PLC0415
        from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

        loop = asyncio.get_event_loop()
        embedder = get_embedding_service()
        vector = await loop.run_in_executor(None, lambda: embedder.encode([content])[0])
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
        content=req.content,
        tags=req.tags,
        group_name=req.group_name,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(note)
    await _fts_insert(note.id, note.content, note.document_id, session)
    await session.commit()
    await session.refresh(note)
    task = asyncio.create_task(_embed_and_store_note(note.id, note.content, note.document_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
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
    note.updated_at = datetime.utcnow()

    await _fts_update(note.id, note.content, note.document_id, session)
    await session.commit()
    await session.refresh(note)
    task = asyncio.create_task(_embed_and_store_note(note.id, note.content, note.document_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
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
    await session.execute(delete(NoteModel).where(NoteModel.id == note_id))
    await session.commit()
    from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

    get_lancedb_service().delete_note_vector(note_id)
    logger.info("Deleted note", extra={"note_id": note_id})


class NoteFlashcardGenerateRequest(BaseModel):
    tag: str | None = None
    note_ids: list[str] | None = None
    count: int = 5


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
