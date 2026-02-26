"""Diagnostics endpoint tests — verify per-store counts after full book ingestion.

All threshold values are read from DATA/books/manifest.json — no hardcoded counts.

Run slow tests only:
    make test-full
    # or
    cd backend && uv run pytest tests/test_diagnostics.py -v -m slow
"""

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app

# Load manifest at import time so parametrize can reference it.
REPO_ROOT = Path(__file__).parent.parent.parent
MANIFEST_PATH = REPO_ROOT / "DATA" / "books" / "manifest.json"
MANIFEST: list[dict] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

# pytest_plugins loads the shared session fixture from conftest_books.py.
# The module path is relative to the pytest rootdir (backend/).
pytest_plugins = ["tests.conftest_books"]


# ---------------------------------------------------------------------------
# Fast test DB fixture (in-memory SQLite, no ML)
# ---------------------------------------------------------------------------


@pytest.fixture
async def _fast_test_db(tmp_path, monkeypatch):
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
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    yield
    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Fast test (no ML required)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnostics_not_found(_fast_test_db):
    """GET /documents/nonexistent-id/diagnostics must return 404."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/documents/nonexistent-doc-id-abc123/diagnostics")
    assert resp.status_code == 404, (
        f"Expected 404, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# Slow parametrized tests (require all_books_ingested fixture)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "book_name",
    [entry["name"] for entry in MANIFEST],
)
async def test_diagnostics_counts(book_name: str, all_books_ingested):
    """Each book must meet all per-store count thresholds from manifest.json."""
    book_entry = next(e for e in MANIFEST if e["name"] == book_name)
    thresholds = book_entry["thresholds"]

    doc_id = all_books_ingested[book_name]["doc_id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/documents/{doc_id}/diagnostics")

    assert resp.status_code == 200, (
        f"Expected 200 for '{book_name}', got {resp.status_code}: {resp.text}"
    )
    data = resp.json()

    chunk_min = thresholds["chunk_count_min"]
    fts_min = thresholds["fts_count_min"]
    vector_min = thresholds["vector_count_min"]
    entity_min = thresholds["entity_count_min"]
    edge_min = thresholds["edge_count_min"]

    print(
        f"\n[{book_name}] diagnostics: "
        f"chunks={data['chunk_count']} (min {chunk_min}), "
        f"fts={data['fts_count']} (min {fts_min}), "
        f"vectors={data['vector_count']} (min {vector_min}), "
        f"entities={data['entity_count']} (min {entity_min}), "
        f"edges={data['edge_count']} (min {edge_min})",
        flush=True,
    )

    assert data["chunk_count"] >= chunk_min, (
        f"'{book_name}': chunk_count {data['chunk_count']} < {chunk_min}"
    )
    assert data["fts_count"] >= fts_min, (
        f"'{book_name}': fts_count {data['fts_count']} < {fts_min}"
    )
    assert data["vector_count"] >= vector_min, (
        f"'{book_name}': vector_count {data['vector_count']} < {vector_min}"
    )
    assert data["entity_count"] >= entity_min, (
        f"'{book_name}': entity_count {data['entity_count']} < {entity_min}"
    )
    assert data["edge_count"] >= edge_min, (
        f"'{book_name}': edge_count {data['edge_count']} < {edge_min}"
    )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_ingest_timing_odyssey(all_books_ingested):
    """The Odyssey ingestion must complete within 1800s (30 min budget)."""
    elapsed = all_books_ingested["The Odyssey"]["elapsed_seconds"]
    budget = next(
        e["ingest_time_budget_seconds"]
        for e in MANIFEST
        if e["name"] == "The Odyssey"
    )
    print(
        f"\n[The Odyssey] elapsed={elapsed:.1f}s / budget={budget}s",
        flush=True,
    )
    assert elapsed <= budget, (
        f"Odyssey ingestion took {elapsed:.0f}s, budget is {budget}s. "
        f"Optimise the pipeline before increasing this budget."
    )
