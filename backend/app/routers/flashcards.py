"""Flashcard CRUD and generation endpoints.

Routes:
  POST /flashcards/generate                              — LLM-generate cards for a document
  POST /flashcards/from-gaps                             — one LLM flashcard per gap string (S97)
  POST /flashcards/cloze/{section_id}                   — generate cloze deletion cards (S154)
  GET  /flashcards/search                               — unified search with FTS + filters (S184)
  GET  /flashcards/audit/{document_id}                  — Bloom's coverage report (S153)
  POST /flashcards/audit/{document_id}/fill             — fill Bloom's gaps (S153)
  GET  /flashcards/health/{document_id}                 — deck health report (S160)
  POST /flashcards/health/{document_id}/archive-mastered — archive mastered cards (S160)
  POST /flashcards/health/{document_id}/fill-uncovered  — generate for uncovered sections (S160)
  GET  /flashcards/{document_id}/export/csv             — CSV download
  GET  /flashcards/{document_id}                        — list cards ordered by created_at desc
  PUT  /flashcards/{card_id}                — update question/answer, sets is_user_edited
  DELETE /flashcards/{card_id}              — delete a card (204)
  POST /flashcards/{card_id}/review         — FSRS review with rating
  GET  /flashcards/{card_id}/source-context — source passage for SourceContextPanel (S155)

NOTE: The /search, /audit, /cloze, /health routes must be registered BEFORE /{document_id}
to prevent FastAPI from matching literal segments as document_id.
"""

import asyncio
import csv
import io
import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

import litellm
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    ChunkModel,
    DocumentModel,
    FlashcardModel,
    CollectionModel,
    ReviewEventModel,
    SectionModel,
)
from app.services.deck_health import DeckHealthService, get_deck_health_service
from app.services.flashcard import (
    FlashcardService,
    _delete_flashcard_fts,
    _sync_flashcard_fts,
    get_flashcard_service,
)
from app.services.flashcard_audit import FlashcardAuditService, get_flashcard_audit_service
from app.services.fsrs_service import FSRSService, get_fsrs_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/flashcards", tags=["flashcards"])

# Strong references to fire-and-forget coverage update tasks (asyncio holds only weak refs).
_background_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class FlashcardGenerateRequest(BaseModel):
    document_id: str
    scope: Literal["full", "section"] = "full"
    section_heading: str | None = None
    count: int = 10
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    context: str | None = None  # selected text from reader; used directly when provided


class FromGapsRequest(BaseModel):
    gaps: list[str] = Field(min_length=1)
    document_id: str = ""


class FromGapsResponse(BaseModel):
    created: int


class FlashcardUpdateRequest(BaseModel):
    question: str | None = None
    answer: str | None = None


class GenerateFromGraphRequest(BaseModel):
    document_id: str
    k: int = Field(default=5, ge=1, le=20)


class EntityPairPreview(BaseModel):
    name_a: str
    name_b: str
    relation_label: str
    confidence: float


class EntityPairsResponse(BaseModel):
    pairs: list[EntityPairPreview]


class ReviewRequest(BaseModel):
    rating: Literal["again", "hard", "good", "easy"]
    session_id: str | None = None


class GenerateTechnicalRequest(BaseModel):
    document_id: str
    scope: Literal["full", "section"] = "full"
    section_heading: str | None = None
    count: int = 10


class FlashcardResponse(BaseModel):
    id: str
    document_id: str | None
    chunk_id: str | None
    source: str = "document"
    question: str
    answer: str
    source_excerpt: str
    difficulty: str = "medium"
    is_user_edited: bool
    fsrs_state: str
    fsrs_stability: float
    fsrs_difficulty: float
    due_date: datetime | None
    reps: int
    lapses: int
    created_at: datetime
    # S137: Bloom's Taxonomy fields
    flashcard_type: str | None = None
    bloom_level: int | None = None
    # S138: section_id derived from chunk -- populated by endpoints that do the join
    section_id: str | None = None
    # S154: cloze deletion text with {{term}} markers; null for non-cloze cards
    cloze_text: str | None = None
    # S179: chunk classifier label; null for non-document-chunk cards
    chunk_classification: str | None = None
    # S188: section heading for source grounding display
    section_heading: str | None = None

    model_config = {"from_attributes": True}


