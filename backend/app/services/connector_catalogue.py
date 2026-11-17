"""Connectors a user can install from the app, each pinned to an archive by sha256 (#437).

An entry is a reviewed connector at one commit: its source archive, the folder in it, and the
licence and source terms shown before the install starts. Install only on the user's action,
into the connector's own environment, with exactly its `uv.lock`; a tampered archive is refused
before anything is unpacked (`component_download`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.exceptions import DependencyUnavailable, NotFound
from app.services import connectors
from app.services.component_download import install_archive_subset
from app.services.components import install_component, resolve_tool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogueEntry:
    name: str
    label: str
    version: str
    summary: str
    licence: str
    terms_statement: str
    terms_url: str
    repository: str
    archive_url: str
    sha256: str
    size_bytes: int
    # The connector's folder inside the archive, with the archive's top directory.
    member_prefix: str


_CONNECTORS_COMMIT = "d94285083136732bde78d02e433594686f0920df"
_YOUTUBE_TERMS = (
    "YouTube's Terms of Service say you may not \"access, reproduce, download, distribute, "
    "transmit, broadcast, display, sell, license, alter, modify or otherwise use any part of the "
    "Service or any Content except: (a) as expressly authorized by the Service; (b) with prior "
    'written permission from YouTube and, if applicable, the respective rights holders", nor '
    '"access the Service using any automated means (such as robots, botnets or scrapers) except '
    "(a) in the case of public search engines, in accordance with YouTube's robots.txt file; or "
    "(b) with YouTube's prior written permission\". Downloading a video with this connector is "
    "between you and YouTube."
)

# html-book and confluence (#348), reviewed at this commit; youtube/ is identical in both.
_BOOKS_COMMIT = "d2ae78a1f11382cfc835888363dc3aa4ee8d1b20"
_BOOKS_SHA256 = "c09b6e41feef36a0d3b0a947c20f80993a134c9461a58daadff660030a7473fb"
_BOOKS_SIZE = 55842
_HTML_BOOK_TERMS = (
    "Each book this connector takes is published under a licence that allows copying it. "
    'The Rust project: "the Rust Programming Language and all other official projects, '
    'including this website, are generally dual-licensed" under Apache-2.0 and MIT, and '
    "doc.rust-lang.org's robots.txt allows /book/. The Python documentation: \"This page is "
    'licensed under the Python Software Foundation License Version 2" '
    "(https://docs.python.org/3/copyright.html), and docs.python.org's robots.txt allows "
    "/3/. Neither site's terms say anything about automated download or use as model input."
)
_CONFLUENCE_TERMS = (
    "The Linux Foundation's Terms of Use (revised November 16, 2020), which cover its "
    'project wikis: "Except as otherwise provided, Content on this site is licensed under a '
    'Creative Commons Attribution 3.0 License", and non-code submissions including wikis '
    '"will be governed by the Creative Commons Attribution 3.0". lf-hyperledger.atlassian.net '
    "allows /wiki/ in robots.txt with a crawl delay of 1 second. The terms say nothing about "
    "automated download or use as model input."
)

_ENTRIES = (
    CatalogueEntry(
        name="youtube",
        label="YouTube",
        version="0.1.0",
        summary="A talk's audio, its uploader's captions and description; Luminary transcribes "
        "and cites it.",
        licence="Apache-2.0",
        terms_statement=_YOUTUBE_TERMS,
        terms_url="https://www.youtube.com/t/terms",
        repository="https://github.com/nupsea/luminary-connectors",
        archive_url=f"https://github.com/nupsea/luminary-connectors/archive/{_CONNECTORS_COMMIT}.tar.gz",
        sha256="73e430a944d292ee941b61fb127b854385f4426a45ff046c3fee80003ad3de80",
        size_bytes=30547,
        member_prefix=f"luminary-connectors-{_CONNECTORS_COMMIT}/youtube/",
    ),
    CatalogueEntry(
        name="html-book",
        label="HTML book",
        version="0.1.0",
        summary="A book published as web pages (the Rust book, the Python tutorial), each page "
        "a section in reading order.",
        licence="Apache-2.0",
        terms_statement=_HTML_BOOK_TERMS,
        terms_url="https://www.rust-lang.org/policies/licenses",
        repository="https://github.com/nupsea/luminary-connectors",
        archive_url=f"https://github.com/nupsea/luminary-connectors/archive/{_BOOKS_COMMIT}.tar.gz",
        sha256=_BOOKS_SHA256,
        size_bytes=_BOOKS_SIZE,
        member_prefix=f"luminary-connectors-{_BOOKS_COMMIT}/html-book/",
    ),
    CatalogueEntry(
        name="confluence",
        label="Confluence",
        version="0.1.0",
        summary="A public Confluence page and every page under it, each a section in tree order.",
        licence="Apache-2.0",
        terms_statement=_CONFLUENCE_TERMS,
        terms_url="https://www.linuxfoundation.org/legal/terms",
        repository="https://github.com/nupsea/luminary-connectors",
        archive_url=f"https://github.com/nupsea/luminary-connectors/archive/{_BOOKS_COMMIT}.tar.gz",
        sha256=_BOOKS_SHA256,
        size_bytes=_BOOKS_SIZE,
        member_prefix=f"luminary-connectors-{_BOOKS_COMMIT}/confluence/",
    ),
)


def catalogue_entries() -> tuple[CatalogueEntry, ...]:
    return _ENTRIES


def get_entry(name: str) -> CatalogueEntry:
    for entry in catalogue_entries():
        if entry.name == name:
            return entry
    raise NotFound(f"No catalogue connector named {name!r}")


async def install_entry(name: str) -> AsyncIterator[dict]:
    """Install a catalogue connector, streaming `component_download` events; the last is
    `ready` or `failed`. uv is fetched first when the machine has none."""
    entry = get_entry(name)
    if resolve_tool("uv") is None:
        async for event in install_component("uv"):
            if event["state"] == "failed":
                yield {
                    **event,
                    "detail": f"Could not fetch the connector installer: {event['detail']}",
                }
                return
            if event["state"] != "ready":
                yield event
    source = connectors.connectors_root() / entry.name / "source"
    async for event in install_archive_subset(
        url=entry.archive_url,
        sha256=entry.sha256,
        archive_path=connectors.connectors_root()
        / ".downloads"
        / f"{entry.name}-{entry.version}.tar.gz",
        member_prefix=entry.member_prefix,
        target=source,
        total_bytes=entry.size_bytes,
        label=entry.label,
    ):
        if event["state"] == "failed":
            yield event
            return
        if event["state"] != "ready":
            yield event
    yield {"state": "downloading", "detail": f"Building {entry.label}'s environment"}
    try:
        installed = await connectors.install_from_folder(source, locked=True)
        _check_matches(entry, installed.description)
    except (connectors.ConnectorInstallFailed, DependencyUnavailable) as exc:
        logger.warning("Catalogue install of %s failed: %s", name, exc.detail)
        yield {"state": "failed", "detail": exc.detail}
        return
    yield {"state": "ready", "detail": f"{entry.label} {entry.version} installed"}


def _check_matches(entry: CatalogueEntry, description: dict) -> None:
    """What was installed is what the catalogue showed: a connector whose name, version or
    terms differ from its entry is removed again, since the user agreed to the entry's."""
    terms = description.get("terms") or {}
    shown = (entry.name, entry.version, entry.terms_url, entry.terms_statement)
    got = (description.get("name"), description.get("version"), terms.get("url"),
           terms.get("statement"))  # fmt: skip
    if got != shown:
        connectors.uninstall(entry.name)
        raise connectors.ConnectorInstallFailed(
            f"{entry.label} from the catalogue does not describe itself as its entry does"
        )
