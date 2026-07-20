import asyncio
import hashlib
import logging
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import case, func, select, text

from app.config import Settings, get_settings
from app.database import get_session_factory
from app.models import (
    ChunkModel,
    CodeSnippetModel,
    CollectionMemberModel,
    DocumentModel,
    EnrichmentJobModel,
    FlashcardModel,
    LearningObjectiveModel,
    PredictionEventModel,
    ReadingPositionModel,
    ReadingProgressModel,
    SectionModel,
    StudySessionModel,
    SummaryModel,
)
from app.repos.collection_repo import CollectionRepo
from app.repos.document_repo import DocumentRepo
from app.schemas.documents import (
    AssignCollectionsRequest,
    BulkDeleteRequest,
    ChapterProgressItem,
    ChunkItem,
    CodeSnippetItem,
    DocumentDetail,
    DocumentDiagnostics,
    DocumentListItem,
    DocumentListResponse,
    DocumentOverviewResponse,
    DocumentProgressResponse,
    DocumentSectionSearchResult,
    EpubChapterResponse,
    EpubChapterTocItem,
    EpubTocResponse,
    KindleIngestResponse,
    LearningObjectiveItem,
    LearningObjectivesResponse,
    LearningObjectiveUpdate,
    PatchDocumentRequest,
    PatchTagsRequest,
    PDFMetaResponse,
    ReadingPositionResponse,
    SavePositionRequest,
    SectionItem,
    UrlIngestRequest,
    YouTubeIngestRequest,
)
from app.schemas.membership import CollectionRef
from app.services import graph as _graph_module  # indirect: get_graph_service is patched in tests

