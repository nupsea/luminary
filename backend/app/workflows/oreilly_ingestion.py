"""Workflow for downloading and ingesting O'Reilly books into Luminary."""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from app.database import get_session_factory
from app.exceptions import InvalidInput, LuminaryError
from app.models import DocumentModel
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.naming import normalize_tag_slug
from app.services.notes_service import sync_document_tag_index
from app.services.oreilly_service import (
    OreillyClient,
    download_oreilly_book_to_epub,
    parse_oreilly_book_id,
    parse_oreilly_target_chapter,
)
from app.workflows.ingestion import run_ingestion

logger = logging.getLogger(__name__)


class OreillyNotConnected(LuminaryError):
    """No O'Reilly session is stored. The upload dialog opens its connect modal on 401."""

    status_code = 401


async def download_and_launch_ingestion(
    doc_id: str,
    book_id: str,
    dest_path: Path,
    client: OreillyClient,
    selected_chapters: list[int] | None = None,
) -> None:
    """Download chapters, compile EPUB, and trigger local LLM ingestion pipeline."""
    try:
        await asyncio.to_thread(
            download_oreilly_book_to_epub,
            book_id=book_id,
            dest_path=dest_path,
            client=client,
            selected_chapter_indices=selected_chapters,
        )
    except Exception as exc:
        logger.exception("O'Reilly book download failed for %s", book_id)
        dest_path.unlink(missing_ok=True)
        async with get_session_factory()() as session:
            doc = await session.get(DocumentModel, doc_id)
            if doc:
                doc.stage = "error"
                doc.error_message = f"O'Reilly download failed: {exc}"
                await session.commit()
        return
    # run_ingestion records its own failures on the document.
    await run_ingestion(doc_id, str(dest_path), "epub", "technical")


async def start_oreilly_ingestion(
    url: str,
    settings: Any,
    selected_chapters: list[int] | None = None,
) -> dict[str, Any]:
    """Validate session, parse book ID, create document, and launch background ingestion."""
    client = OreillyClient()
    if not client.is_configured():
        raise OreillyNotConnected(
            "O'Reilly subscription cookies not configured. "
            "Please connect your O'Reilly subscription in Settings."
        )

    book_id = parse_oreilly_book_id(url)
    if not book_id:
        raise InvalidInput(f"Could not extract O'Reilly book ID or ISBN from URL: {url}")

    # Fetch metadata for book title
    book_title = f"O'Reilly Book {book_id}"
    try:
        meta = await asyncio.to_thread(client.fetch_book_metadata, book_id)
        book_title = meta.get("title") or book_title
    except Exception as exc:
        logger.warning(
            "Could not fetch metadata for %s, proceeding with fallback title: %s",
            book_id,
            exc,
        )

    # Detect if a specific chapter was requested in the URL
    target_chapter = parse_oreilly_target_chapter(url) if selected_chapters is None else None
    matched_chapter_title: str | None = None

    if target_chapter:
        try:
            all_chapters = await asyncio.to_thread(client.fetch_chapter_list, book_id)
            target_norm = target_chapter.lower().replace(".xhtml", ".html")
            for idx, ch in enumerate(all_chapters):
                fn = ch.get("filename", "").lower().replace(".xhtml", ".html")
                ref = ch.get("reference_id", "").lower().replace(".xhtml", ".html")
                if fn == target_norm or ref.endswith(target_norm):
                    selected_chapters = [idx]
                    matched_chapter_title = ch.get("title")
                    break
        except Exception as exc:
            logger.warning("Could not resolve chapter %s for %s: %s", target_chapter, book_id, exc)

    if matched_chapter_title:
        book_title = f"{book_title} — {matched_chapter_title}"
        doc_tags = ["oreilly", "tech-chapter"]
    else:
        doc_tags = ["oreilly", "tech-book"]
    doc_tags = [normalize_tag_slug(t) for t in doc_tags]

    doc_id = str(uuid.uuid4())
    data_dir = Path(settings.DATA_DIR).expanduser()
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest_epub = raw_dir / f"{doc_id}.epub"

    async with get_session_factory()() as session:
        doc = DocumentModel(
            id=doc_id,
            title=book_title,
            format="epub",
            content_type="technical",
            word_count=0,
            page_count=0,
            file_path=str(dest_epub),
            file_hash=None,
            stage="parsing",
            source_url=url,
            tags=doc_tags,
        )
        session.add(doc)
        await session.flush()
        await sync_document_tag_index(doc_id, doc.tags, session, record_manual_provenance=True)
        await session.commit()

    get_ingestion_jobs().launch(
        doc_id,
        download_and_launch_ingestion(
            doc_id=doc_id,
            book_id=book_id,
            dest_path=dest_epub,
            client=client,
            selected_chapters=selected_chapters,
        ),
    )

    logger.info("O'Reilly book ingestion launched", extra={"doc_id": doc_id, "book_id": book_id})
    return {
        "document_id": doc_id,
        "status": "processing",
        "title": book_title,
    }
