"""A polite HTTP client for connectors: a named user agent, a delay between requests, retries
on a dropped connection, and failures turned into `ConnectorError`s the core can show.

Standard library only (`urllib`), like the rest of the SDK.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from luminary_source_sdk.connector import ConnectorError


class PoliteClient:
    """GETs one request at a time, at least `delay_s` apart.

    A connection that drops or times out is retried `retries` times, `backoff_s` longer each
    time; an HTTP answer (403, 404) is never retried. `messages` replaces the text of an HTTP
    status the user should read differently ("the page is missing or not public").
    """

    def __init__(
        self,
        user_agent: str,
        *,
        delay_s: float = 0.0,
        retries: int = 0,
        backoff_s: float = 2.0,
        timeout_s: float = 30.0,
        messages: dict[int, str] | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.delay_s = delay_s
        self.retries = retries
        self.backoff_s = backoff_s
        self.timeout_s = timeout_s
        self.messages = messages or {}
        self._last = 0.0

    def get_text(self, url: str) -> tuple[str, str]:
        """(the URL after redirects, the body decoded by its charset)."""
        final, body, charset = self._get(url, {})
        return final, body.decode(charset or "utf-8", errors="replace")

    def get_json(self, url: str) -> Any:
        _, body, charset = self._get(url, {"Accept": "application/json"})
        try:
            return json.loads(body.decode(charset or "utf-8"))
        except ValueError as exc:
            raise ConnectorError("source", f"{url} did not answer JSON: {exc}") from exc

    def _get(self, url: str, headers: dict[str, str]) -> tuple[str, bytes, str | None]:
        for attempt in range(self.retries + 1):
            try:
                return self._get_once(url, headers)
            except (urllib.error.URLError, TimeoutError) as exc:
                if isinstance(exc, urllib.error.HTTPError):
                    raise self._refusal(url, exc.code) from exc
                if attempt == self.retries:
                    raise ConnectorError("source", f"could not reach {url}: {exc}") from exc
                time.sleep(self.backoff_s * (attempt + 1))
        raise AssertionError("unreachable")

    def _get_once(self, url: str, headers: dict[str, str]) -> tuple[str, bytes, str | None]:
        wait = self._last + self.delay_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, **headers})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return resp.geturl(), resp.read(), resp.headers.get_content_charset()
        finally:
            self._last = time.monotonic()

    def _refusal(self, url: str, status: int) -> ConnectorError:
        detail = self.messages.get(status)
        message = f"{url} answered {status}" + (f": {detail}" if detail else "")
        return ConnectorError("auth" if status == 401 else "source", message)