# indirect: tests patch `app.services.youtube_downloader.{check_ytdlp_available,
# check_ffmpeg_available, fetch_metadata, download_audio}`.
from app.services import youtube_downloader as _yt_module
from app.services.activity_service import ActivityService
from app.services.article_extractor import get_article_extractor
from app.services.document_deletion_service import get_document_deletion_service
from app.services.document_search import get_document_search_service
from app.services.document_tagger import enrich_document_tags, prune_auto_entity_tags
from app.services.documents_service import (
    delete_raw_file as _delete_raw_file,
)
from app.services.documents_service import (
    derive_learning_status as _derive_learning_status,
)
from app.services.documents_service import (
    parsed_to_dict as _parsed_to_dict,
)
from app.services.documents_service import (
    safe_tags as _safe_tags,
)
from app.services.documents_service import (
    section_to_dict as _section_to_dict,
)
from app.services.epub_service import (
    get_chapter_async,
    get_epub_service,
    get_toc_async,
)
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.naming import normalize_tag_slug
from app.services.notes_service import sync_document_tag_index
from app.services.objective_tracker import get_objective_tracker_service
from app.services.parser import DocumentParser
from app.services.repo_helpers import get_or_404
from app.services.summarizer import PREGENERATE_MODES
from app.services.vector_store import get_lancedb_service
from app.services.youtube_downloader import is_youtube_url
from app.workflows import ingestion as _ingestion_module  # indirect: _run_pregenerate is patched
from app.workflows.ingestion import (
    STAGE_PROGRESS,
    ContentType,
    _background_tasks,
    run_ingestion,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_parser = DocumentParser()

_ALLOWED_EXTENSIONS = frozenset(
    {"pdf", "txt", "md", "markdown", "docx", "mp3", "m4a", "wav", "mp4", "epub"}
)


# Back-compat re-exports for tests and routers/study.py that import these
# private aliases from this module.
__all__ = [
    "BulkDeleteRequest",
    "ChapterProgressItem",
    "ChunkItem",
    "CodeSnippetItem",
    "DocumentDetail",
    "DocumentDiagnostics",
    "DocumentListItem",
    "DocumentListResponse",
    "DocumentProgressResponse",
    "DocumentSectionSearchResult",
    "EpubChapterResponse",
    "EpubChapterTocItem",
    "EpubTocResponse",
    "KindleIngestResponse",
    "LearningObjectiveItem",
    "LearningObjectivesResponse",
    "PDFMetaResponse",
    "PatchDocumentRequest",
    "PatchTagsRequest",
    "ReadingPositionResponse",
    "SavePositionRequest",
    "SectionItem",
    "UrlIngestRequest",
    "YouTubeIngestRequest",
    "_delete_raw_file",
    "_derive_learning_status",
    "_parsed_to_dict",
    "_safe_tags",
    "_section_to_dict",
    "router",
]


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    content_type: str | None = Query(default=None, description="Comma-separated content types"),
    tag: str | None = Query(default=None, description="Filter by tag value"),
    collection_id: str | None = Query(
        default=None, description="Restrict to documents in this collection"
    ),
    sort: Literal[
        "newest", "oldest", "alphabetical", "most-studied", "last_accessed", "weakest-first"
    ] = Query(
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
        chunk_count_sq = (
            select(func.count())
            .where(ChunkModel.document_id == DocumentModel.id)
            .correlate(DocumentModel)
            .scalar_subquery()
        )
        section_count_sq = (
            select(func.count())
            .where(SectionModel.document_id == DocumentModel.id)
            .correlate(DocumentModel)
            .scalar_subquery()
        )
        read_section_count_sq = (
            select(func.count())
            .where(ReadingProgressModel.document_id == DocumentModel.id)
            .correlate(DocumentModel)
            .scalar_subquery()
        )
        enrichment_status_sq = (
            select(EnrichmentJobModel.status)
            .where(EnrichmentJobModel.document_id == DocumentModel.id)
            .order_by(
                # Prioritize image-related jobs for the status display
                case(
                    (EnrichmentJobModel.job_type == "image_analyze", 1),
                    (EnrichmentJobModel.job_type == "image_extract", 2),
                    else_=3,
                ),
                EnrichmentJobModel.created_at.desc(),
            )
            .limit(1)
            .correlate(DocumentModel)
            .scalar_subquery()
        )
        objectives_total_sq = (
            select(func.count())
            .where(LearningObjectiveModel.document_id == DocumentModel.id)
            .correlate(DocumentModel)
            .scalar_subquery()
        )
        objectives_covered_sq = (
            select(func.count())
            .where(
                LearningObjectiveModel.document_id == DocumentModel.id,
                LearningObjectiveModel.covered.is_(True),
            )
            .correlate(DocumentModel)
            .scalar_subquery()
        )

        # Mastery aggregate: weighted FSRS-stability mean, minus prediction-error penalty.
        # Mirrors MasteryService._compute_weighted_mastery; clamps each card's stability
        # at _MASTERY_FULL_DAYS (21) and applies bloom_level>=4 weight of 1.5.
        _bloom_weight = case((FlashcardModel.bloom_level >= 4, 1.5), else_=1.0)
        _capped_stability = func.min(FlashcardModel.fsrs_stability / 21.0, 1.0)
        mastery_sum_contribution_sq = (
            select(func.sum(_capped_stability * _bloom_weight))
            .where(FlashcardModel.document_id == DocumentModel.id)
            .correlate(DocumentModel)
            .scalar_subquery()
        )
        mastery_sum_weight_sq = (
            select(func.sum(_bloom_weight))
            .where(FlashcardModel.document_id == DocumentModel.id)
            .correlate(DocumentModel)
            .scalar_subquery()
        )
        prediction_error_count_sq = (
            select(func.count())
            .where(
                PredictionEventModel.document_id == DocumentModel.id,
                PredictionEventModel.correct.is_(False),
            )
            .correlate(DocumentModel)
            .scalar_subquery()
        )

        # Build WHERE filters pushed into SQL.
        where_clauses = []
        if content_type:
            allowed = [t.strip() for t in content_type.split(",") if t.strip()]
            if allowed:
                where_clauses.append(DocumentModel.content_type.in_(allowed))
        if tag:
            # Prefix match via the shadow index, matching the note tag filter
            # semantics: ?tag=science also matches docs tagged 'science/biology'.
            from sqlalchemy import or_

            from app.models import DocumentTagIndexModel as _DocTagIdx

            where_clauses.append(
                select(_DocTagIdx.document_id)
                .where(
                    _DocTagIdx.document_id == DocumentModel.id,
                    or_(
                        _DocTagIdx.tag_full == tag,
                        _DocTagIdx.tag_full.like(f"{tag}/%"),
                    ),
                )
                .exists()
            )
        if collection_id:
            where_clauses.append(
                select(CollectionMemberModel.id)
                .where(
                    CollectionMemberModel.collection_id == collection_id,
                    CollectionMemberModel.member_id == DocumentModel.id,
                    CollectionMemberModel.member_type == "document",
                )
                .exists()
            )

        # Total count under the same filters.
        count_stmt = select(func.count()).select_from(DocumentModel)
        for clause in where_clauses:
            count_stmt = count_stmt.where(clause)
        total = int((await session.execute(count_stmt)).scalar_one())

        # learning_status sort key, derived in SQL from the count subqueries.
        learning_status_order_sq = case(
            (study_session_count_sq > 0, 3),
            (flashcard_count_sq > 0, 2),
            (summary_count_sq > 0, 1),
            else_=0,
        )

        if sort == "newest":
            order_clauses = [DocumentModel.created_at.desc()]
        elif sort == "oldest":
            order_clauses = [DocumentModel.created_at.asc()]
        elif sort == "alphabetical":
            order_clauses = [func.lower(DocumentModel.title).asc()]
        elif sort == "last_accessed":
            order_clauses = [DocumentModel.last_accessed_at.desc()]
        elif sort == "weakest-first":
            # Docs with cards sorted ascending by mastery (nulls/no-cards last).
            # mastery_sum_weight==0 means no cards; treat as highest mastery so
            # they sink to the bottom and don't crowd out real weak docs.
            order_clauses = [
                case((mastery_sum_weight_sq > 0, 0), else_=1).asc(),
                (mastery_sum_contribution_sq / mastery_sum_weight_sq).asc(),
                DocumentModel.created_at.desc(),
            ]
        else:  # most-studied
            order_clauses = [learning_status_order_sq.desc(), DocumentModel.created_at.desc()]

        stmt = select(
            DocumentModel,
            summary_one_sentence_sq.label("summary_one_sentence"),
            flashcard_count_sq.label("flashcard_count"),
            summary_count_sq.label("summary_count"),
            study_session_count_sq.label("study_session_count"),
            chunk_count_sq.label("chunk_count"),
            section_count_sq.label("section_count"),
            read_section_count_sq.label("read_section_count"),
            enrichment_status_sq.label("enrichment_status"),
            objectives_total_sq.label("objectives_total"),
            objectives_covered_sq.label("objectives_covered"),
            mastery_sum_contribution_sq.label("mastery_sum_contribution"),
            mastery_sum_weight_sq.label("mastery_sum_weight"),
            prediction_error_count_sq.label("prediction_error_count"),
        )
        for clause in where_clauses:
            stmt = stmt.where(clause)
        stmt = stmt.order_by(*order_clauses).limit(page_size).offset((page - 1) * page_size)

        result = await session.execute(stmt)
        rows = result.all()

        # Batch-fetch collection memberships for the current page so
        # DocumentCard can render membership chips without per-card fetches
        # (plan 2E.5). The id list is only known after the page query runs.
        page_doc_ids = [row[0].id for row in rows]
        collection_refs_by_doc = await CollectionRepo(session).refs_for_members(
            page_doc_ids, member_type="document"
        )

    page_items: list[DocumentListItem] = []
    for row in rows:
        doc = row[0]
        summary_one_sentence = row[1]
        flashcard_count = row[2] or 0
        summary_count = row[3] or 0
        study_session_count = row[4] or 0
        chunk_count = row[5] or 0
        section_count = row[6] or 0
        read_section_count = row[7] or 0
        enrichment_status = row[8]
        objectives_total = row[9] or 0
        objectives_covered = row[10] or 0
        mastery_sum_contribution = row[11]
        mastery_sum_weight = row[12]
        prediction_error_count = row[13] or 0
        reading_progress_pct = (read_section_count / section_count) if section_count > 0 else 0.0
        objective_progress_pct: float | None = None
        if objectives_total > 0:
            objective_progress_pct = round(objectives_covered / objectives_total * 100.0, 1)
        mastery_pct: float | None = None
        if mastery_sum_weight and mastery_sum_weight > 0:
            weighted_mean = float(mastery_sum_contribution or 0.0) / float(mastery_sum_weight)
            penalty = min(prediction_error_count * 0.05, 0.20)
            mastery_pct = round(max(0.0, weighted_mean - penalty) * 100.0, 1)
        page_items.append(
            DocumentListItem(
                id=doc.id,
                title=doc.title,
                format=doc.format,
                content_type=doc.content_type,
                word_count=doc.word_count,
                page_count=doc.page_count,
                stage=doc.stage,
                tags=_safe_tags(doc.tags),
                created_at=doc.created_at,
                last_accessed_at=doc.last_accessed_at,
                summary_one_sentence=summary_one_sentence,
                flashcard_count=flashcard_count,
                learning_status=_derive_learning_status(
                    study_session_count, flashcard_count, summary_count
                ),
                chapter_count=doc.chapter_count,
                chunk_count=chunk_count,
                reading_progress_pct=reading_progress_pct,
                audio_duration_seconds=doc.audio_duration_seconds,
                source_url=doc.source_url,
                video_title=doc.video_title,
                channel_name=doc.channel_name,
                youtube_url=doc.youtube_url,
                enrichment_status=enrichment_status,
                objective_progress_pct=objective_progress_pct,
                mastery_pct=mastery_pct,
                collections=[
                    CollectionRef(id=cid, name=name, color=color)
                    for cid, name, color in collection_refs_by_doc.get(doc.id, [])
                ],
            )
        )

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
    content_type: ContentType = Form(...),
    settings: Settings = Depends(get_settings),
):
    ext = Path(file.filename or "upload.txt").suffix.lstrip(".").lower()
    if ext and ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '.{ext}'. "
                f"Allowed types: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            ),
        )

    # Read file content into memory so we can hash it and write it to disk.
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    _text_fmts = ("pdf", "docx", "txt", "md", "markdown", "mp3", "m4a", "wav", "mp4", "epub")
    fmt = ext if ext in _text_fmts else "txt"

    async with get_session_factory()() as session:
        # Deduplication: look for an existing document with the same file hash.
        existing = await DocumentRepo(session).find_by_file_hash(file_hash)

        if existing is not None:
            if existing.stage == "complete":
                # Identical file already fully ingested — return it as-is.
                # But backfill any missing pre-generated summaries in the background
                # (handles docs ingested before summarization was added, or where the
                # background task was GC'd before completing all modes).

                async with get_session_factory()() as _s:
                    existing_modes = set(
                        row[0]
                        for row in (
                            await _s.execute(
                                select(SummaryModel.mode).where(
                                    SummaryModel.document_id == existing.id
                                )
                            )
                        ).all()
                    )
                missing = [m for m in PREGENERATE_MODES if m not in existing_modes]
                if missing:

                    task = asyncio.create_task(_ingestion_module._run_pregenerate(existing.id))
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard)
                    logger.info(
                        "Backfilling missing summaries for complete doc",
                        extra={"doc_id": existing.id, "missing_modes": missing},
                    )
                else:
                    logger.info(
                        "Duplicate upload detected (stage=complete), returning existing doc",
                        extra={"doc_id": existing.id, "file_hash": file_hash},
                    )
                return {"document_id": existing.id, "status": "processing"}

            if existing.stage == "error":
                # Previous attempt failed — reset stage and retry ingestion on
                # the same document record so no duplicate row is created.
                existing.stage = "parsing"
                existing.content_type = content_type
                # commit stage reset before the background job polls document.stage
                await session.commit()
                get_ingestion_jobs().launch(
                    existing.id,
                    run_ingestion(existing.id, existing.file_path, existing.format, content_type),
                )
                logger.info(
                    "Retrying failed ingestion on existing doc",
                    extra={"doc_id": existing.id, "file_hash": file_hash},
                )
                return {"document_id": existing.id, "status": "processing"}

            # Stage is in-progress (parsing/chunking/embedding) — already running.
            logger.info(
                "Duplicate upload detected (stage=%s), returning in-progress doc",
                existing.stage,
                extra={"doc_id": existing.id},
            )
            return {"document_id": existing.id, "status": "processing"}

        # New file — write to disk and create a fresh document record.
        doc_id = str(uuid.uuid4())
        data_dir = Path(settings.DATA_DIR).expanduser()
        raw_dir = data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        dest = raw_dir / f"{doc_id}.{ext}"

        dest.write_bytes(content)

        logger.info(
            "File received",
            extra={
                "upload_filename": file.filename or "upload",
                "size_bytes": len(content),
                "format": fmt,
                "doc_id": doc_id,
            },
        )

        doc = DocumentModel(
            id=doc_id,
            title=Path(file.filename or "upload").stem,
            format=fmt,
            content_type=content_type,
            word_count=0,
            page_count=0,
            file_path=str(dest),
            file_hash=file_hash,
            stage="parsing",
        )
        # Document row must exist in SQLite before the background ingestion job starts;
        # the job uses document_id as its primary key.
        session.add(doc)
        await session.commit()

    get_ingestion_jobs().launch(
        doc_id, run_ingestion(doc_id, str(dest), fmt, content_type)
    )
    logger.info("Ingestion started", extra={"doc_id": doc_id})
    return {"document_id": doc_id, "status": "processing"}


