"""Each library's background work runs in that library (#388).

A library's work starts the first time this process serves it: at startup for the default
library, at its first request for any other. Every task starts inside `use_library`, so the
enrichment queue, the startup backfills and everything they launch open that library's
stores and no other's.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from app.database import get_session_factory
from app.db_init import open_library
from app.library import use_library
from app.repos.document_repo import DocumentRepo
from app.services.background import task_registry
from app.services.background_prefs import load_background_prefs
from app.services.chapter_cards import chapter_cards_handler
from app.services.concept_linker import concept_link_handler
from app.services.diagram_extractor import diagram_extract_handler
from app.services.enrichment_worker import JobHandler, drop_enrichment_worker, get_enrichment_worker
from app.services.image_enricher import image_analyze_handler
from app.services.image_extractor import image_extract_handler
from app.services.llm_admission import unattended
from app.services.reference_enricher import web_refs_handler
from app.services.settings_service import load_llm_settings
from app.storage import library_root
from app.types import DEFAULT_LIBRARY

logger = logging.getLogger(__name__)

JOB_HANDLERS: dict[str, JobHandler] = {
    "image_extract": image_extract_handler,
    "image_analyze": image_analyze_handler,
    "diagram_extract": diagram_extract_handler,
    "web_refs": web_refs_handler,
    "concept_link": concept_link_handler,
    "chapter_cards": chapter_cards_handler,
}

_background_tasks = task_registry(__name__)

# Library -> the root its work started at: the same id under another `DATA_DIR` is another library.
_serving: dict[str, Path] = {}
_starting = asyncio.Lock()


def serving() -> list[str]:
    """The libraries whose work this process runs, the default first."""
    return list(_serving)


async def serve_library(library: str) -> None:
    """Open *library* and start its work, the first time this process serves it.

    Startup opens the default library itself, before anything else reads it.
    """
    root = library_root(library=library)
    if _serving.get(library) == root:
        return
    async with _starting:
        if _serving.get(library) == root:
            return
        if library != DEFAULT_LIBRARY:
            await open_library(library)
        with use_library(library):
            await _start()
        _serving[library] = root


async def stop_library(library: str) -> None:
    """Stop *library*'s enrichment queue; the next request for it starts the work again."""
    _serving.pop(library, None)
    with use_library(library):
        await get_enrichment_worker().stop()
        drop_enrichment_worker()


async def stop_serving() -> None:
    for library in serving():
        await stop_library(library)


async def _start() -> None:
    await _load_preferences()
    worker = get_enrichment_worker()
    for job_type, handler in JOB_HANDLERS.items():
        worker.register(job_type, handler)
    await worker.start()
    await _fail_interrupted_ingestions()
    if "pytest" not in sys.modules:
        _start_backfills()


async def _load_preferences() -> None:
    # Before the queue starts: background work reads the library's engine mode and pacing.
    try:
        async with get_session_factory()() as session:
            await load_llm_settings(session)
            await load_background_prefs(session)
    except Exception:
        logger.warning("could not load the library's settings; using defaults", exc_info=True)


async def _fail_interrupted_ingestions() -> None:
    # An ingestion running when the process died has no task left to finish it (I-10).
    try:
        async with get_session_factory()() as session:
            failed = await DocumentRepo(session).fail_unfinished(
                "Ingestion was interrupted before it finished. "
                "Delete this document and upload it again."
            )
            await session.commit()
        if failed:
            logger.warning("marked %d interrupted ingestion(s) as failed at startup", failed)
    except Exception:
        logger.warning("could not reconcile interrupted ingestions", exc_info=True)


async def _refile_flashcards() -> None:
    # Cards written before I-35 sit under their generation call's first chapter.
    try:
        await asyncio.sleep(15)
        from app.services.flashcard_repair import refile_cards

        async with get_session_factory()() as session:
            await refile_cards(session)
            await session.commit()
    except Exception as exc:
        logger.warning("Flashcard refile failed (non-fatal): %s", exc)


def _start_backfills() -> None:
    # Delayed so they do not compete with model warmup; each no-ops once its library is caught up.
    async def backfill_descriptions():
        try:
            await asyncio.sleep(20)
            from app.services.notes_service import backfill_missing_descriptions

            await backfill_missing_descriptions()
        except Exception as exc:
            logger.warning("Description backfill failed (non-fatal): %s", exc)

    # Notes saved before the 384-dimension fix have no vectors (I-9); the one manual
    # trigger is admin-only, so without this only new notes are searchable by meaning.
    async def backfill_note_vectors():
        try:
            await asyncio.sleep(30)
            from app.services.reindex_service import get_reindex_service

            async with get_session_factory()() as _reindex_db:
                report = await get_reindex_service().reindex_notes(_reindex_db)
            if report["reindexed"] or report["failed"]:
                logger.info(
                    "Note vector backfill: %d embedded, %d failed, %d total",
                    report["reindexed"],
                    report["failed"],
                    report["total"],
                )
        except Exception as exc:
            logger.warning("Note vector backfill failed (non-fatal): %s", exc)

    # Deferred summarisation is fire-and-forget and nothing records that it was owed, so a
    # laptop closed mid-ingest would leave a document without summaries for good. After the
    # note backfill, so the two do not compete for the one model slot.
    async def backfill_section_summaries():
        try:
            await asyncio.sleep(90)
            from app.services.section_summarizer import resummarize_documents_missing_summaries

            repaired = await resummarize_documents_missing_summaries()
            if repaired:
                logger.info("Section summary backfill: repaired %d document(s)", repaired)
        except Exception as exc:
            logger.warning("Section summary backfill failed (non-fatal): %s", exc)

    _background_tasks.add(asyncio.create_task(_refile_flashcards()))
    with unattended():
        _background_tasks.add(asyncio.create_task(backfill_descriptions()))
    _background_tasks.add(asyncio.create_task(backfill_note_vectors()))
    with unattended():
        _background_tasks.add(asyncio.create_task(backfill_section_summaries()))
