import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select

from app.config import Settings, get_settings
from app.database import get_session_factory
from app.models import DocumentModel
from app.services.parser import DocumentParser
from app.types import ParsedDocument, Section
from app.workflows.ingestion import STAGE_PROGRESS, run_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_parser = DocumentParser()


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
