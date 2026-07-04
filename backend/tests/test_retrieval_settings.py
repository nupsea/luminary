"""GET/PATCH /settings/retrieval — the L3 reranker toggle (default ON)."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.services.settings_service import get_rerank_enabled, set_rerank_enabled


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


async def test_get_retrieval_defaults_on(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/settings/retrieval")
    assert resp.status_code == 200
    assert resp.json() == {"rerank_enabled": True}


async def test_patch_retrieval_roundtrip(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/settings/retrieval", json={"rerank_enabled": False})
        assert resp.status_code == 200
        assert resp.json() == {"rerank_enabled": False}
        again = await client.get("/settings/retrieval")
        assert again.json() == {"rerank_enabled": False}
        back = await client.patch("/settings/retrieval", json={"rerank_enabled": True})
        assert back.json() == {"rerank_enabled": True}


async def test_service_defaults_and_persistence(test_db):
    factory = test_db
    async with factory() as session:
        assert await get_rerank_enabled(session) is True
        await set_rerank_enabled(session, False)
    async with factory() as session:
        assert await get_rerank_enabled(session) is False