@router.post("/ingest-kindle", response_model=KindleIngestResponse)
async def ingest_kindle(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    """Ingest a Kindle My Clippings.txt file.

    Parses highlights grouped by book title and creates one document per book.
    Each created document is tagged with 'kindle' and uses content_type='kindle_clippings'.
    """
    filename = file.filename or "My Clippings.txt"
    if not re.search(r"clippings", filename, re.IGNORECASE):
        # Also accept any .txt file — the user may have renamed it
        ext = Path(filename).suffix.lstrip(".").lower()
        if ext != "txt":
            raise HTTPException(
                status_code=400,
                detail="File must be a Kindle My Clippings.txt export (a plain text file).",
            )

    content_bytes = await file.read()
    text = content_bytes.decode("utf-8", errors="replace")

    documents = _parser.parse_kindle_clippings(text)
    if not documents:
        raise HTTPException(
            status_code=422,
            detail=(
                "No Kindle highlights found. Make sure you uploaded a valid My Clippings.txt file."
            ),
        )

    data_dir = Path(settings.DATA_DIR).expanduser()
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    document_ids: list[str] = []
    for parsed_doc in documents:
        doc_id = str(uuid.uuid4())
        # Write each book's highlights as a plain text file
        dest = raw_dir / f"{doc_id}.txt"
        dest.write_text(parsed_doc.raw_text, encoding="utf-8")

        async with get_session_factory()() as session:
            doc = DocumentModel(
                id=doc_id,
                title=parsed_doc.title,
                format="txt",
                content_type="kindle_clippings",
                word_count=parsed_doc.word_count,
                page_count=0,
                file_path=str(dest),
                file_hash=None,  # No hash — derived from a multi-book file
                stage="parsing",
                tags=["kindle"],
            )
            # Document row must exist in SQLite before the background ingestion job starts.
            session.add(doc)
            await session.flush()
            await sync_document_tag_index(
                doc_id, doc.tags, session, record_manual_provenance=True
            )
            await session.commit()

        get_ingestion_jobs().launch(
            doc_id, run_ingestion(doc_id, str(dest), "txt", "kindle_clippings")
        )
        document_ids.append(doc_id)
        logger.info(
            "Kindle book ingestion started",
            extra={"doc_id": doc_id, "title": parsed_doc.title},
        )

    logger.info(
        "Kindle ingestion started: %d books from %s",
        len(document_ids),
        filename,
    )
    return KindleIngestResponse(document_ids=document_ids, book_count=len(document_ids))


@router.post("/ingest-url")
async def ingest_url(
    body: UrlIngestRequest,
    settings: Settings = Depends(get_settings),
):
    """Ingest a YouTube URL (yt-dlp) or a general web article (Trafilatura)."""

    # 1. Non-YouTube: Ingest as a web article using ArticleExtractor
    if not is_youtube_url(body.url):

        doc_id = str(uuid.uuid4())
        try:
            extractor = get_article_extractor()
            parsed = await extractor.extract(body.url, doc_id=doc_id)
        except Exception as exc:
            logger.error("Article extraction failed for %s: %s", body.url, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        data_dir = Path(settings.DATA_DIR).expanduser()
        raw_dir = data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        dest = raw_dir / f"{doc_id}.md"
        dest.write_text(parsed.raw_text, encoding="utf-8")

        async with get_session_factory()() as session:
            doc = DocumentModel(
                id=doc_id,
                title=parsed.title,
                format="md",
                content_type="tech_article",
                word_count=parsed.word_count,
                page_count=1,
                file_path=str(dest),
                file_hash=None,
                stage="parsing",
                source_url=body.url,
            )
            # Document row must exist in SQLite before the background ingestion job starts.
            session.add(doc)
            await session.commit()

        # Convert Section objects to dicts for JSON serialization
        parsed_sections = [
            {
                "heading": s.heading,
                "level": s.level,
                "text": s.text,
                "page_start": s.page_start,
                "page_end": s.page_end,
            }
            for s in parsed.sections
        ]

        get_ingestion_jobs().launch(
            doc_id,
            run_ingestion(
                doc_id,
                str(dest),
                "md",
                "tech_article",
                parsed_document={
                    "title": parsed.title,
                    "format": "md",
                    "pages": 1,
                    "word_count": parsed.word_count,
                    "sections": parsed_sections,
                    "raw_text": parsed.raw_text,
                },
            ),
        )
        logger.info("Article ingestion started", extra={"doc_id": doc_id, "url": body.url})
        return {"document_id": doc_id, "status": "processing"}

    # 2. YouTube: Existing logic
    if not _yt_module.check_ytdlp_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "yt-dlp is not installed. Install it with: "
                "uv tool install yt-dlp  or  brew install yt-dlp"
            ),
        )

    if not _yt_module.check_ffmpeg_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "ffmpeg is not installed. Install it with: "
                "brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
            ),
        )

    try:
        meta = await _yt_module.fetch_metadata(body.url)
    except RuntimeError as exc:
        logger.warning("yt-dlp metadata fetch failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    video_title = meta.get("title") or "YouTube Video"
    channel_name = meta.get("uploader") or meta.get("channel") or None
    doc_id = str(uuid.uuid4())

    data_dir = Path(settings.DATA_DIR).expanduser()
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest_stem = raw_dir / doc_id  # yt-dlp appends .wav

    try:
        await _yt_module.download_audio(body.url, dest_stem)
    except RuntimeError as exc:
        logger.error("yt-dlp download failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Audio download failed: {exc}",
        ) from exc

    dest = dest_stem.with_suffix(".wav")
    if not dest.exists():
        raise HTTPException(status_code=500, detail="Downloaded audio file not found")

    async with get_session_factory()() as session:
        doc = DocumentModel(
            id=doc_id,
            title=video_title,
            format="wav",
            content_type="audio",
            word_count=0,
            page_count=0,
            file_path=str(dest),
            file_hash=None,
            stage="parsing",
            source_url=body.url,
            video_title=video_title,
            channel_name=channel_name,
            youtube_url=body.url,
        )
        # Document row must exist in SQLite before the background ingestion job starts.
        session.add(doc)
        await session.commit()

    get_ingestion_jobs().launch(
        doc_id, run_ingestion(doc_id, str(dest), "wav", "audio", parsed_document=None)
    )
    logger.info("YouTube ingestion started", extra={"doc_id": doc_id, "url": body.url})
    return {"document_id": doc_id, "status": "processing"}


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: str):
    """Return document detail with sections list."""
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        doc = await repo.get_or_404(document_id)
        sections = list(await repo.sections_for_document(document_id))
        read_count = await repo.read_section_count(document_id)

    section_count = len(sections)
    reading_progress_pct = (read_count / section_count) if section_count > 0 else 0.0

    return DocumentDetail(
        id=doc.id,
        title=doc.title,
        format=doc.format,
        content_type=doc.content_type,
        word_count=doc.word_count,
        page_count=doc.page_count,
        stage=doc.stage,
        tags=_safe_tags(doc.tags),
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
                admonition_type=s.admonition_type,
                parent_section_id=s.parent_section_id,
            )
            for s in sections
        ],
        reading_progress_pct=reading_progress_pct,
        audio_duration_seconds=doc.audio_duration_seconds,
        source_url=doc.source_url,
        video_title=doc.video_title,
        channel_name=doc.channel_name,
        youtube_url=doc.youtube_url,
    )


