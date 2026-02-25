import asyncio
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text

from app.config import Settings, get_settings
from app.database import get_session_factory
from app.models import (
    ChunkModel,
    DocumentModel,
    FlashcardModel,
    MisconceptionModel,
    NoteModel,
    QAHistoryModel,
    SectionModel,
    StudySessionModel,
    SummaryModel,
)
from app.services.parser import DocumentParser
from app.services.vector_store import get_lancedb_service
from app.types import ParsedDocument, Section
from app.workflows.ingestion import STAGE_PROGRESS, run_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_parser = DocumentParser()

_ALLOWED_EXTENSIONS = frozenset({"pdf", "txt", "md", "markdown", "docx"})


# ---------------------------------------------------------------------------
# Pydantic response / request models
# ---------------------------------------------------------------------------


class DocumentListItem(BaseModel):
    id: str
    title: str
    format: str
    content_type: str
    word_count: int
    page_count: int
    stage: str
    tags: list[str]
    created_at: datetime
    last_accessed_at: datetime
    summary_one_sentence: str | None
    flashcard_count: int
    learning_status: Literal["not_started", "summarized", "flashcards_generated", "studied"]


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    total: int
    page: int
    page_size: int


class BulkDeleteRequest(BaseModel):
    ids: list[str]


class PatchTagsRequest(BaseModel):
    tags: list[str]


class PatchDocumentRequest(BaseModel):
    title: str | None = None
    tags: list[str] | None = None


class SectionItem(BaseModel):
    id: str
    heading: str
    level: int
    page_start: int
    page_end: int
    section_order: int
    preview: str


class DocumentDetail(BaseModel):
    id: str
    title: str
    format: str
    content_type: str
    word_count: int
    page_count: int
    stage: str
    tags: list[str]
    created_at: datetime
    last_accessed_at: datetime
    sections: list[SectionItem]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _section_to_dict(s: Section) -> dict:
    return {
        "heading": s.heading,
        "level": s.level,
        "text": s.text,
        "page_start": s.page_start,
        "page_end": s.page_end,
    }


def _parsed_to_dict(p: ParsedDocument) -> dict:
    return {
        "title": p.title,
        "format": p.format,
        "pages": p.pages,
        "word_count": p.word_count,
        "sections": [_section_to_dict(s) for s in p.sections],
        "raw_text": p.raw_text,
    }


def _derive_learning_status(
    study_session_count: int,
    flashcard_count: int,
    summary_count: int,
) -> str:
    if study_session_count > 0:
        return "studied"
    if flashcard_count > 0:
        return "flashcards_generated"
    if summary_count > 0:
        return "summarized"
    return "not_started"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


