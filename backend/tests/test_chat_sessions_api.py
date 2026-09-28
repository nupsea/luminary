from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _create_session(client: AsyncClient, **overrides) -> dict:
    body = {
        "scope": "single",
        "document_ids": ["doc-1"],
        "model": "llama3.2:latest",
        **overrides,
    }
    resp = await client.post("/chat/sessions", json=body)
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_patch_model_updates_session(test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sess = await _create_session(client)
        resp = await client.patch(f"/chat/sessions/{sess['id']}", json={"model": "openai/gpt-4o"})
        assert resp.status_code == 200
        assert resp.json()["model"] == "openai/gpt-4o"

        detail = await client.get(f"/chat/sessions/{sess['id']}")
        assert detail.json()["model"] == "openai/gpt-4o"


@pytest.mark.asyncio
async def test_patch_model_null_resets_to_default(test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sess = await _create_session(client)
        resp = await client.patch(f"/chat/sessions/{sess['id']}", json={"model": None})
        assert resp.status_code == 200
        assert resp.json()["model"] is None


@pytest.mark.asyncio
async def test_patch_title_and_model_together(test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sess = await _create_session(client)
        resp = await client.patch(
            f"/chat/sessions/{sess['id']}",
            json={"title": "Odyssey deep dive", "model": "mistral:7b"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "Odyssey deep dive"
        assert body["model"] == "mistral:7b"


@pytest.mark.asyncio
async def test_patch_empty_body_rejected(test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sess = await _create_session(client)
        resp = await client.patch(f"/chat/sessions/{sess['id']}", json={})
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_model_missing_session_404(test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/chat/sessions/nope", json={"model": "mistral:7b"})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_session_returns_scope_docs_model(test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sess = await _create_session(client, scope="all", document_ids=[], model=None)
        detail = await client.get(f"/chat/sessions/{sess['id']}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["scope"] == "all"
        assert body["document_ids"] == []
        assert body["model"] is None
