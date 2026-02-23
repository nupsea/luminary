import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_settings_masks_api_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-key-value")
    # Clear the lru_cache to pick up monkeypatched env
    from app.config import get_settings

    get_settings.cache_clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/settings")
    get_settings.cache_clear()
    assert response.status_code == 200
    body = response.json()
    assert body["OPENAI_API_KEY"] == "sk-s***"
    assert "secret" not in body["OPENAI_API_KEY"]
