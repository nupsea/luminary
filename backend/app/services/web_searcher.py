"""Web search service for optional per-conversation web augmentation

Dispatches to the configured provider (none/brave/tavily/duckduckgo).
Privacy invariant: web snippets are NEVER stored in the database.
All errors are caught and logged; returns [] on any provider failure.
"""

import logging
import re
from urllib.parse import urlparse

from app.config import get_settings
from app.types import WebSnippet

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pure helper functions (no I/O)
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(
    r"\b(Python\s+\d+\.\d+|React\s+\d+|Node\.js\s+\d+|"
    r"v\d+\.\d+(?:\.\d+)?|"
    r"version\s+\d+\.\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)


def _extract_domain(url: str) -> str:
    """Extract domain from a URL, stripping www. prefix.

    Examples:
        "https://www.docs.python.org/3/..." -> "docs.python.org"
        "https://realpython.com/asyncio/" -> "realpython.com"
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or ""
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return url


def _truncate_content(text: str, max_chars: int = 500) -> str:
    """Truncate text to max_chars, ending at a word boundary."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        return truncated[:last_space]
    return truncated


def _detect_version_info(text: str) -> str:
    """Extract the first version signal from text.

    Matches patterns like 'Python 3.12', 'React 18', 'v2.0', 'version 1.5'.
    Returns the first match or '' if none detected.
    """
    m = _VERSION_RE.search(text or "")
    if m:
        return m.group(0)
    return ""


def _classify_source_quality(url: str, title: str) -> str:
    """Classify source quality based on URL and title heuristics."""
    domain = _extract_domain(url).lower()
    title_lower = (title or "").lower()
    if any(
        d in domain
        for d in (
            "docs.python.org",
            "developer.mozilla.org",
            "docs.rust-lang.org",
            "docs.microsoft.com",
            "developer.apple.com",
            "docs.oracle.com",
            "reactjs.org",
            "vuejs.org",
            "angular.io",
            "nodejs.org",
            "golang.org",
            "kotlinlang.org",
        )
    ):
        return "official_docs"
    if any(d in domain for d in ("spec.whatwg.org", "w3.org", "ecma-international.org")):
        return "spec"
    if "wikipedia.org" in domain:
        return "wiki"
    if any(
        kw in domain or kw in title_lower for kw in ("blog", "medium.com", "dev.to", "hashnode")
    ):
        return "blog"
    return "unknown"


# ---------------------------------------------------------------------------
# WebSearcher service
# ---------------------------------------------------------------------------


class WebSearcher:
    """Dispatch web search to the configured provider.

    provider='none'       -- always returns [] silently (default)
    provider='brave'      -- calls Brave Search API (requires BRAVE_API_KEY)
    provider='tavily'     -- calls Tavily Search API (requires TAVILY_API_KEY)
    provider='duckduckgo' -- uses duckduckgo_search library (no key required)

    All provider failures are caught and logged; returns [] on any error.
    Content is NOT stored in the database per privacy invariant
    """

    async def search(self, query: str, k: int = 3) -> list[WebSnippet]:
        """Return up to k WebSnippet results for the query.

        Returns [] if provider='none' or on any provider error.
        """
        cfg = get_settings()
        provider = cfg.WEB_SEARCH_PROVIDER

        if provider == "none":
            logger.debug("web_searcher: provider=none -- skipping web search")
            return []

        if provider == "duckduckgo":
            return await self._search_duckduckgo(query, k)

        if provider == "brave":
            return await self._search_brave(query, k, cfg.BRAVE_API_KEY)

        if provider == "tavily":
            return await self._search_tavily(query, k, cfg.TAVILY_API_KEY)

        logger.warning("web_searcher: unknown provider=%r -- returning []", provider)
        return []

    async def _search_duckduckgo(self, query: str, k: int) -> list[WebSnippet]:
        try:
            from duckduckgo_search import DDGS  # type: ignore[import-untyped]

            results = []
            ddgs = DDGS()
            raw = ddgs.text(query, max_results=k)
            for item in raw or []:
                url = item.get("href") or item.get("url") or ""
                title = item.get("title") or ""
                body = item.get("body") or ""
                content = _truncate_content(body)
                domain = _extract_domain(url)
                results.append(
                    WebSnippet(
                        url=url,
                        title=title,
                        content=content,
                        source_quality=_classify_source_quality(url, title),
                        version_info=_detect_version_info(body),
                        domain=domain,
                    )
                )
            logger.info("web_searcher: duckduckgo returned %d results", len(results))
            return results
        except ImportError:
            logger.warning(
                "web_searcher: duckduckgo_search not installed; "
                "run 'cd backend && uv add duckduckgo-search'"
            )
            return []
        except Exception:
            logger.warning("web_searcher: duckduckgo search failed", exc_info=True)
            return []

    async def _search_brave(self, query: str, k: int, api_key: str) -> list[WebSnippet]:
        if not api_key:
            logger.warning(
                "web_searcher: provider=brave but BRAVE_API_KEY is empty -- returning []"
            )
            return []
        try:
            import httpx  # type: ignore[import-untyped]

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": k},
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                )
                if resp.status_code != 200:
                    logger.warning("web_searcher: brave API returned %d", resp.status_code)
                    return []
                data = resp.json()
                results = []
                for item in (data.get("web", {}).get("results") or [])[:k]:
                    url = item.get("url") or ""
                    title = item.get("title") or ""
                    description = item.get("description") or ""
                    content = _truncate_content(description)
                    domain = _extract_domain(url)
                    results.append(
                        WebSnippet(
                            url=url,
                            title=title,
                            content=content,
                            source_quality=_classify_source_quality(url, title),
                            version_info=_detect_version_info(description),
                            domain=domain,
                        )
                    )
                logger.info("web_searcher: brave returned %d results", len(results))
                return results
        except Exception:
            logger.warning("web_searcher: brave search failed", exc_info=True)
            return []

    async def _search_tavily(self, query: str, k: int, api_key: str) -> list[WebSnippet]:
        if not api_key:
            logger.warning(
                "web_searcher: provider=tavily but TAVILY_API_KEY is empty -- returning []"
            )
            return []
        try:
            import httpx  # type: ignore[import-untyped]

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"query": query, "max_results": k},
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code != 200:
                    logger.warning("web_searcher: tavily API returned %d", resp.status_code)
                    return []
                data = resp.json()
                results = []
                for item in (data.get("results") or [])[:k]:
                    url = item.get("url") or ""
                    title = item.get("title") or ""
                    description = item.get("content") or item.get("snippet") or ""
                    content = _truncate_content(description)
                    domain = _extract_domain(url)
                    results.append(
                        WebSnippet(
                            url=url,
                            title=title,
                            content=content,
                            source_quality=_classify_source_quality(url, title),
                            version_info=_detect_version_info(description),
                            domain=domain,
                        )
                    )
                logger.info("web_searcher: tavily returned %d results", len(results))
                return results
        except Exception:
            logger.warning("web_searcher: tavily search failed", exc_info=True)
            return []


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_web_searcher: WebSearcher | None = None


def get_web_searcher() -> WebSearcher:
    global _web_searcher  # noqa: PLW0603
    if _web_searcher is None:
        _web_searcher = WebSearcher()
    return _web_searcher