class CoverageReportResponse(BaseModel):
    """Response schema for GET /flashcards/audit/{document_id} (S153)."""

    total_cards: int
    by_bloom_level: dict[str, int]  # JSON keys are always strings
    by_section: dict[str, dict]  # BloomSectionStat as plain dict
    coverage_score: float
    gaps: list[dict]  # BloomGap as plain dict


class FillGapsResponse(BaseModel):
    """Response schema for POST /flashcards/audit/{document_id}/fill (S153)."""

    created: int


class DeckHealthReportResponse(BaseModel):
    """Response schema for GET /flashcards/health/{document_id} (S160)."""

    orphaned: int
    orphaned_ids: list[str]
    mastered: int
    mastered_ids: list[str]
    stale: int
    stale_ids: list[str]
    uncovered_sections: int
    uncovered_section_ids: list[str]
    hotspot_sections: list[dict]


class ArchiveMasteredResponse(BaseModel):
    """Response schema for POST /flashcards/health/{document_id}/archive-mastered (S160)."""

    archived: int


class FillUncoveredRequest(BaseModel):
    """Request body for POST /flashcards/health/{document_id}/fill-uncovered (S160)."""

    section_ids: list[str] = Field(min_length=1)


class FillUncoveredResponse(BaseModel):
    """Response schema for POST /flashcards/health/{document_id}/fill-uncovered (S160)."""

    queued: int


class SourceContextResponse(BaseModel):
    """Response schema for GET /flashcards/{card_id}/source-context (S155)."""

    section_heading: str
    section_preview: str
    document_title: str
    pdf_page_number: int | None
    section_id: str
    document_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(
    card: FlashcardModel, section_id: str | None = None
) -> FlashcardResponse:
    return FlashcardResponse(
        id=card.id,
        document_id=card.document_id,
        chunk_id=card.chunk_id,
        source=card.source if card.source else "document",
        question=card.question,
        answer=card.answer,
        source_excerpt=card.source_excerpt,
        difficulty=card.difficulty,
        is_user_edited=card.is_user_edited,
        fsrs_state=card.fsrs_state,
        fsrs_stability=card.fsrs_stability,
        fsrs_difficulty=card.fsrs_difficulty,
        due_date=card.due_date,
        reps=card.reps,
        lapses=card.lapses,
        created_at=card.created_at,
        flashcard_type=getattr(card, "flashcard_type", None),
        bloom_level=getattr(card, "bloom_level", None),
        section_id=section_id,
        cloze_text=getattr(card, "cloze_text", None),
        chunk_classification=getattr(card, "chunk_classification", None),
        section_heading=getattr(card, "section_heading", None),
    )


# ---------------------------------------------------------------------------
# S184: Search response model
# ---------------------------------------------------------------------------