_LEARNING_STATUS_ORDER = {
    "studied": 3, "flashcards_generated": 2, "summarized": 1, "not_started": 0
}


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    content_type: str | None = Query(default=None, description="Comma-separated content types"),
    tag: str | None = Query(default=None, description="Filter by tag value"),
    sort: Literal["newest", "oldest", "alphabetical", "most-studied", "last_accessed"] = Query(
        default="newest"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DocumentListResponse:
    """Return paginated documents with optional filtering and sorting."""
    async with get_session_factory()() as session:
        # Correlated scalar subqueries for derived fields
        summary_one_sentence_sq = (
            select(SummaryModel.content)
            .where(
                SummaryModel.document_id == DocumentModel.id,
                SummaryModel.mode == "one_sentence",
            )
            .limit(1)
            .correlate(DocumentModel)
            .scalar_subquery()
        )
        flashcard_count_sq = (
            select(func.count())
            .where(FlashcardModel.document_id == DocumentModel.id)
            .correlate(DocumentModel)
            .scalar_subquery()
        )
        summary_count_sq = (
            select(func.count())
            .where(SummaryModel.document_id == DocumentModel.id)
            .correlate(DocumentModel)
            .scalar_subquery()
        )
        study_session_count_sq = (
            select(func.count())
            .where(StudySessionModel.document_id == DocumentModel.id)
            .correlate(DocumentModel)
            .scalar_subquery()
        )

        stmt = select(
            DocumentModel,
            summary_one_sentence_sq.label("summary_one_sentence"),
            flashcard_count_sq.label("flashcard_count"),
            summary_count_sq.label("summary_count"),
            study_session_count_sq.label("study_session_count"),
        )

        result = await session.execute(stmt)
        rows = result.all()

    # Build items
    all_items: list[DocumentListItem] = []
    for row in rows:
        doc = row[0]
        summary_one_sentence = row[1]
        flashcard_count = row[2] or 0
        summary_count = row[3] or 0
        study_session_count = row[4] or 0
        all_items.append(
            DocumentListItem(
                id=doc.id,
                title=doc.title,
                format=doc.format,
                content_type=doc.content_type,
                word_count=doc.word_count,
                page_count=doc.page_count,
                stage=doc.stage,
                tags=doc.tags or [],
                created_at=doc.created_at,
                last_accessed_at=doc.last_accessed_at,
                summary_one_sentence=summary_one_sentence,
                flashcard_count=flashcard_count,
                learning_status=_derive_learning_status(
                    study_session_count, flashcard_count, summary_count
                ),
            )
        )

    # Filter by content_type
    if content_type:
        allowed = {t.strip() for t in content_type.split(",") if t.strip()}
        all_items = [i for i in all_items if i.content_type in allowed]

    # Filter by tag
    if tag:
        all_items = [i for i in all_items if tag in i.tags]

    # Sort
    if sort == "newest":
        all_items.sort(key=lambda i: i.created_at, reverse=True)
    elif sort == "oldest":
        all_items.sort(key=lambda i: i.created_at)
    elif sort == "alphabetical":
        all_items.sort(key=lambda i: i.title.lower())
    elif sort == "most-studied":
        all_items.sort(key=lambda i: _LEARNING_STATUS_ORDER.get(i.learning_status, 0), reverse=True)
    elif sort == "last_accessed":
        all_items.sort(key=lambda i: i.last_accessed_at, reverse=True)

    total = len(all_items)
    start = (page - 1) * page_size
    page_items = all_items[start : start + page_size]

    return DocumentListResponse(items=page_items, total=total, page=page, page_size=page_size)


@router.post("/parse")
async def parse_document(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    doc_id = str(uuid.uuid4())
    ext = Path(file.filename or "upload.txt").suffix.lstrip(".")
    data_dir = Path(settings.DATA_DIR).expanduser()
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{doc_id}.{ext}"

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    fmt = ext if ext in ("pdf", "docx", "txt", "md", "markdown") else "txt"
    parsed = _parser.parse(dest, fmt)
    logger.info("Parsed document", extra={"doc_id": doc_id, "format": fmt})
    return {"document_id": doc_id, "parsed": _parsed_to_dict(parsed)}


@router.post("/ingest")
async def ingest_document(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    doc_id = str(uuid.uuid4())
    ext = Path(file.filename or "upload.txt").suffix.lstrip(".").lower()
    if ext and ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '.{ext}'. "
                f"Allowed types: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            ),
        )
    data_dir = Path(settings.DATA_DIR).expanduser()
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{doc_id}.{ext}"

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    fmt = ext if ext in ("pdf", "docx", "txt", "md", "markdown") else "txt"

    async with get_session_factory()() as session:
        doc = DocumentModel(
            id=doc_id,
            title=Path(file.filename or "upload").stem,
            format=fmt,
            content_type="notes",
            word_count=0,
            page_count=0,
            file_path=str(dest),
            stage="parsing",
        )
        session.add(doc)
        await session.commit()

    asyncio.create_task(run_ingestion(doc_id, str(dest), fmt))
    logger.info("Ingestion started", extra={"doc_id": doc_id})
    return {"document_id": doc_id, "status": "processing"}


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: str):
    """Return document detail with sections list."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")

        sections_result = await session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .order_by(SectionModel.section_order)
        )
        sections = sections_result.scalars().all()

    return DocumentDetail(
        id=doc.id,
        title=doc.title,
        format=doc.format,
        content_type=doc.content_type,
        word_count=doc.word_count,
        page_count=doc.page_count,
        stage=doc.stage,
        tags=doc.tags or [],
        created_at=doc.created_at,
        last_accessed_at=doc.last_accessed_at,
        sections=[
            SectionItem(
                id=s.id,
                heading=s.heading,
                level=s.level,
                page_start=s.page_start,
                page_end=s.page_end,
                section_order=s.section_order,
                preview=s.preview,
            )
            for s in sections
        ],
    )


@router.post("/bulk-delete", status_code=200)
async def bulk_delete_documents(body: BulkDeleteRequest):
    """Delete multiple documents and their derived data by ID list."""
    deleted = []
    for document_id in body.ids:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(DocumentModel).where(DocumentModel.id == document_id)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                continue
            await session.execute(
                text("DELETE FROM chunks_fts WHERE document_id = :doc_id"),
                {"doc_id": document_id},
            )
            for model in (
                ChunkModel,
                SectionModel,
                SummaryModel,
                FlashcardModel,
                MisconceptionModel,
                NoteModel,
                QAHistoryModel,
            ):
                await session.execute(
                    delete(model).where(model.document_id == document_id)  # type: ignore[attr-defined]
                )
            await session.execute(
                delete(StudySessionModel).where(StudySessionModel.document_id == document_id)
            )
            await session.delete(doc)
            await session.commit()
        try:
            get_lancedb_service().delete_document(document_id)
        except Exception:
            logger.warning("Failed to delete LanceDB vectors for document %s", document_id)
        try:
            from app.services.graph import get_graph_service  # noqa: PLC0415

            get_graph_service().delete_document(document_id)
        except Exception:
            logger.warning("Failed to delete Kuzu graph nodes for document %s", document_id)
        deleted.append(document_id)
    return {"deleted": deleted, "count": len(deleted)}


@router.patch("/{document_id}")
async def patch_document(document_id: str, body: PatchDocumentRequest):
    async with get_session_factory()() as session:
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if body.title is not None:
            doc.title = body.title
        if body.tags is not None:
            doc.tags = body.tags
        await session.commit()
    return {"document_id": document_id, "updated": True}


@router.patch("/{document_id}/tags")
async def patch_document_tags(document_id: str, body: PatchTagsRequest):
    """Replace the tag list for a document."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        doc.tags = body.tags
        await session.commit()
    return {"document_id": document_id, "tags": body.tags}


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str):
    async with get_session_factory()() as session:
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")

        # Delete child rows from all related tables (no FK CASCADE in SQLite without FK pragma)
        await session.execute(
            text("DELETE FROM chunks_fts WHERE document_id = :doc_id"),
            {"doc_id": document_id},
        )
        for model in (
            ChunkModel,
            SectionModel,
            SummaryModel,
            FlashcardModel,
            MisconceptionModel,
            NoteModel,
            QAHistoryModel,
        ):
            await session.execute(
                delete(model).where(model.document_id == document_id)  # type: ignore[attr-defined]
            )
        await session.execute(
            delete(StudySessionModel).where(StudySessionModel.document_id == document_id)
        )
        await session.delete(doc)
        await session.commit()

    # Remove vectors from LanceDB
    try:
        get_lancedb_service().delete_document(document_id)
    except Exception:
        logger.warning("Failed to delete LanceDB vectors for document %s", document_id)

    # Remove graph nodes and edges from Kuzu
    try:
        from app.services.graph import get_graph_service  # noqa: PLC0415

        get_graph_service().delete_document(document_id)
    except Exception:
        logger.warning("Failed to delete Kuzu graph nodes for document %s", document_id)

    logger.info("Deleted document %s", document_id)


@router.get("/{document_id}/status")
async def get_document_status(document_id: str):
    async with get_session_factory()() as session:
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    stage = doc.stage
    progress_pct = STAGE_PROGRESS.get(stage, 0)
    return {
        "document_id": document_id,
        "stage": stage,
        "progress_pct": progress_pct,
        "done": stage == "complete",
        "error_message": "Ingestion failed. Please try again." if stage == "error" else None,
    }
