"""API contract tests — 4xx behaviour on bad input across all routers.

Verifies:
  - Missing required fields return 422 (FastAPI validation)
  - Invalid/unknown IDs return 404 with {detail: str}
  - Uploading an unsupported file type returns 400 with {detail: str}
  - No endpoint returns a bare 500 on predictable bad input
  - All error responses use the {detail: <string>} schema

Run with:
    uv run pytest tests/test_api_contracts.py
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app

# ---------------------------------------------------------------------------
# Shared fixture — in-memory SQLite DB
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

    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)

    yield tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


def _assert_detail_str(body: dict) -> None:
    """Assert the response body has a {detail: str} schema."""
    assert "detail" in body, f"Missing 'detail' key in: {body}"
    assert isinstance(body["detail"], str), (
        f"'detail' is not a string: {body['detail']!r}"
    )


# ---------------------------------------------------------------------------
# /documents — 404 on unknown ID
# ---------------------------------------------------------------------------


async def test_get_document_unknown_id_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/documents/{_UNKNOWN_ID}")
    assert r.status_code == 404
    _assert_detail_str(r.json())


async def test_get_document_status_unknown_id_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/documents/{_UNKNOWN_ID}/status")
    assert r.status_code == 404
    _assert_detail_str(r.json())


async def test_delete_document_unknown_id_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete(f"/documents/{_UNKNOWN_ID}")
    assert r.status_code == 404
    _assert_detail_str(r.json())


async def test_patch_document_unknown_id_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch(f"/documents/{_UNKNOWN_ID}", json={"title": "New Title"})
    assert r.status_code == 404
    _assert_detail_str(r.json())


# ---------------------------------------------------------------------------
# /documents/ingest — 422 missing file, 400 unsupported type
# ---------------------------------------------------------------------------


async def test_ingest_missing_file_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/documents/ingest")
    assert r.status_code == 422


async def test_ingest_unsupported_extension_returns_400(test_db):
    """Uploading a .png file returns 400 with a clear {detail: str} message."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/documents/ingest",
            files={"file": ("image.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        )
    assert r.status_code == 400
    body = r.json()
    _assert_detail_str(body)
    assert "png" in body["detail"].lower() or "unsupported" in body["detail"].lower()


async def test_ingest_unsupported_binary_returns_400(test_db):
    """Uploading a .exe file returns 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/documents/ingest",
            files={"file": ("program.exe", b"MZ\x90\x00", "application/octet-stream")},
        )
    assert r.status_code == 400
    _assert_detail_str(r.json())


# ---------------------------------------------------------------------------
# /summarize — 404 on unknown doc, 422 on missing mode
# ---------------------------------------------------------------------------


async def test_summarize_unknown_doc_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/summarize/{_UNKNOWN_ID}",
            json={"mode": "one_sentence"},
        )
    assert r.status_code == 404
    _assert_detail_str(r.json())


async def test_summarize_missing_mode_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/summarize/{_UNKNOWN_ID}", json={})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /flashcards — 422 on missing fields, 404 on bad IDs
# ---------------------------------------------------------------------------


async def test_generate_flashcards_missing_document_id_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/flashcards/generate", json={})
    assert r.status_code == 422


async def test_update_flashcard_unknown_id_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/flashcards/{_UNKNOWN_ID}", json={"question": "Q?"})
    assert r.status_code == 404
    _assert_detail_str(r.json())


async def test_delete_flashcard_unknown_id_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete(f"/flashcards/{_UNKNOWN_ID}")
    assert r.status_code == 404
    _assert_detail_str(r.json())


async def test_review_flashcard_unknown_id_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/flashcards/{_UNKNOWN_ID}/review", json={"rating": "good"})
    assert r.status_code == 404
    _assert_detail_str(r.json())


# ---------------------------------------------------------------------------
# /notes — 422 on missing content, 404 on bad IDs
# ---------------------------------------------------------------------------


async def test_create_note_missing_content_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/notes", json={})
    assert r.status_code == 422


async def test_update_note_unknown_id_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/notes/{_UNKNOWN_ID}", json={"content": "updated"})
    assert r.status_code == 404
    _assert_detail_str(r.json())


async def test_delete_note_unknown_id_returns_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete(f"/notes/{_UNKNOWN_ID}")
    assert r.status_code == 404
    _assert_detail_str(r.json())


# ---------------------------------------------------------------------------
# /search — 422 on missing q
# ---------------------------------------------------------------------------


async def test_search_missing_query_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/search")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /qa — 422 on missing question
# ---------------------------------------------------------------------------


async def test_qa_missing_question_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/qa", json={})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /monitoring — graceful responses
# ---------------------------------------------------------------------------


async def test_monitoring_evals_returns_200_list(test_db):
    """GET /monitoring/evals returns 200 with an empty list when no runs exist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/monitoring/evals")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_monitoring_eval_history_returns_200_list(test_db):
    """GET /monitoring/eval-history returns 200 with a list (may be empty)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/monitoring/eval-history")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