class FlashcardSearchResponse(BaseModel):
    items: list[FlashcardResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# NOTE: /search is registered BEFORE /{document_id} to prevent FastAPI from
# matching the literal segment "search" as a document_id wildcard.


@router.get("/search", response_model=FlashcardSearchResponse)
async def search_flashcards(
    query: str | None = Query(default=None),
    document_id: str | None = Query(default=None),
    collection_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    bloom_level_min: int | None = Query(default=None),
    bloom_level_max: int | None = Query(default=None),
    fsrs_state: str | None = Query(default=None),
    flashcard_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    service: FlashcardService = Depends(get_flashcard_service),
) -> FlashcardSearchResponse:
    """Search flashcards with optional FTS query and structured filters (S184).

    All filters combine with AND. Returns paginated FlashcardResponse list.
    """
    cards, total = await service.search(
        session=session,
        query=query,
        document_id=document_id,
        collection_id=collection_id,
        tag=tag,
        bloom_level_min=bloom_level_min,
        bloom_level_max=bloom_level_max,
        fsrs_state=fsrs_state,
        flashcard_type=flashcard_type,
        page=page,
        page_size=page_size,
    )
    return FlashcardSearchResponse(
        items=[_to_response(c) for c in cards],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/generate", response_model=list[FlashcardResponse], status_code=201)
async def generate_flashcards(
    req: FlashcardGenerateRequest,
    session: AsyncSession = Depends(get_db),
    service: FlashcardService = Depends(get_flashcard_service),
) -> list[FlashcardResponse]:
    """Generate flashcards for a document using LLM."""
    try:
        cards = await service.generate(
            document_id=req.document_id,
            scope=req.scope,
            section_heading=req.section_heading,
            count=req.count,
            difficulty=req.difficulty,
            session=session,
            context=req.context,
        )
    except (
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.APIConnectionError,
        ConnectionRefusedError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Start it with: ollama serve",
        ) from exc
    logger.info(
        "Generated flashcards",
        extra={"document_id": req.document_id, "count": len(cards)},
    )
    return [_to_response(c) for c in cards]


@router.post("/from-gaps", response_model=FromGapsResponse, status_code=200)
async def generate_from_gaps(
    req: FromGapsRequest,
    session: AsyncSession = Depends(get_db),
    service: FlashcardService = Depends(get_flashcard_service),
) -> FromGapsResponse:
    """Generate one LLM-authored flashcard per knowledge gap (S97).

    Raises 422 when gaps is empty. Raises 503 when Ollama is unreachable.
    """
    try:
        created, _ = await service.generate_from_gaps(
            gaps=req.gaps,
            document_id=req.document_id,
            session=session,
        )
    except (
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.APIConnectionError,
        ConnectionRefusedError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unreachable. Start it with: ollama serve",
        ) from exc
    logger.info("generate_from_gaps: created %d cards", created)
    return FromGapsResponse(created=created)


def _cards_to_csv(cards: list[FlashcardModel], document_title: str) -> str:
    """Render flashcards as a CSV string.

    Pure function — no I/O. All inputs are explicit parameters.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["question", "answer", "source_excerpt", "document_title"])
    for card in cards:
        writer.writerow([card.question, card.answer, card.source_excerpt, document_title])
    return output.getvalue()


@router.get("/entity-pairs", response_model=EntityPairsResponse)
async def get_entity_pairs(document_id: str) -> EntityPairsResponse:
    """Return top entity pairs for a document from Kuzu (for preview before generation).

    Uses RELATED_TO edges ordered by confidence descending; falls back to CO_OCCURS
    when no RELATED_TO edges exist.
    """
    from app.services.graph import get_graph_service  # noqa: PLC0415

    graph = get_graph_service()
    raw_pairs = graph.get_related_entity_pairs_for_document(document_id, limit=10)

    if not raw_pairs:
        co_pairs = graph.get_co_occurring_pairs_for_document(document_id, limit=10)
        # CO_OCCURS weight is a raw co-occurrence count (1.0, 2.0, …), not a probability.
        # Normalise to [0.0, 1.0] so the frontend percentage display is meaningful.
        max_weight = max((w for _, _, w in co_pairs), default=1.0) or 1.0
        previews = [
            EntityPairPreview(
                name_a=a,
                name_b=b,
                relation_label="co-occurs",
                confidence=round(w / max_weight, 4),
            )
            for a, b, w in co_pairs
        ]
    else:
        previews = [
            EntityPairPreview(name_a=a, name_b=b, relation_label=label, confidence=conf)
            for a, b, label, conf in raw_pairs
        ]

    return EntityPairsResponse(pairs=previews)


@router.post("/generate-from-graph", response_model=list[FlashcardResponse], status_code=201)
async def generate_flashcards_from_graph(
    req: GenerateFromGraphRequest,
    session: AsyncSession = Depends(get_db),
    service: FlashcardService = Depends(get_flashcard_service),
) -> list[FlashcardResponse]:
    """Generate relationship-framing flashcards from Kuzu entity pairs. HTTP 201."""
    try:
        cards = await service.generate_from_graph(
            document_id=req.document_id,
            k=req.k,
            session=session,
        )
    except (
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.APIConnectionError,
        ConnectionRefusedError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Start it with: ollama serve",
        ) from exc
    logger.info(
        "Generated graph flashcards",
        extra={"document_id": req.document_id, "count": len(cards)},
    )
    return [_to_response(c) for c in cards]


@router.post("/generate-technical", response_model=list[FlashcardResponse], status_code=201)
async def generate_technical_flashcards(
    req: GenerateTechnicalRequest,
    session: AsyncSession = Depends(get_db),
    service: FlashcardService = Depends(get_flashcard_service),
) -> list[FlashcardResponse]:
    """Generate Bloom's-taxonomy-typed flashcards for technical documents. HTTP 201."""
    try:
        cards = await service.generate_technical(
            document_id=req.document_id,
            scope=req.scope,
            section_heading=req.section_heading,
            count=req.count,
            session=session,
        )
    except (
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.APIConnectionError,
        ConnectionRefusedError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Start it with: ollama serve",
        ) from exc
    logger.info(
        "Generated technical flashcards",
        extra={"document_id": req.document_id, "count": len(cards)},
    )
    return [_to_response(c) for c in cards]


class TraceFlashcardRequest(BaseModel):
    question: str  # typically the code block (front of card)
    answer: str    # correct output + diff explanation (back of card)
    source_excerpt: str
    document_id: str | None = None
    chunk_id: str | None = None


@router.post("/create-trace", response_model=FlashcardResponse, status_code=201)
async def create_trace_flashcard(
    req: TraceFlashcardRequest,
    session: AsyncSession = Depends(get_db),
) -> FlashcardResponse:
    """Create a 'trace' flashcard from a prediction error. No LLM required.

    Called when the user clicks 'Create flashcard from this mistake?' after a wrong
    prediction in the Predict-then-Run panel. Stores with source='prediction_error',
    flashcard_type='trace'.
    """
    now = datetime.now(UTC)
    card = FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=req.document_id,
        chunk_id=req.chunk_id,
        source="prediction_error",
        deck="default",
        question=req.question,
        answer=req.answer,
        source_excerpt=req.source_excerpt[:500],
        difficulty="medium",
        is_user_edited=False,
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        due_date=now,
        reps=0,
        lapses=0,
        created_at=now,
        flashcard_type="trace",
        bloom_level=None,
    )
    session.add(card)
    # S184: sync FTS index for trace flashcards
    await _sync_flashcard_fts(card, session)
    await session.commit()
    await session.refresh(card)
    logger.info("Created trace flashcard", extra={"card_id": card.id})
    return _to_response(card)


# ---------------------------------------------------------------------------
# S154: Cloze deletion flashcard generation
# NOTE: This route is registered BEFORE /{document_id} to prevent FastAPI
# from matching the literal segment "cloze" as a document_id wildcard.
# ---------------------------------------------------------------------------


@router.post("/cloze/{section_id}", response_model=list[FlashcardResponse], status_code=201)
async def generate_cloze_flashcards(
    section_id: str,
    count: int = Query(default=5, ge=1, le=20),
    session: AsyncSession = Depends(get_db),
    service: FlashcardService = Depends(get_flashcard_service),
) -> list[FlashcardResponse]:
    """Generate cloze deletion (fill-in-the-blank) flashcards for a section."""
    try:
        cards = await service.generate_cloze(
            section_id=section_id,
            count=count,
            session=session,
        )
    except (
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.APIConnectionError,
        ConnectionRefusedError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Start it with: ollama serve",
        ) from exc
    logger.info(
        "Generated cloze flashcards",
        extra={"section_id": section_id, "count": len(cards)},
    )
    return [_to_response(c) for c in cards]


# ---------------------------------------------------------------------------
# Bloom's taxonomy coverage audit (S153)
# NOTE: These routes are registered BEFORE /{document_id} to prevent FastAPI
# from matching the literal segment "audit" as a document_id wildcard.
# ---------------------------------------------------------------------------


@router.get("/audit/{document_id}", response_model=CoverageReportResponse)
async def get_audit(
    document_id: str,
    session: AsyncSession = Depends(get_db),
    audit_service: FlashcardAuditService = Depends(get_flashcard_audit_service),
) -> CoverageReportResponse:
    """Return a Bloom's taxonomy coverage report for a document's flashcard deck."""
    report = await audit_service.analyze_coverage(document_id, session)
    # Convert int keys to str for JSON serialisation (JSON object keys must be strings)
    by_bloom_level_str = {str(k): v for k, v in report["by_bloom_level"].items()}
    by_section_serialisable = {
        sid: {
            "section_heading": stat["section_heading"],
            "by_bloom_level": {str(k): v for k, v in stat["by_bloom_level"].items()},
            "has_level_3_plus": stat["has_level_3_plus"],
        }
        for sid, stat in report["by_section"].items()
    }
    return CoverageReportResponse(
        total_cards=report["total_cards"],
        by_bloom_level=by_bloom_level_str,
        by_section=by_section_serialisable,
        coverage_score=report["coverage_score"],
        gaps=list(report["gaps"]),
    )


@router.post("/audit/{document_id}/fill", response_model=FillGapsResponse)
async def fill_audit_gaps(
    document_id: str,
    session: AsyncSession = Depends(get_db),
    audit_service: FlashcardAuditService = Depends(get_flashcard_audit_service),
) -> FillGapsResponse:
    """Generate missing Bloom's level cards for all gap sections of a document."""
    try:
        report = await audit_service.analyze_coverage(document_id, session)
        created = await audit_service.fill_gaps(document_id, report["gaps"], session)
    except (
        litellm.ServiceUnavailableError,
        litellm.exceptions.APIConnectionError,
        ConnectionRefusedError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unreachable. Start it with: ollama serve",
        ) from exc
    return FillGapsResponse(created=created)


# ---------------------------------------------------------------------------
# Deck health report (S160)
# NOTE: These routes are registered BEFORE /{document_id} to prevent FastAPI
# from matching the literal segment "health" as a document_id wildcard.
# ---------------------------------------------------------------------------


@router.get("/health/{document_id}", response_model=DeckHealthReportResponse)
async def get_deck_health(
    document_id: str,
    session: AsyncSession = Depends(get_db),
    health_service: DeckHealthService = Depends(get_deck_health_service),
) -> DeckHealthReportResponse:
    """Return a deck health report for a document's flashcard deck (S160)."""
    report = await health_service.analyze(document_id, session)
    return DeckHealthReportResponse(**report)


@router.post("/health/{document_id}/archive-mastered", response_model=ArchiveMasteredResponse)
async def archive_mastered_cards(
    document_id: str,
    session: AsyncSession = Depends(get_db),
    health_service: DeckHealthService = Depends(get_deck_health_service),
) -> ArchiveMasteredResponse:
    """Archive all mastered cards (stability > 180) for a document (S160)."""
    archived = await health_service.archive_mastered(document_id, session)
    return ArchiveMasteredResponse(archived=archived)


@router.post(
    "/health/{document_id}/fill-uncovered",
    response_model=FillUncoveredResponse,
    status_code=202,
)
async def fill_uncovered_sections(
    document_id: str,
    req: FillUncoveredRequest,
    health_service: DeckHealthService = Depends(get_deck_health_service),
) -> FillUncoveredResponse:
    """Queue fire-and-forget card generation for uncovered sections (S160).

    Returns HTTP 202 immediately. Cards are generated in the background using
    a fresh DB session to avoid sharing the request-scope session with a
    background task (which FastAPI may close when the response is sent).
    """

    async def _run() -> None:
        from app.database import get_db as _get_db  # noqa: PLC0415

        async for db in _get_db():
            await health_service.generate_for_uncovered(document_id, req.section_ids, db)
            break

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return FillUncoveredResponse(queued=len(req.section_ids))


# ---------------------------------------------------------------------------
# Deck list (S169)
# NOTE: This route is registered BEFORE /{document_id} to prevent FastAPI
# from matching the literal segment "decks" as a document_id wildcard.
# ---------------------------------------------------------------------------


class DeckItem(BaseModel):
    deck: str
    source_type: str  # "document" | "collection" | "note"
    card_count: int
    document_id: str | None
    collection_id: str | None


@router.get("/decks", response_model=list[DeckItem])
async def list_flashcard_decks(
    session: AsyncSession = Depends(get_db),
) -> list[DeckItem]:
    """Return all distinct decks with card counts and source type (S169).

    source_type is derived by joining deck name against CollectionModel.name:
    - "collection" when the deck matches a CollectionModel.name
    - "document" when document_id is non-null (source='document')
    - "note" otherwise (tag-scoped or note_ids-scoped)
    """
    from sqlalchemy import func as sa_func  # noqa: PLC0415

    rows = (
        await session.execute(
            select(
                FlashcardModel.deck,
                FlashcardModel.source,
                sa_func.count().label("card_count"),
                sa_func.max(FlashcardModel.document_id).label("document_id"),
            )
            .group_by(FlashcardModel.deck)
        )
    ).all()

    # Fetch all collection names in one query
    coll_result = await session.execute(
        select(CollectionModel.id, CollectionModel.name)
    )
    name_to_id = {row[1]: row[0] for row in coll_result.all()}

    items: list[DeckItem] = []
    for deck, source, card_count, doc_id in rows:
        deck_str = deck or "default"
        if deck_str in name_to_id:
            source_type = "collection"
            collection_id: str | None = name_to_id[deck_str]
            document_id: str | None = None
        elif doc_id is not None or source == "document":
            source_type = "document"
            collection_id = None
            document_id = doc_id
        else:
            source_type = "note"
            collection_id = None
            document_id = None
        items.append(
            DeckItem(
                deck=deck_str,
                source_type=source_type,
                card_count=card_count,
                document_id=document_id,
                collection_id=collection_id,
            )
        )
    return items


@router.get("/{document_id}/export/csv")
async def export_flashcards_csv(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export all flashcards for a document as a CSV download."""
    doc_result = await session.execute(
        select(DocumentModel).where(DocumentModel.id == document_id)
    )
    doc = doc_result.scalar_one_or_none()
    document_title = doc.title if doc else ""

    card_result = await session.execute(
        select(FlashcardModel)
        .where(FlashcardModel.document_id == document_id)
        .order_by(FlashcardModel.created_at.desc())
    )
    cards = list(card_result.scalars().all())

    return StreamingResponse(
        iter([_cards_to_csv(cards, document_title)]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=flashcards.csv"},
    )


@router.get("/{document_id}", response_model=list[FlashcardResponse])
async def list_flashcards(
    document_id: str,
    section_id: str | None = Query(default=None),
    bloom_level_min: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[FlashcardResponse]:
    """List flashcards for a document ordered by created_at desc.

    Optional filters:
      section_id      -- only cards whose chunk belongs to this section
      bloom_level_min -- only cards with bloom_level >= this value (null bloom cards excluded)
    """
    if section_id is not None:
        # Join through ChunkModel to filter by section
        stmt = (
            select(FlashcardModel, ChunkModel.section_id)
            .join(ChunkModel, FlashcardModel.chunk_id == ChunkModel.id)
            .where(
                FlashcardModel.document_id == document_id,
                ChunkModel.section_id == section_id,
            )
        )
        if bloom_level_min is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level >= bloom_level_min,
            )
        stmt = stmt.order_by(FlashcardModel.created_at.desc())
        result = await session.execute(stmt)
        return [_to_response(row[0], section_id=row[1]) for row in result.all()]

    # No section filter — preserve existing no-join path
    stmt = (
        select(FlashcardModel)
        .where(FlashcardModel.document_id == document_id)
    )
    if bloom_level_min is not None:
        stmt = stmt.where(
            FlashcardModel.bloom_level.is_not(None),
            FlashcardModel.bloom_level >= bloom_level_min,
        )
    stmt = stmt.order_by(FlashcardModel.created_at.desc())
    result = await session.execute(stmt)
    cards = result.scalars().all()
    return [_to_response(c) for c in cards]


@router.put("/{card_id}", response_model=FlashcardResponse)
async def update_flashcard(
    card_id: str,
    req: FlashcardUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> FlashcardResponse:
    """Update a flashcard's question and/or answer. Sets is_user_edited=True."""
    result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.id == card_id)
    )
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    if req.question is not None:
        card.question = req.question
    if req.answer is not None:
        card.answer = req.answer
    card.is_user_edited = True

    # S184: keep FTS index in sync on question/answer edits
    await _sync_flashcard_fts(card, session)
    await session.commit()
    await session.refresh(card)
    logger.info("Updated flashcard", extra={"card_id": card_id})
    return _to_response(card)