@router.get("/{document_id}/overview", response_model=DocumentOverviewResponse)
async def get_document_overview(document_id: str) -> DocumentOverviewResponse:
    """Read-aggregation for the Doc overview page (docs/02-ingest-and-doc-overview.md).

    Header + collection memberships + tags + reading progress. Study TOPICS (chapters) and
    References are separate frontend calls; the studyable list lives in the Study tab.
    """
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        doc = await repo.get_or_404(document_id)
        sections = list(await repo.sections_for_document(document_id))
        read_count = await repo.read_section_count(document_id)
        coll_map = await CollectionRepo(session).refs_for_members(
            [document_id], member_type="document"
        )

    section_count = len(sections)
    reading_progress_pct = (read_count / section_count) if section_count > 0 else 0.0

    return DocumentOverviewResponse(
        id=doc.id,
        title=doc.title,
        format=doc.format,
        content_type=doc.content_type,
        tags=_safe_tags(doc.tags),
        reading_progress_pct=reading_progress_pct,
        collections=[
            CollectionRef(id=cid, name=name, color=color)
            for cid, name, color in coll_map.get(document_id, [])
        ],
    )


@router.post("/{document_id}/collections", response_model=list[CollectionRef], status_code=201)
async def assign_document_collections(
    document_id: str, req: AssignCollectionsRequest
) -> list[CollectionRef]:
    """Add a document to one or more collections (ingest + after) and return the
    document's resulting collection set. Idempotent (INSERT OR IGNORE; no duplicates)."""
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        await repo.get_or_404(document_id)  # 404 if unknown
        coll_repo = CollectionRepo(session)
        for cid in dict.fromkeys(req.collection_ids):
            await coll_repo.add_members(cid, [document_id], member_type="document")
        refs = await coll_repo.refs_for_members([document_id], member_type="document")
    return [
        CollectionRef(id=cid, name=name, color=color)
        for cid, name, color in refs.get(document_id, [])
    ]


