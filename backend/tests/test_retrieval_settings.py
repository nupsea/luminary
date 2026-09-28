"""GET/PATCH /settings/retrieval — the L3 reranker toggle (default ON)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.settings_service import get_rerank_enabled, set_rerank_enabled


@pytest.fixture
def test_db(memory_db):
    return memory_db.factory


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
