"""Background work runs in the library it belongs to and writes to that library's root (#388)."""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

import app.runtime.library_work as library_work
from app.database import get_session_factory
from app.db_init import open_library
from app.library import current_library, use_library
from app.models import EnrichmentJobModel, NoteModel
from app.services import chapter_backfill
from app.services.chapters import Chapter
from app.services.enrichment_worker import get_enrichment_worker, requeue_skipped_jobs
from app.services.ingestion_jobs import get_ingestion_jobs
from tests.factories import make_document, make_note
from tests.test_library_context import _close, two_libraries  # noqa: F401

LIBRARIES = ("first", "second")


async def _queue(library: str, status: str = "pending") -> str:
    doc_id = str(uuid.uuid4())
    with use_library(library):
        async with get_session_factory()() as session:
            session.add(make_document(id=doc_id, title=f"A {library} book", stage="complete"))
            await session.flush()
            session.add(
                EnrichmentJobModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    job_type="probe",
                    status=status,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()
    return doc_id


async def _in(library: str, column) -> list:
    with use_library(library):
        async with get_session_factory()() as session:
            return sorted((await session.execute(select(column))).scalars().all())


async def _statuses() -> dict[str, list[str]]:
    return {lib: await _in(lib, EnrichmentJobModel.status) for lib in LIBRARIES}


async def test_each_librarys_queue_runs_in_that_library(two_libraries, monkeypatch):  # noqa: F811
    ran: list[tuple[str, str]] = []

    async def probe(document_id: str, _job_id: str) -> None:
        ran.append((current_library(), document_id))
        async with get_session_factory()() as session:
            session.add(make_note(document_id=document_id, content="written by the worker"))
            await session.commit()

    monkeypatch.setattr(library_work, "JOB_HANDLERS", {"probe": probe})
    for library in LIBRARIES:
        await open_library(library)
    docs = {library: await _queue(library) for library in LIBRARIES}
    try:
        for library in LIBRARIES:
            await library_work.serve_library(library)
        async with asyncio.timeout(10):
            while await _statuses() != {lib: ["done"] for lib in LIBRARIES}:
                await asyncio.sleep(0.05)
        notes = {lib: await _in(lib, NoteModel.document_id) for lib in LIBRARIES}
    finally:
        await _close(*LIBRARIES)

    assert sorted(ran) == sorted((lib, doc) for lib, doc in docs.items())
    assert notes == {lib: [doc] for lib, doc in docs.items()}


async def test_an_installed_component_requeues_skipped_work_in_every_library(two_libraries):  # noqa: F811
    for library in LIBRARIES:
        await open_library(library)
        await _queue(library, status="skipped")
        with use_library(library):
            get_enrichment_worker()
    try:
        assert await requeue_skipped_jobs() == len(LIBRARIES)
        jobs = await _statuses()
    finally:
        await _close(*LIBRARIES)
    assert jobs == {lib: ["pending"] for lib in LIBRARIES}


async def test_a_request_cancels_only_its_own_librarys_ingestions():
    with use_library("first"):
        task = get_ingestion_jobs().launch("doc-1", asyncio.sleep(60))
    with use_library("second"):
        assert not get_ingestion_jobs().is_running("doc-1")
        assert await get_ingestion_jobs().cancel("doc-1") is False
    assert not task.done()
    with use_library("first"):
        assert await get_ingestion_jobs().cancel("doc-1") is True


async def test_the_chapter_backfill_writes_in_the_library_whose_reader_is_ahead(monkeypatch):
    def pick(ahead: bool) -> chapter_backfill.Pick:
        chapter = Chapter(id=f"ch-{current_library()}", title="Chapter 2", order=1)
        return chapter_backfill.Pick(f"doc-{current_library()}", "A book", chapter, ahead=ahead)

    async def next_chapter():
        return pick(ahead=current_library() == "second")

    written: list[tuple[str, str]] = []

    async def book_for(document_id, _session):
        return document_id

    async def write_chapter(document_id, _book, chapter, _session):
        written.append((current_library(), document_id))
        return [chapter.id]

    async def now(_pick, _libraries):
        return None

    monkeypatch.setattr(chapter_backfill, "next_chapter", next_chapter)
    monkeypatch.setattr(chapter_backfill, "not_now", now)
    monkeypatch.setattr(chapter_backfill, "_local_model", lambda: None)
    monkeypatch.setattr(chapter_backfill, "book_for", book_for)
    monkeypatch.setattr(chapter_backfill, "write_chapter", write_chapter)
    monkeypatch.setattr(chapter_backfill, "get_session_factory", lambda: _no_session)

    assert await chapter_backfill.run_once(list(LIBRARIES)) == (True, None)
    assert written == [("second", "doc-second")]


class _NoSession:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_exc):
        return False


def _no_session():
    return _NoSession()