@router.get("/{document_id}/chunks", response_model=list[ChunkItem])
async def get_document_chunks(document_id: str) -> list[ChunkItem]:
    """Return all chunks for a document in chunk_index order.

    Works for any document type -- no format filter applied.
    Used by the YouTube transcript viewer and any other chunk-level consumer.
    """
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        await repo.get_or_404(document_id)
        chunks = list(await repo.chunks_for_document(document_id))

    return [
        ChunkItem(
            id=c.id,
            chunk_index=c.chunk_index,
            text=c.text,
            section_id=c.section_id,
            speaker=c.speaker,
            start_time=None,  # ChunkModel has no start_time; reserved for future use
        )
        for c in chunks
    ]


@router.get("/{document_id}/audio")
async def serve_audio_file(document_id: str) -> FileResponse:
    """Stream the raw audio file for audio documents (used by the mini-player)."""
    async with get_session_factory()() as session:
        doc = await get_or_404(session, DocumentModel, document_id, name="Document")
    if doc.content_type != "audio":
        raise HTTPException(status_code=400, detail="Not an audio document")
    fp = Path(doc.file_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")
    ext = fp.suffix.lower().lstrip(".")
    mime_map = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav"}
    mime = mime_map.get(ext, "audio/mpeg")
    return FileResponse(str(fp), media_type=mime)


@router.get("/{document_id}/video")
async def serve_video_file(document_id: str) -> FileResponse:
    """Stream the raw video file for video documents (used by the HTML5 video player)."""
    async with get_session_factory()() as session:
        doc = await get_or_404(session, DocumentModel, document_id, name="Document")
    if doc.content_type != "video":
        raise HTTPException(status_code=400, detail="Not a video document")
    fp = Path(doc.file_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")
    return FileResponse(str(fp), media_type="video/mp4")


@router.get("/{document_id}/file")
async def serve_document_file(document_id: str) -> FileResponse:
    """Serve the raw uploaded file for a document.

    Used by the PDF.js viewer to stream PDF bytes.
    Returns 404 if the document does not exist or the file is not found on disk.
    Returns the file with the appropriate Content-Type based on document format.
    """
    async with get_session_factory()() as session:
        doc = await get_or_404(session, DocumentModel, document_id, name="Document")
    fp = Path(doc.file_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="Document file not found on disk")
    mime_map = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
        "md": "text/markdown",
        "epub": "application/epub+zip",
    }
    mime = mime_map.get(doc.format.lower(), "application/octet-stream")
    return FileResponse(str(fp), media_type=mime)


@router.get("/{document_id}/pdf-meta", response_model=PDFMetaResponse)
async def get_pdf_meta(document_id: str) -> PDFMetaResponse:
    """Return PDF metadata: page count and whether a TOC (sections) exists.

    Returns 404 if document not found.
    Returns 400 if the document is not a PDF (format != 'pdf').
    """
    async with get_session_factory()() as session:
        doc = await get_or_404(session, DocumentModel, document_id, name="Document")
        if doc.format.lower() != "pdf":
            raise HTTPException(
                status_code=400,
                detail=f"Document is not a PDF (format={doc.format})",
            )
        # Shares session with the get_or_404 check above; single-table count.
        section_count_result = await session.execute(
            select(func.count(SectionModel.id)).where(SectionModel.document_id == document_id)
        )
        section_count = section_count_result.scalar_one() or 0

    return PDFMetaResponse(
        page_count=doc.page_count,
        has_toc=section_count > 0,
    )


# EPUB chapter viewer endpoints


@router.get("/{document_id}/epub/toc", response_model=EpubTocResponse)
async def get_epub_toc(document_id: str) -> EpubTocResponse:
    """Return the chapter table-of-contents for an EPUB document.

    Returns 404 if the document does not exist.
    Returns 400 if the document is not an EPUB (format != 'epub').
    Returns 404 if the raw EPUB file is not found on disk.
    """

    async with get_session_factory()() as session:
        doc = await get_or_404(session, DocumentModel, document_id, name="Document")
    if doc.format.lower() != "epub":
        raise HTTPException(
            status_code=400,
            detail=f"Document is not an EPUB (format={doc.format})",
        )
    fp = Path(doc.file_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="EPUB file not found on disk")

    try:
        chapters = await get_toc_async(str(fp))
    except Exception as exc:
        logger.error("EPUB TOC extraction failed for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read EPUB table of contents: {exc}",
        ) from exc

    return EpubTocResponse(
        document_id=document_id,
        chapters=[EpubChapterTocItem(**ch) for ch in chapters],
    )


@router.get("/{document_id}/epub/chapter/{chapter_index}", response_model=EpubChapterResponse)
async def get_epub_chapter(document_id: str, chapter_index: int) -> EpubChapterResponse:
    """Return sanitized HTML for a single EPUB chapter.

    Returns 404 if the document does not exist or file is missing.
    Returns 400 if the document is not an EPUB.
    Returns 404 if chapter_index is out of range.
    """

    if chapter_index < 0:
        raise HTTPException(status_code=400, detail="chapter_index must be >= 0")

    async with get_session_factory()() as session:
        doc = await get_or_404(session, DocumentModel, document_id, name="Document")
        if doc.format.lower() != "epub":
            raise HTTPException(
                status_code=400,
                detail=f"Document is not an EPUB (format={doc.format})",
            )
        fp = Path(doc.file_path)
        if not fp.exists():
            raise HTTPException(status_code=404, detail="EPUB file not found on disk")

        # Section IDs needed to map chapter index to section IDs; shares session with
        # the get_or_404 check above.
        sections_result = await session.execute(
            select(SectionModel.id)
            .where(SectionModel.document_id == document_id)
            .order_by(SectionModel.section_order)
        )
        all_section_ids = [row[0] for row in sections_result.all()]

    # Compute total chapters first (needed to slice sections)
    try:
        toc = await get_toc_async(str(fp))
        total_chapters = len(toc)
    except Exception:
        total_chapters = max(1, len(all_section_ids))

    section_ids = get_epub_service().compute_chapter_section_ids(
        all_section_ids, chapter_index, total_chapters
    )

    try:
        chapter = await get_chapter_async(str(fp), chapter_index, section_ids)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("EPUB chapter %d render failed for %s: %s", chapter_index, document_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to render chapter {chapter_index}: {exc}",
        ) from exc

    return EpubChapterResponse(
        chapter_index=chapter_index,
        chapter_title=chapter["chapter_title"],
        html=chapter["html"],
        word_count=chapter["word_count"],
        section_ids=chapter["section_ids"],
    )


@router.post("/bulk-delete", status_code=200)
async def bulk_delete_documents(body: BulkDeleteRequest):
    """Delete multiple documents and their derived data by ID list."""
    svc = get_document_deletion_service()
    deleted = []
    for document_id in body.ids:
        async with get_session_factory()() as session:
            # Existence check + cascade delete share one session per document;
            # delete_sqlite_cascade uses the session directly for multi-table cleanup.
            result = await session.execute(
                select(DocumentModel).where(DocumentModel.id == document_id)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                continue
            await svc.delete_sqlite_cascade(session, doc)
            await session.commit()
        svc.delete_lancedb_vectors(document_id)
        svc.delete_kuzu_nodes(document_id)
        svc.delete_filesystem_assets(document_id)
        deleted.append(document_id)
    logger.info("Bulk deleted documents", extra={"count": len(deleted)})
    return {"deleted": deleted, "count": len(deleted)}


@router.patch("/{document_id}")
async def patch_document(document_id: str, body: PatchDocumentRequest):
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        doc = await repo.get_or_404(document_id)
        if body.title is not None:
            doc.title = body.title
        if body.tags is not None:

            doc.tags = [normalize_tag_slug(t) for t in body.tags if normalize_tag_slug(t)]
            await sync_document_tag_index(
                document_id, doc.tags, session, record_manual_provenance=True
            )
        if body.content_type is not None:
            doc.content_type = body.content_type
        await repo.commit()
    logger.info("Patched document", extra={"document_id": document_id})
    response: dict = {"document_id": document_id, "updated": True}
    if body.content_type is not None:
        response["note"] = "Re-ingest document to apply new chunking strategy."
    return response


@router.post("/{document_id}/retag")
async def retag_document(document_id: str):
    """Manually trigger auto-tag enrichment for a document.

    Idempotent: a second call with no new model suggestions returns added=0.
    Failures are swallowed by enrich_document_tags itself; the endpoint
    always returns 200 with the count of new tags added (zero on failure).
    """
    added = await enrich_document_tags(document_id)
    return {"document_id": document_id, "added": added}


@router.post("/tags/prune-auto")
async def prune_auto_tags_endpoint():
    """Sweep entity-derived auto-tags that fail the current quality gate.

    Re-applies the TAG_STOPLIST + min-length + non-numeric rules to every
    existing entity-1 provenance row and removes failures via the standard
    sync path (canonical counts, shadow index, JSON column stay aligned).
    Manual tags and LLM-suggested auto-tags are never touched.
    """
    result = await prune_auto_entity_tags()
    return result


@router.post("/retag-all")
async def retag_all_documents():
    """Schedule auto-tag enrichment for every complete document.

    Runs each enrichment as a fire-and-forget background task so the response
    returns immediately with the queued count. Errors during any individual
    enrichment are swallowed and logged by enrich_document_tags.

    Use this once after upgrading to populate auto-tags on existing docs that
    pre-date the auto-tagger; new docs get enrichment automatically during
    ingestion. Calling it again later is safe but cheap-ish work for docs
    whose tag set has already stabilised.
    """
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(DocumentModel.id).where(DocumentModel.stage == "complete")
            )
        ).all()
    doc_ids = [r[0] for r in rows]
    for did in doc_ids:
        task = asyncio.create_task(enrich_document_tags(did))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    logger.info("retag-all: queued %d docs", len(doc_ids))
    return {"queued": len(doc_ids)}


