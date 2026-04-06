"""Tests for S170: Note vector dimension fix, ReindexService, and admin endpoint."""

import os
import statistics
import time
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.vector_store as vs_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import NoteModel, NoteTagIndexModel  # noqa: F401

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    # Reset LanceDB singleton so it picks up the temp DATA_DIR
    orig_vs = vs_module._lancedb_service
    vs_module._lancedb_service = None

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    vs_module._lancedb_service = orig_vs
    get_settings.cache_clear()
    await engine.dispose()


@pytest.fixture
def client(test_db):
    """Sync TestClient bound to the test_db fixture."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_note(note_id: str | None = None, content: str = "test", **kwargs) -> NoteModel:
    return NoteModel(
        id=note_id or str(uuid.uuid4()),
        content=content,
        tags=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Test: dim mismatch detection triggers drop-and-recreate
# ---------------------------------------------------------------------------


def test_dim_mismatch_triggers_drop_and_recreate(tmp_path):
    """_get_or_create_note_table with a 384-dim existing table drops and recreates."""
    from app.services.vector_store import NOTE_TABLE_NAME, NOTE_VECTOR_DIM, LanceDBService

    svc = LanceDBService()

    # Build a fake table with a 384-dim schema
    bad_schema = pa.schema(
        [
            pa.field("note_id", pa.string()),
            pa.field("document_id", pa.string()),
            pa.field("content", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 384)),
        ]
    )
    mock_table = MagicMock()
    mock_table.schema = bad_schema

    mock_db = MagicMock()
    mock_db.list_tables.return_value.tables = [NOTE_TABLE_NAME]
    mock_db.open_table.return_value = mock_table
    mock_db.create_table.return_value = MagicMock()

    svc._db = mock_db

    import logging
    with patch.object(logging.getLogger("app.services.vector_store"), "warning") as mock_warn:
        svc._get_or_create_note_table()

    # drop_table should have been called once with the note table name
    mock_db.drop_table.assert_called_once_with(NOTE_TABLE_NAME)
    # create_table should have been called to recreate
    mock_db.create_table.assert_called_once()
    # Warning should have been logged mentioning the dim mismatch
    assert mock_warn.called
    warn_args = mock_warn.call_args[0]
    assert 384 in warn_args
    assert NOTE_VECTOR_DIM in warn_args


def test_correct_dim_does_not_trigger_drop(tmp_path):
    """_get_or_create_note_table with correct 1024-dim schema does not drop the table."""
    from app.services.vector_store import NOTE_TABLE_NAME, NOTE_VECTOR_DIM, LanceDBService

    svc = LanceDBService()

    good_schema = pa.schema(
        [
            pa.field("note_id", pa.string()),
            pa.field("document_id", pa.string()),
            pa.field("content", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), NOTE_VECTOR_DIM)),
        ]
    )
    mock_table = MagicMock()
    mock_table.schema = good_schema

    mock_db = MagicMock()
    mock_db.list_tables.return_value.tables = [NOTE_TABLE_NAME]
    mock_db.open_table.return_value = mock_table

    svc._db = mock_db
    result = svc._get_or_create_note_table()

    mock_db.drop_table.assert_not_called()
    assert result is mock_table


# ---------------------------------------------------------------------------
# Test: reindex_notes returns correct reindexed count
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reindex_notes_reindexes_absent_notes(test_db):
    """reindex_notes returns reindexed=2 when 2 of 3 notes are absent from LanceDB."""
    engine, factory, _ = test_db

    note_ids = [str(uuid.uuid4()) for _ in range(3)]
    async with factory() as session:
        for nid in note_ids:
            session.add(_make_note(nid, content=f"note content {nid}"))
        await session.commit()

    from app.services.reindex_service import ReindexService

    svc = ReindexService()

    # First note is present, last two are absent
    present_id = note_ids[0]

    def _mock_count_rows(filter_expr: str) -> int:
        nid = filter_expr.split("'")[1]
        return 1 if nid == present_id else 0

    mock_tbl = MagicMock()
    mock_tbl.count_rows.side_effect = _mock_count_rows

    mock_vs = MagicMock()
    mock_vs._get_or_create_note_table.return_value = mock_tbl
    mock_vs.upsert_note_vector = MagicMock()

    mock_embedder = MagicMock()
    mock_embedder.encode.return_value = [[0.0] * 1024]

    with (
        patch("app.services.reindex_service.get_reindex_service"),
        patch("app.services.vector_store.get_lancedb_service", return_value=mock_vs),
        patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
    ):
        async with factory() as session:
            report = await svc.reindex_notes(session)

    assert report["total"] == 3
    assert report["reindexed"] == 2
    assert report["failed"] == 0
    assert mock_vs.upsert_note_vector.call_count == 2


@pytest.mark.anyio
async def test_reindex_notes_counts_failed_on_exception(test_db):
    """reindex_notes increments failed when embedding raises."""
    engine, factory, _ = test_db

    note_ids = [str(uuid.uuid4()) for _ in range(2)]
    async with factory() as session:
        for nid in note_ids:
            session.add(_make_note(nid))
        await session.commit()

    from app.services.reindex_service import ReindexService

    svc = ReindexService()

    mock_tbl = MagicMock()
    mock_tbl.count_rows.return_value = 0  # all absent

    mock_vs = MagicMock()
    mock_vs._get_or_create_note_table.return_value = mock_tbl

    mock_embedder = MagicMock()
    mock_embedder.encode.side_effect = RuntimeError("embedding unavailable")

    with (
        patch("app.services.vector_store.get_lancedb_service", return_value=mock_vs),
        patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
    ):
        async with factory() as session:
            report = await svc.reindex_notes(session)

    assert report["total"] == 2
    assert report["reindexed"] == 0
    assert report["failed"] == 2


# ---------------------------------------------------------------------------
# Test: admin key auth
# ---------------------------------------------------------------------------


def test_reindex_endpoint_wrong_key_returns_403(test_db, monkeypatch):
    """POST /admin/notes/reindex returns 403 when X-Admin-Key is wrong and ADMIN_KEY set."""
    monkeypatch.setenv("ADMIN_KEY", "supersecret")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with TestClient(app) as c:
            resp = c.post("/admin/notes/reindex", headers={"X-Admin-Key": "wrongkey"})
        assert resp.status_code == 403
    finally:
        monkeypatch.delenv("ADMIN_KEY", raising=False)
        get_settings.cache_clear()


def test_reindex_endpoint_correct_key_returns_200(test_db, monkeypatch):
    """POST /admin/notes/reindex returns 200 with correct X-Admin-Key."""
    monkeypatch.setenv("ADMIN_KEY", "supersecret")
    from app.config import get_settings

    get_settings.cache_clear()

    try:
        with TestClient(app) as c:
            resp = c.post("/admin/notes/reindex", headers={"X-Admin-Key": "supersecret"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["queued"] is True
        assert isinstance(body["total_notes"], int)
    finally:
        monkeypatch.delenv("ADMIN_KEY", raising=False)
        get_settings.cache_clear()


def test_reindex_endpoint_no_auth_when_admin_key_empty(test_db):
    """POST /admin/notes/reindex succeeds without header when ADMIN_KEY is empty."""
    from app.config import get_settings

    # Ensure ADMIN_KEY is empty (default)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.ADMIN_KEY == ""

    with TestClient(app) as c:
        resp = c.post("/admin/notes/reindex")
    assert resp.status_code == 200
    body = resp.json()
    assert body["queued"] is True
    assert isinstance(body["total_notes"], int)


# ---------------------------------------------------------------------------
# Performance test: 1,000-note tag query p95 < 100ms
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    not os.getenv("LUMINARY_PERF_TESTS"),
    reason="Set LUMINARY_PERF_TESTS=1 to run performance tests",
)
@pytest.mark.anyio
async def test_tag_query_p95_under_100ms_at_1000_notes(test_db):
    """GET /notes?tag=science p95 < 100ms with 1,000 notes + NoteTagIndexModel indexes."""
    engine, factory, _ = test_db

    # Insert 1,000 NoteModel + NoteTagIndexModel rows
    async with factory() as session:
        for i in range(1000):
            nid = str(uuid.uuid4())
            note = NoteModel(
                id=nid,
                content=f"note {i}",
                tags=["science"],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(note)
            session.add(
                NoteTagIndexModel(
                    note_id=nid,
                    tag_full="science",
                    tag_root="science",
                    tag_parent="",
                )
            )
        await session.commit()

    times: list[float] = []
    with TestClient(app) as c:
        for _ in range(10):
            start = time.perf_counter()
            resp = c.get("/notes?tag=science")
            elapsed = time.perf_counter() - start
            assert resp.status_code == 200
            times.append(elapsed)

    p95 = statistics.quantiles(times, n=20)[18]  # 95th percentile
    assert p95 < 0.1, f"p95 tag query latency {p95*1000:.1f}ms exceeds 100ms threshold"
