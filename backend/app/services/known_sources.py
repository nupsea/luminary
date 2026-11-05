"""Links to a source the core no longer imports itself, and which connector takes them (#467).

A pasted YouTube or O'Reilly link that no installed connector claims is refused with what to
install, or the file to import instead. Never the web-article extractor, which would read the
site's page as an article (#430).
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.exceptions import InvalidInput


class ConnectorNeeded(InvalidInput):
    """`connector` in the body names what to install; `catalogue` whether Settings offers it."""


# host -> (source, connector, in the catalogue, the file a user can import instead)
_KNOWN = {
    "www.youtube.com": ("YouTube", "youtube", True, "the talk's audio or video file"),
    "youtube.com": ("YouTube", "youtube", True, "the talk's audio or video file"),
    "m.youtube.com": ("YouTube", "youtube", True, "the talk's audio or video file"),
    "youtu.be": ("YouTube", "youtube", True, "the talk's audio or video file"),
    "learning.oreilly.com": ("O'Reilly", "oreilly", False, "the book's EPUB"),
    "www.oreilly.com": ("O'Reilly", "oreilly", False, "the book's EPUB"),
    "oreilly.com": ("O'Reilly", "oreilly", False, "the book's EPUB"),
}


def refuse_unclaimed(url: str) -> None:
    """Raise `ConnectorNeeded` for a link only a connector can import; else return."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    known = _KNOWN.get(host)
    if known is None:
        return
    if host in ("www.oreilly.com", "oreilly.com") and not parsed.path.startswith("/library/"):
        return  # oreilly.com's own articles are web pages, which the article path reads
    source, connector, offered, instead = known
    where = (
        "install it in Settings → Connectors"
        if offered
        else "install it from its folder (python -m app.scripts.install_connector)"
    )
    raise ConnectorNeeded(
        f"{source} links come in through the {source} connector: {where}, or import {instead}.",
        connector=connector,
        catalogue=offered,
    )