@router.patch("/{document_id}/tags")
async def patch_document_tags(document_id: str, body: PatchTagsRequest):
    """Replace the tag list for a document."""
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        doc = await repo.get_or_404(document_id)

        normalized = [normalize_tag_slug(t) for t in body.tags if normalize_tag_slug(t)]
        doc.tags = normalized
        await sync_document_tag_index(
            document_id, normalized, session, record_manual_provenance=True
        )
        await repo.commit()
    logger.info(
        "Patched document tags",
        extra={"document_id": document_id, "tag_count": len(normalized)},
    )
    return {"document_id": document_id, "tags": normalized}


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str):
    # Cancel any in-flight ingestion task before tearing down rows. The workflow
    # writes to chunks / sections / embeddings as it progresses; if we delete
    # while it is mid-stage, SQLite holds locks and the workflow can also write
    # orphan rows back to tables we just emptied.
    cancelled = await get_ingestion_jobs().cancel(document_id)
    if cancelled:
        logger.info(
            "Cancelled in-flight ingestion before delete",
            extra={"document_id": document_id},
        )

    svc = get_document_deletion_service()
    async with get_session_factory()() as session:
        doc = await get_or_404(session, DocumentModel, document_id, name="Document")
        await svc.delete_sqlite_cascade(session, doc)
        await session.commit()  # cascade service took the session; commit completes the transaction

    svc.delete_lancedb_vectors(document_id)
    svc.delete_kuzu_nodes(document_id)
    svc.delete_filesystem_assets(document_id)
    logger.info("Deleted document %s", document_id)


