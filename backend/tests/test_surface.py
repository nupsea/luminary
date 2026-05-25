import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.surface_manifest import enabled_routers, labs_surfaces


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LUMINARY_SURFACE_TIER", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def test_enabled_routers_tier_semantics():
    pub = enabled_routers("public", set())
    assert "documents" in pub
    assert "feynman" not in pub
    assert "evals" not in pub

    dev = enabled_routers("dev", set())
    assert {"feynman", "evals", "admin"} <= dev

    assert "feynman" not in enabled_routers("labs", set())
    assert "feynman" in enabled_routers("labs", {"feynman"})


def test_labs_surfaces_have_descriptions():
    for s in labs_surfaces():
        assert s.get("description"), f"labs surface {s['id']} missing description"


async def test_get_surface_defaults(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/settings/surface")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "dev"
    assert data["labs_enabled"] == []
    assert "feynman" in {s["id"] for s in data["available_labs"]}


async def test_patch_labs_roundtrip(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/settings/labs", json={"labs_enabled": ["feynman"]})
        assert resp.status_code == 200
        assert resp.json()["labs_enabled"] == ["feynman"]
        again = await client.get("/settings/surface")
        assert again.json()["labs_enabled"] == ["feynman"]


async def test_patch_labs_rejects_unknown(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/settings/labs", json={"labs_enabled": ["not_a_surface"]})
    assert resp.status_code == 400
