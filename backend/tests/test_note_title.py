"""NoteModel.title + title_auto_generated -- manual edit must not be overwritten."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app


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
    yield engine, factory
    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.anyio
async def test_new_note_starts_auto_generated_with_null_title(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/notes",
            json={"content": "Some body text", "tags": [], "document_id": None},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["title"] is None
        assert body["title_auto_generated"] is True


@pytest.mark.anyio
async def test_patch_title_flips_auto_flag_off(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        created = (
            await c.post(
                "/notes",
                json={"content": "hello", "tags": [], "document_id": None},
            )
        ).json()
        note_id = created["id"]

        patched = (
            await c.patch(f"/notes/{note_id}", json={"title": "My Custom Title"})
        ).json()
        assert patched["title"] == "My Custom Title"
        assert patched["title_auto_generated"] is False


@pytest.mark.anyio
async def test_patch_empty_title_clears_to_null(test_db):
    """Sending title='' (or whitespace) clears the title but still flips the
    auto flag off -- the user expressed intent to manage the title themselves.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        created = (
            await c.post(
                "/notes",
                json={"content": "hello", "tags": [], "document_id": None},
            )
        ).json()
        note_id = created["id"]

        await c.patch(f"/notes/{note_id}", json={"title": "A"})  # set
        cleared = (
            await c.patch(f"/notes/{note_id}", json={"title": "   "})
        ).json()
        assert cleared["title"] is None
        assert cleared["title_auto_generated"] is False


@pytest.mark.unstable
@pytest.mark.anyio
async def test_patch_other_fields_does_not_touch_title(test_db):
    """PATCH that omits `title` must leave the title + auto flag unchanged."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        created = (
            await c.post(
                "/notes",
                json={"content": "hello", "tags": [], "document_id": None},
            )
        ).json()
        note_id = created["id"]

        await c.patch(f"/notes/{note_id}", json={"title": "Pinned"})
        # Subsequent edit changes content + tags but not title.
        after = (
            await c.patch(
                f"/notes/{note_id}",
                json={"content": "new body", "tags": [f"tag-{uuid.uuid4().hex[:6]}"]},
            )
        ).json()
        assert after["title"] == "Pinned"
        assert after["title_auto_generated"] is False