@router.get("/{document_id}/status")
async def get_document_status(document_id: str):
    async with get_session_factory()() as session:
        doc = await get_or_404(session, DocumentModel, document_id, name="Document")
    stage = doc.stage
    progress_pct = STAGE_PROGRESS.get(stage, 0)
    logger.debug("Status polled", extra={"document_id": document_id, "stage": stage})
    return {
        "document_id": document_id,
        "stage": stage,
        "progress_pct": progress_pct,
        "done": stage == "complete",
        "error_message": (doc.error_message or "Ingestion failed. Please try again.")
        if stage == "error"
        else None,
    }


@router.get("/{document_id}/diagnostics", response_model=DocumentDiagnostics)
async def get_document_diagnostics(document_id: str):
    """Return per-store counts for the given document.

    Returns 404 if the document does not exist in SQLite.
    All other counts are 0 if the store is unavailable or empty.
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

        # Two counts share a session with the get_or_404 guard; FTS5 virtual table
        # requires raw SQL so both stay here rather than going through a repo.
        chunk_result = await session.execute(
            select(func.count(ChunkModel.id)).where(ChunkModel.document_id == document_id)
        )
        chunk_count = chunk_result.scalar_one() or 0

        # FTS5 count
        fts_result = await session.execute(
            text("SELECT COUNT(*) FROM chunks_fts WHERE document_id = :did"),
            {"did": document_id},
        )
        fts_count = fts_result.scalar_one() or 0

    # LanceDB vector count (0 if store unavailable)
    try:
        vector_count = get_lancedb_service().count_for_document(document_id)
    except Exception:
        vector_count = 0

    # Kuzu entity and edge counts (0 if graph unavailable)
    try:

        entity_count, edge_count = _graph_module.get_graph_service().count_for_document(document_id)
    except Exception:
        entity_count = 0
        edge_count = 0

    return DocumentDiagnostics(
        chunk_count=chunk_count,
        fts_count=fts_count,
        entity_count=entity_count,
        edge_count=edge_count,
        vector_count=vector_count,
    )


# In-document FTS5 search


@router.get("/{document_id}/search", response_model=list[DocumentSectionSearchResult])
async def search_document_sections(
    document_id: str,
    q: str = Query(default="", min_length=0),
) -> list[DocumentSectionSearchResult]:
    """FTS5 keyword search scoped to a single document.

    Returns up to 50 section-level results ordered by match count desc.
    Returns [] for empty/whitespace-only query (not an error).
    Returns 404 if document does not exist.
    """

    if not q or not q.strip():
        return []

    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

    svc = get_document_search_service()
    results = await svc.search(document_id, q, limit=50)
    logger.info(
        "Document search: doc=%s query=%r hits=%d",
        document_id,
        q[:50],
        len(results),
    )
    return [DocumentSectionSearchResult(**r) for r in results]


@router.get("/{document_id}/conversation")
async def get_conversation_metadata(document_id: str) -> dict:
    """Return speaker roster and timeline for a conversation document.

    Returns 404 if not found, 400 if content_type != 'conversation'.
    """
    async with get_session_factory()() as session:
        doc = await get_or_404(session, DocumentModel, document_id, name="Document")

    if doc.content_type != "conversation":
        raise HTTPException(
            status_code=400,
            detail=f"Document is not a conversation (content_type={doc.content_type})",
        )

    metadata = doc.conversation_metadata or {
        "speakers": [],
        "total_turns": 0,
        "has_timestamps": False,
        "first_timestamp": None,
        "last_timestamp": None,
    }
    return metadata


@router.get("/{document_id}/code_snippets", response_model=list[CodeSnippetItem])
async def get_code_snippets(document_id: str) -> list[CodeSnippetItem]:
    """Return extracted code snippets for a document.

    Returns an empty list for non-tech documents or documents with no code blocks.
    Returns 404 if the document does not exist.
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

        # Shares session with get_or_404; simple document-scoped read-only list.
        snippets_result = await session.execute(
            select(CodeSnippetModel)
            .where(CodeSnippetModel.document_id == document_id)
            .order_by(CodeSnippetModel.created_at)
        )
        snippets = snippets_result.scalars().all()

    return [
        CodeSnippetItem(
            id=s.id,
            chunk_id=s.chunk_id,
            section_id=s.section_id,
            language=s.language,
            signature=s.signature,
            content=s.content,
        )
        for s in snippets
    ]


