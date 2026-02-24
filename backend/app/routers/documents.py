import asyncio
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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


class PatchDocumentRequest(BaseModel):
    title: str | None = None
    tags: list[str] | None = None


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


@router.get("", response_model=list[DocumentListItem])
async def list_documents():
    """Return all documents with derived fields (summary, flashcard_count, learning_status)."""
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
        ).order_by(DocumentModel.created_at.desc())

        result = await session.execute(stmt)
        rows = result.all()

    items = []
    for row in rows:
        doc = row[0]
        summary_one_sentence = row[1]
        flashcard_count = row[2] or 0
        summary_count = row[3] or 0
        study_session_count = row[4] or 0

        items.append(
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
    return items


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
    ext = Path(file.filename or "upload.txt").suffix.lstrip(".")
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

    # Kuzu graph cleanup — stub until S15a
    logger.info("Kuzu node cleanup pending (S15a) for document %s", document_id)

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
    }