@router.delete("/{card_id}", status_code=204)
async def delete_flashcard(
    card_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a flashcard by ID."""
    result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.id == card_id)
    )
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    # S184: remove from FTS index before deleting
    await _delete_flashcard_fts(card_id, session)
    await session.execute(delete(FlashcardModel).where(FlashcardModel.id == card_id))
    await session.commit()
    logger.info("Deleted flashcard", extra={"card_id": card_id})


@router.delete("/document/{document_id}", status_code=204)
async def delete_all_document_flashcards(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete all flashcards for a specific document."""
    await session.execute(
        delete(FlashcardModel)
        .where(FlashcardModel.id.isnot(None))
        .where(FlashcardModel.document_id == document_id)
    )
    await session.commit()
    logger.info("Deleted all flashcards for document", extra={"document_id": document_id})


@router.post("/{card_id}/review", response_model=FlashcardResponse)
async def review_flashcard(
    card_id: str,
    req: ReviewRequest,
    session: AsyncSession = Depends(get_db),
    service: FSRSService = Depends(get_fsrs_service),
) -> FlashcardResponse:
    """Submit an FSRS review rating for a flashcard. Optionally link to a study session."""
    try:
        card = await service.schedule(card_id, req.rating, session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if req.session_id:
        event = ReviewEventModel(
            id=str(uuid.uuid4()),
            session_id=req.session_id,
            flashcard_id=card_id,
            rating=req.rating,
            is_correct=req.rating != "again",
        )
        session.add(event)
        await session.commit()

    # Fire-and-forget coverage update -- does not block the review response.
    if card.document_id:
        from app.services.objective_tracker import get_objective_tracker_service  # noqa: PLC0415

        _tracker = get_objective_tracker_service()
        _task = asyncio.create_task(_tracker.update_coverage(card.document_id))
        _background_tasks.add(_task)
        _task.add_done_callback(_background_tasks.discard)

    logger.info("Reviewed flashcard", extra={"card_id": card_id, "rating": req.rating})
    return _to_response(card)


@router.get("/{card_id}/source-context", response_model=SourceContextResponse)
async def get_source_context(
    card_id: str,
    session: AsyncSession = Depends(get_db),
) -> SourceContextResponse:
    """Return source passage for a flashcard (for SourceContextPanel on Again/Hard).

    Join chain: FlashcardModel.chunk_id -> ChunkModel.section_id -> SectionModel -> DocumentModel.
    Returns 404 when:
      - flashcard not found
      - flashcard.chunk_id is null
      - ChunkModel.section_id is null (chunk not section-assigned)
      - SectionModel row not found for that section_id
    """
    fc_result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.id == card_id)
    )
    card = fc_result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")
    if card.chunk_id is None:
        raise HTTPException(status_code=404, detail="Flashcard has no source chunk")

    chunk_result = await session.execute(
        select(ChunkModel).where(ChunkModel.id == card.chunk_id)
    )
    chunk = chunk_result.scalar_one_or_none()
    if chunk is None or chunk.section_id is None:
        raise HTTPException(status_code=404, detail="No section found for this flashcard")

    sec_result = await session.execute(
        select(SectionModel).where(SectionModel.id == chunk.section_id)
    )
    section = sec_result.scalar_one_or_none()
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    doc_result = await session.execute(
        select(DocumentModel).where(DocumentModel.id == section.document_id)
    )
    doc = doc_result.scalar_one_or_none()
    document_title = doc.title if doc else ""

    preview = (section.preview or "")[:400]

    logger.info("source-context: card=%s section=%s", card_id, chunk.section_id)
    return SourceContextResponse(
        section_heading=section.heading,
        section_preview=preview,
        document_title=document_title,
        pdf_page_number=chunk.pdf_page_number,
        section_id=chunk.section_id,
        document_id=section.document_id,
    )