@router.get("/{document_id}/objectives", response_model=LearningObjectivesResponse)
async def get_objectives(document_id: str) -> LearningObjectivesResponse:
    """Return extracted learning objectives for a document.

    Returns empty list for fiction books (no rows).
    Returns 404 if the document does not exist.
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

        # Shares session with get_or_404; simple document-scoped read-only list.
        result = await session.execute(
            select(LearningObjectiveModel)
            .where(LearningObjectiveModel.document_id == document_id)
            .order_by(LearningObjectiveModel.created_at)
        )
        objectives = result.scalars().all()

    return LearningObjectivesResponse(
        document_id=document_id,
        objectives=[
            LearningObjectiveItem(
                id=obj.id,
                section_id=obj.section_id,
                text=obj.text,
                covered=obj.covered,
            )
            for obj in objectives
        ],
    )


@router.patch(
    "/{document_id}/objectives/{objective_id}",
    response_model=LearningObjectiveItem,
)
async def update_objective(
    document_id: str,
    objective_id: str,
    payload: LearningObjectiveUpdate,
) -> LearningObjectiveItem:
    """Manually toggle a learning objective's covered flag.

    Independent of the auto-tracker (objective_tracker.update_coverage),
    which only flips covered to True when avg FSRS stability passes the
    threshold. This route lets the learner mark an objective done by
    judgment, e.g. after reading the section without reviewing cards yet,
    or untoggle one that was auto-marked but they don't actually feel
    confident on.

    Returns the updated objective. 404 when document or objective is
    missing, or when the objective belongs to a different document
    (blocks cross-document tampering by id-guess).
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")
        obj = await get_or_404(
            session, LearningObjectiveModel, objective_id, name="Objective"
        )
        if obj.document_id != document_id:
            raise HTTPException(status_code=404, detail="Objective not found in document")
        obj.covered = payload.covered
        await session.commit()  # single field update; session flows through get_or_404 above
        await session.refresh(obj)
        return LearningObjectiveItem(
            id=obj.id,
            section_id=obj.section_id,
            text=obj.text,
            covered=obj.covered,
        )


# Document learning progress


@router.get("/{document_id}/progress", response_model=DocumentProgressResponse)
async def get_document_progress(document_id: str) -> DocumentProgressResponse:
    """Return learning objective coverage progress for a document.

    Returns zeros (not 404) when the document has no objectives.
    Returns 404 when the document does not exist.
    """

    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

    tracker = get_objective_tracker_service()
    data = await tracker.get_progress(document_id)
    return DocumentProgressResponse(
        document_id=data["document_id"],
        total_objectives=data["total_objectives"],
        covered_objectives=data["covered_objectives"],
        progress_pct=data["progress_pct"],
        by_chapter=[ChapterProgressItem(**ch) for ch in data["by_chapter"]],
    )


@router.post("/{document_id}/refresh_progress", response_model=DocumentProgressResponse)
async def refresh_document_progress(document_id: str) -> DocumentProgressResponse:
    """Synchronously recalculate objective coverage and return updated progress.

    Returns 404 when the document does not exist.
    """

    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

    tracker = get_objective_tracker_service()
    await tracker.update_coverage(document_id)
    data = await tracker.get_progress(document_id)
    return DocumentProgressResponse(
        document_id=data["document_id"],
        total_objectives=data["total_objectives"],
        covered_objectives=data["covered_objectives"],
        progress_pct=data["progress_pct"],
        by_chapter=[ChapterProgressItem(**ch) for ch in data["by_chapter"]],
    )


# Reading position persistence — resume where you left off


@router.post("/{document_id}/position", response_model=ReadingPositionResponse, status_code=200)
async def save_reading_position(
    document_id: str, body: SavePositionRequest
) -> ReadingPositionResponse:
    """Upsert the last reading position for a document.

    Uses document_id as the primary key -- a second call updates the existing row
    rather than inserting a duplicate.
    Returns 404 if the document does not exist.
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

        # Upsert: read then insert-or-update in one session to avoid a second connection;
        # ReadingPositionModel is keyed by document_id (one row per doc).
        result = await session.execute(
            select(ReadingPositionModel).where(ReadingPositionModel.document_id == document_id)
        )
        row = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if row is None:
            row = ReadingPositionModel(
                document_id=document_id,
                last_section_id=body.last_section_id,
                last_section_heading=body.last_section_heading,
                last_pdf_page=body.last_pdf_page,
                last_epub_chapter_index=body.last_epub_chapter_index,
                updated_at=now,
            )
            session.add(row)
        else:
            row.last_section_id = body.last_section_id
            row.last_section_heading = body.last_section_heading
            row.last_pdf_page = body.last_pdf_page
            row.last_epub_chapter_index = body.last_epub_chapter_index
            row.updated_at = now
        await session.commit()
        await session.refresh(row)

    return ReadingPositionResponse(
        document_id=row.document_id,
        last_section_id=row.last_section_id,
        last_section_heading=row.last_section_heading,
        last_pdf_page=row.last_pdf_page,
        last_epub_chapter_index=row.last_epub_chapter_index,
    )


@router.get("/{document_id}/position", response_model=ReadingPositionResponse)
async def get_reading_position(document_id: str) -> ReadingPositionResponse:
    """Return the last saved reading position for a document.

    Returns 404 if the document does not exist or has no saved position yet.
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")

        # Shares session with get_or_404; single-row read.
        result = await session.execute(
            select(ReadingPositionModel).where(ReadingPositionModel.document_id == document_id)
        )
        row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="No reading position saved for this document")

    return ReadingPositionResponse(
        document_id=row.document_id,
        last_section_id=row.last_section_id,
        last_section_heading=row.last_section_heading,
        last_pdf_page=row.last_pdf_page,
        last_epub_chapter_index=row.last_epub_chapter_index,
    )


@router.post("/{document_id}/activity/read", status_code=204)
async def record_doc_read(document_id: str) -> None:
    """Bump content_activity for a meaningful read (open + scroll past 10%).

    The frontend gates on the 10% threshold and a 5s debounce client-side
    so the network call only fires once per "actually reading" window;
    ActivityService re-applies a 5s server-side debounce as a safety net
    against retries / multi-tab races (plan 2E.8).
    """
    async with get_session_factory()() as session:
        await get_or_404(session, DocumentModel, document_id, name="Document")
        await ActivityService(session).record_doc_read(document_id)
