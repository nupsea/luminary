"""Integration tests for O'Reilly router and auto-detection in /documents/ingest-url."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.oreilly_service import delete_oreilly_cookies


@pytest.fixture(autouse=True)
def clean_cookies():
    delete_oreilly_cookies()
    yield
    delete_oreilly_cookies()


@pytest.mark.asyncio
async def test_oreilly_status_unconfigured():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/oreilly/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["valid"] is False


@pytest.mark.asyncio
async def test_oreilly_set_cookies_invalid():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Empty cookies
        resp = await client.post("/oreilly/cookies", json={"cookies": ""})
        assert resp.status_code == 400

        # 2. Cookies that fail session validation
        with patch(
            "app.services.oreilly_service.OreillyClient.validate_session",
            return_value=(False, "Expired"),
        ):
            resp = await client.post("/oreilly/cookies", json={"cookies": "_abck=badtoken"})
            assert resp.status_code == 401


@pytest.mark.asyncio
async def test_oreilly_set_cookies_valid_and_status():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "app.services.oreilly_service.OreillyClient.validate_session",
            return_value=(True, "learner@example.com"),
        ):
            resp = await client.post(
                "/oreilly/cookies",
                json={"cookies": [{"name": "_abck", "value": "goodtoken"}]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["valid"] is True
            assert data["user"] == "learner@example.com"

        # Check status now reflects active configuration
        with patch(
            "app.services.oreilly_service.OreillyClient.validate_session",
            return_value=(True, "learner@example.com"),
        ):
            resp = await client.get("/oreilly/status")
            assert resp.status_code == 200
            assert resp.json()["configured"] is True
            assert resp.json()["valid"] is True

        # Delete cookies
        resp = await client.delete("/oreilly/cookies")
        assert resp.status_code == 200

        resp = await client.get("/oreilly/status")
        assert resp.json()["configured"] is False


@pytest.mark.asyncio
async def test_oreilly_preview_unconfigured():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/oreilly/preview",
            json={"url": "https://learning.oreilly.com/library/view/ddia/9781491903063/"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_url_auto_detects_oreilly_unconfigured():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest-url",
            json={"url": "https://learning.oreilly.com/library/view/ddia/9781491903063/"},
        )
        # Without cookies configured, it immediately warns the user
        assert resp.status_code == 401
        assert "O'Reilly subscription cookies not configured" in resp.json()["detail"]
