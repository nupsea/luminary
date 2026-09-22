"""A deleted document leaves no summary behind and stops describing the library (#140).

Summarisation is a background task that deleting the document does not cancel.
Measured on a smoke run: a document deleted at 11:00:26 had summaries written at
11:01:47, 11:03:09 and 11:04:20, and those orphans then fed the library summary,
which nothing refreshed on delete -- "Summarize all documents" described books
that were no longer in the library.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, LibrarySummaryModel, SummaryModel
from app.services.document_deletion_service import DocumentDeletionService
from app.services.summarizer import SummarizationService


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    orig = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, session_factory
    yield session_factory
    db_module._engine, db_module._session_factory = orig
    get_settings.cache_clear()
    await engine.dispose()


async def _add_doc(factory, doc_id: str, summary: str | None = None) -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title=f"Doc {doc_id[:4]}",
                format="txt",
                content_type="notes",
                word_count=100,
                page_count=1,
                file_path=f"/nonexistent/{doc_id}.txt",
                stage="complete",
            )
        )
        if summary is not None:
            session.add(
                SummaryModel(
                    id=str(uuid.uuid4()), document_id=doc_id, mode="executive", content=summary
                )
            )
        await session.commit()


async def _delete(factory, doc_id: str) -> None:
    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
        await DocumentDeletionService().delete_sqlite_cascade(session, doc)
        await session.commit()


async def _count(factory, stmt) -> int:
    async with factory() as session:
        return (await session.execute(stmt)).scalar_one()


def _blocking_llm(stream: bool):
    """An LLM whose first call waits until the test releases it."""
    started, release = asyncio.Event(), asyncio.Event()

    async def _tokens():
        yield "Overview"

    async def _generate(*_args, **_kwargs):
        started.set()
        await release.wait()
        return _tokens() if stream else "A summary."

    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=_generate)
    return llm, started, release


async def test_summaries_finished_after_the_delete_are_not_stored(factory):
    doc_id = str(uuid.uuid4())
    await _add_doc(factory, doc_id)
    svc = SummarizationService()
    llm, started, release = _blocking_llm(stream=False)

    with (
        patch("app.services.summarizer.get_llm_service", return_value=llm),
        patch.object(svc, "_build_section_summary_input", AsyncMock(return_value="Sections.")),
        patch.object(svc, "build_assembled_summary", AsyncMock(return_value=None)),
    ):
        job = asyncio.create_task(svc.pregenerate(doc_id))
        await asyncio.wait_for(started.wait(), timeout=5)
        await _delete(factory, doc_id)
        release.set()
        await asyncio.wait_for(job, timeout=5)

    orphans = select(func.count()).select_from(SummaryModel)
    assert await _count(factory, orphans.where(SummaryModel.document_id == doc_id)) == 0


async def test_store_summary_still_writes_for_a_live_document(factory):
    doc_id = str(uuid.uuid4())
    await _add_doc(factory, doc_id)
    summary_id = await SummarizationService()._store_summary(doc_id, "executive", "Text.")
    assert summary_id is not None
    async with factory() as session:
        row = await session.get(SummaryModel, summary_id)
    assert (row.document_id, row.content) == (doc_id, "Text.")


async def test_library_input_ignores_summaries_of_deleted_documents(factory):
    live = str(uuid.uuid4())
    await _add_doc(factory, live, summary="Live summary.")
    async with factory() as session:
        session.add(
            SummaryModel(
                id=str(uuid.uuid4()),
                document_id=str(uuid.uuid4()),
                mode="executive",
                content="Orphan summary.",
            )
        )
        await session.commit()

    assert await SummarizationService()._fetch_all_executive_summaries() == {
        live: "Live summary."
    }


@pytest.mark.real_library_summary
async def test_delete_drops_the_library_summary_and_an_inflight_refresh_is_not_kept(factory):
    kept, deleted = str(uuid.uuid4()), str(uuid.uuid4())
    await _add_doc(factory, kept, summary="Kept summary.")
    await _add_doc(factory, deleted, summary="Deleted summary.")
    async with factory() as session:
        session.add(LibrarySummaryModel(id="old", mode="executive", content="Old overview"))
        await session.commit()

    svc = SummarizationService()
    llm, started, release = _blocking_llm(stream=True)
    library_rows = select(func.count()).select_from(LibrarySummaryModel)

    with (
        patch("app.services.summarizer.get_llm_service", return_value=llm),
        patch("app.services.llm_routing.refusal", return_value=None),
    ):
        refresh = asyncio.create_task(svc.refresh_library_summary())
        await asyncio.wait_for(started.wait(), timeout=5)
        await _delete(factory, deleted)
        assert await _count(factory, library_rows) == 0, "the old overview names a deleted doc"
        release.set()
        await asyncio.wait_for(refresh, timeout=5)

    assert await _count(factory, library_rows) == 0, "built from the deleted doc; not stored"


@pytest.mark.parametrize("bulk", [False, True])
async def test_deleting_documents_schedules_a_library_summary_refresh(factory, bulk):
    doc_id = str(uuid.uuid4())
    await _add_doc(factory, doc_id)
    refreshed = asyncio.Event()

    async def _record(_self) -> None:
        refreshed.set()

    with (
        patch("app.services.vector_store.get_lancedb_service", return_value=MagicMock()),
        patch(
            "app.services.summarizer.SummarizationService.refresh_library_summary", _record
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            if bulk:
                resp = await ac.post("/documents/bulk-delete", json={"ids": [doc_id]})
            else:
                resp = await ac.delete(f"/documents/{doc_id}")
        assert resp.status_code in (200, 204)
        await asyncio.wait_for(refreshed.wait(), timeout=5)
