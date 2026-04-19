"""Unit tests for web_searcher service and GET /settings/web-search endpoint (S142).

All tests are pure-function or mocked -- no real HTTP calls.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.services.web_searcher import (
    WebSearcher,
    _detect_version_info,
    _extract_domain,
    _truncate_content,
)

# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


def test_extract_domain_strips_www():
    python_url = "https://www.docs.python.org/3/library/asyncio.html"
    assert _extract_domain(python_url) == "docs.python.org"
    assert _extract_domain("https://realpython.com/python-asyncio/") == "realpython.com"
    mozilla_url = "https://developer.mozilla.org/en-US/"
    assert _extract_domain(mozilla_url) == "developer.mozilla.org"


def test_extract_domain_no_www():
    assert _extract_domain("https://github.com/org/repo") == "github.com"


def test_truncate_content_caps_at_500():
    long_text = "a " * 400  # 800 chars
    result = _truncate_content(long_text, max_chars=500)
    assert len(result) <= 500


def test_truncate_content_preserves_short_text():
    short = "hello world"
    assert _truncate_content(short, max_chars=500) == short


def test_truncate_content_ends_at_word_boundary():
    text = "hello world foo"
    result = _truncate_content(text, max_chars=8)
    # Should end at a word boundary -- either "hello" or "hello wo"
    assert not result.endswith(" ")


def test_detect_version_info_finds_python_version():
    assert _detect_version_info("Python 3.12 introduced ExceptionGroup") == "Python 3.12"
    assert _detect_version_info("We cover python 3.9 features here") == "python 3.9"


def test_detect_version_info_finds_react_version():
    assert _detect_version_info("React 18 concurrent features") == "React 18"


def test_detect_version_info_finds_semver():
    assert _detect_version_info("Release v2.1.3 of the library") == "v2.1.3"


def test_detect_version_info_empty_for_no_match():
    assert _detect_version_info("No version here") == ""
    assert _detect_version_info("") == ""


# ---------------------------------------------------------------------------
# WebSearcher.search() with provider=none
# ---------------------------------------------------------------------------


def test_search_returns_empty_when_provider_none():
    """provider=none must return [] without any network call."""
    mock_settings = SimpleNamespace(WEB_SEARCH_PROVIDER="none", BRAVE_API_KEY="", TAVILY_API_KEY="")
    with patch("app.services.web_searcher.get_settings", return_value=mock_settings):
        searcher = WebSearcher()
        result = asyncio.run(searcher.search("python asyncio", k=3))
    assert result == []


@pytest.mark.asyncio
async def test_search_with_mocked_duckduckgo():
    """Mocked duckduckgo provider returns correctly shaped WebSnippet list."""
    mock_settings = SimpleNamespace(
        WEB_SEARCH_PROVIDER="duckduckgo", BRAVE_API_KEY="", TAVILY_API_KEY=""
    )

    with (
        patch("app.services.web_searcher.get_settings", return_value=mock_settings),
        patch(
            "app.services.web_searcher.WebSearcher._search_duckduckgo", new_callable=AsyncMock
        ) as mock_search,
    ):
        from app.types import WebSnippet

        mock_search.return_value = [
            WebSnippet(
                url="https://docs.python.org/3/library/asyncio.html",
                title="asyncio — Python 3.12 docs",
                content="The asyncio module provides infrastructure for writing single-threaded"
                " concurrent code using coroutines. Python 3.12 improved this.",
                source_quality="official_docs",
                version_info="Python 3.12",
                domain="docs.python.org",
            )
        ]
        searcher = WebSearcher()
        result = await searcher.search("python asyncio", k=3)

    assert len(result) == 1
    snippet = result[0]
    assert snippet["url"] == "https://docs.python.org/3/library/asyncio.html"
    assert snippet["title"] == "asyncio — Python 3.12 docs"
    assert snippet["domain"] == "docs.python.org"
    assert "url" in snippet
    assert "title" in snippet
    assert "content" in snippet
    assert "source_quality" in snippet
    assert len(snippet["content"]) <= 500


@pytest.mark.asyncio
async def test_search_with_provider_none_no_network():
    """provider=none never calls any network method."""
    mock_settings = SimpleNamespace(WEB_SEARCH_PROVIDER="none", BRAVE_API_KEY="", TAVILY_API_KEY="")

    _ddg_path = "app.services.web_searcher.WebSearcher._search_duckduckgo"
    _brave_path = "app.services.web_searcher.WebSearcher._search_brave"
    _tavily_path = "app.services.web_searcher.WebSearcher._search_tavily"
    with (
        patch("app.services.web_searcher.get_settings", return_value=mock_settings),
        patch(_ddg_path, new_callable=AsyncMock) as mock_ddg,
        patch(_brave_path, new_callable=AsyncMock) as mock_brave,
        patch(_tavily_path, new_callable=AsyncMock) as mock_tavily,
    ):
        searcher = WebSearcher()
        result = await searcher.search("test query", k=3)

    assert result == []
    mock_ddg.assert_not_called()
    mock_brave.assert_not_called()
    mock_tavily.assert_not_called()


# ---------------------------------------------------------------------------
# GET /settings/web-search API endpoint (invariant #9: every new endpoint needs a test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_web_search_settings_returns_provider_and_enabled_when_none():
    """GET /settings/web-search returns provider=none and enabled=False by default."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/settings/web-search")

    assert resp.status_code == 200
    data = resp.json()
    assert "provider" in data
    assert "enabled" in data
    assert isinstance(data["enabled"], bool)
    # Default config has WEB_SEARCH_PROVIDER="none" so enabled must be False
    assert data["provider"] == "none"
    assert data["enabled"] is False


@pytest.mark.asyncio
async def test_get_web_search_settings_enabled_true_when_provider_set(monkeypatch):
    """GET /settings/web-search returns enabled=True when provider is not 'none'."""
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "duckduckgo")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import app

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/settings/web-search")

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "duckduckgo"
        assert data["enabled"] is True
    finally:
        get_settings.cache_clear()
