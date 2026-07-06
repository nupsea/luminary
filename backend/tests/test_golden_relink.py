"""Stale source-document handling for generated golden datasets.

Regression for the silent-zero bug: a dataset generated from a document that
was later deleted pins a dead source_document_id on every question. Scoped
retrieval then returns nothing and every run records an honest-looking 0%
instead of an error. The API must flag the dataset, refuse to run it, and
offer a re-link repair.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, GoldenDatasetModel, GoldenQuestionModel

DEAD_DOC = "dead-document-id"


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    get_settings.cache_clear()
    await engine.dispose()


async def _seed(factory, *, doc_ids: list[str] | None = None) -> tuple[str, str]:
    """Create a live document and a complete dataset whose questions pin
    *doc_ids* (default: only the dead id). Returns (dataset_id, live_doc_id)."""
    live_doc_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())
    pins = doc_ids or [DEAD_DOC]
    async with factory() as session:
        session.add(
            DocumentModel(
                id=live_doc_id,
                title="Apache Iceberg (re-ingested)",
                format="pdf",
                content_type="book",
                word_count=1000,
                file_path="iceberg.pdf",
                file_hash="abc",
                stage="complete",
                page_count=10,
            )
        )
        session.add(
            GoldenDatasetModel(
                id=dataset_id,
                name="iceberg_test",
                size="small",
                generator_model="test",
                source_document_ids=pins,
                status="complete",
                generated_count=len(pins) * 2,
                target_count=len(pins) * 2,
            )
        )
        for doc_id in pins:
            for i in range(2):
                session.add(
                    GoldenQuestionModel(
                        id=str(uuid.uuid4()),
                        dataset_id=dataset_id,
                        question=f"q-{doc_id}-{i}",
                        ground_truth_answer="a",
                        context_hint="hint",
                        source_chunk_id="stale-chunk",
                        source_document_id=doc_id,
                    )
                )
        await session.commit()
    return dataset_id, live_doc_id


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_dataset_list_flags_missing_documents(test_db):
    dataset_id, _live = await _seed(test_db)
    async with _client() as client:
        resp = await client.get("/evals/datasets")
    assert resp.status_code == 200
    item = next(d for d in resp.json() if d.get("id") == dataset_id)
    assert item["missing_document_ids"] == [DEAD_DOC]


async def test_run_rejected_when_all_source_documents_dead(test_db):
    dataset_id, _live = await _seed(test_db)
    async with _client() as client:
        resp = await client.post(
            f"/evals/datasets/{dataset_id}/run",
            json={"judge_model": "", "check_citations": False, "max_questions": 10},
        )
    assert resp.status_code == 409
    assert "Re-link" in resp.json()["detail"]


async def test_relink_repairs_dataset(test_db):
    dataset_id, live_doc_id = await _seed(test_db)
    async with _client() as client:
        resp = await client.patch(
            f"/evals/datasets/{dataset_id}/relink",
            json={"document_id": live_doc_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["relinked_questions"] == 2
        assert body["missing_document_ids"] == []

        listed = await client.get("/evals/datasets")
        item = next(d for d in listed.json() if d.get("id") == dataset_id)
        assert item["missing_document_ids"] == []
        assert item["source_document_ids"] == [live_doc_id]

    async with test_db() as session:
        rows = (
            (
                await session.execute(
                    select(GoldenQuestionModel).where(
                        GoldenQuestionModel.dataset_id == dataset_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert all(q.source_document_id == live_doc_id for q in rows)
    assert all(q.source_chunk_id == "" for q in rows)


async def test_run_forwards_ablation_and_rerank(test_db, monkeypatch):
    """The generated-dataset run endpoint supports the same options as the
    file-golden console path (regression: ablation/rerank were file-only)."""
    from unittest.mock import AsyncMock

    import app.routers.evals as evals_router

    dataset_id, live_doc_id = await _seed(test_db)
    async with test_db() as session:
        from sqlalchemy import update

        await session.execute(
            update(GoldenQuestionModel)
            .where(GoldenQuestionModel.dataset_id == dataset_id)
            .values(source_document_id=live_doc_id)
        )
        await session.commit()

    launched = AsyncMock()
    monkeypatch.setattr(evals_router, "_run_generated_eval_subprocess", launched)
    async with _client() as client:
        resp = await client.post(
            f"/evals/datasets/{dataset_id}/run",
            json={
                "judge_model": "",
                "max_questions": 10,
                "rerank": True,
                "ablation": True,
            },
        )
    assert resp.status_code == 202
    assert launched.call_args.kwargs["rerank"] is True
    assert launched.call_args.kwargs["ablation"] is True


async def test_relink_rejects_dead_target(test_db):
    dataset_id, _live = await _seed(test_db)
    async with _client() as client:
        resp = await client.patch(
            f"/evals/datasets/{dataset_id}/relink",
            json={"document_id": "also-not-a-document"},
        )
    assert resp.status_code == 422


async def test_relink_multi_doc_requires_from_document_id(test_db):
    dataset_id, live_doc_id = await _seed(test_db, doc_ids=[DEAD_DOC, "second-dead"])
    async with _client() as client:
        ambiguous = await client.patch(
            f"/evals/datasets/{dataset_id}/relink",
            json={"document_id": live_doc_id},
        )
        assert ambiguous.status_code == 422

        scoped = await client.patch(
            f"/evals/datasets/{dataset_id}/relink",
            json={"document_id": live_doc_id, "from_document_id": DEAD_DOC},
        )
        assert scoped.status_code == 200
        assert scoped.json()["relinked_questions"] == 2
        assert scoped.json()["missing_document_ids"] == ["second-dead"]
