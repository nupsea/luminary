"""A three-chapter O'Reilly book served by a stand-in for `OreillyClient`'s network calls."""

from __future__ import annotations

import html
import json
from pathlib import Path

BOOK_ID = "9781098100001"
BOOK_URL = f"https://learning.oreilly.com/library/view/fixture-systems/{BOOK_ID}/"
_FILES = f"https://learning.oreilly.com/api/v2/epubs/urn:orm:book:{BOOK_ID}/files"
COVER_URL = f"https://learning.oreilly.com/covers/urn:orm:book:{BOOK_ID}/1200w/"
COVER_BYTES = b"\xff\xd8\xff\xe0cover"
FIGURE_BYTES = b"\x89PNG\r\n\x1a\nfigure"

METADATA = {
    "id": BOOK_ID,
    "title": "Fixture Systems",
    "authors": ["Ada Author"],
    "publishers": ["O'Reilly Media, Inc."],
    "description": "How storage and replication fit together.",
    "cover_url": COVER_URL,
    "isbn": BOOK_ID,
}

_HTML = {
    "preface01.html": (
        "<h1>Preface</h1><p>This preface says who the book is for and what each chapter covers.</p>"
    ),
    "ch01.html": (
        '<h1>1. Storage</h1><p id="logs">A log is an append-only sequence of records on disk.</p>'
        "<h2>Indexes</h2><p>An index is extra structure derived from the primary data.</p>"
        '<img src="figs/f1.png" alt="An LSM tree"/>'
    ),
    "ch02.html": (
        "<h1>2. Replication</h1><p>Replication keeps a copy of the same data on several machines,"
        f' building on <a href="/library/view/fixture-systems/{BOOK_ID}/ch01.html#logs">logs</a>.'
        "</p><h2>Leaders and Followers</h2>"
        "<p>Every write goes to the leader, which streams it on.</p>"
    ),
}

CHAPTERS = [
    {
        "title": title,
        "filename": name,
        "content_url": f"{_FILES}/{name}",
        "reference_id": f"{BOOK_ID}:{name}",
        "images": [],
        "virtual_pages": 4,
        "minutes_required": minutes,
        "order": i,
    }
    for i, (title, name, minutes) in enumerate(
        [
            ("Preface", "preface01.html", 3.5),
            ("1. Storage", "ch01.html", 12.0),
            ("2. Replication", "ch02.html", 15.25),
        ]
    )
]


class FixtureBookClient:
    """Answers `OreillyClient`'s network calls; `failing` names chapter files that error."""

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.failing = failing
        self.fetched: list[str] = []

    def is_configured(self) -> bool:
        return True

    def fetch_book_metadata(self, book_id: str) -> dict:
        assert book_id == BOOK_ID
        return dict(METADATA)

    def fetch_chapter_list(self, book_id: str) -> list[dict]:
        assert book_id == BOOK_ID
        return [dict(ch) for ch in CHAPTERS]

    def fetch_chapter_html(self, content_url: str) -> str:
        self.fetched.append(content_url)
        name = content_url.rsplit("/", 1)[-1]
        if name in self.failing:
            raise ConnectionError("connection reset")
        return f'<html><body><div id="sbo-rt-content">{_HTML[name]}</div></body></html>'

    def fetch_bytes(self, url: str) -> bytes:
        self.fetched.append(url)
        if url == COVER_URL:
            return COVER_BYTES
        if url.endswith("/figs/f1.png"):
            return FIGURE_BYTES
        raise AssertionError(f"unexpected fetch {url}")


def write_book_bundle(dest: Path, client: FixtureBookClient) -> Path:
    """The book as the O'Reilly connector writes it: each chapter wrapped as `build_epub`
    wraps it, its figures under `assets/images/`, the cover in `assets/`."""
    from app.services.oreilly_service import _chapter_file_name, process_chapter_html

    meta = client.fetch_book_metadata(BOOK_ID)
    sections, taken, figures = [], set(), {}
    (dest / "sections").mkdir(parents=True)
    for index, ch in enumerate(client.fetch_chapter_list(BOOK_ID)):
        url = ch["content_url"]
        body, found = process_chapter_html(client.fetch_chapter_html(url), BOOK_ID, url)
        stem = Path(_chapter_file_name(ch["filename"], index, taken)).stem
        (dest / "sections" / f"{stem}.xhtml").write_text(
            '<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" lang="en">\n'
            f"<head><title>{html.escape(ch['title'])}</title></head>\n<body>\n{body}\n</body>\n"
            "</html>",
            encoding="utf-8",
        )
        sections.append(
            {"id": stem, "heading": ch["title"], "level": 1, "file": f"sections/{stem}.xhtml"}
        )
        figures.update(found)
    (dest / "assets" / "images").mkdir(parents=True)
    for url, local in figures.items():
        (dest / "assets" / "images" / local).write_bytes(client.fetch_bytes(url))
    (dest / "assets" / "cover.jpg").write_bytes(client.fetch_bytes(meta["cover_url"]))
    manifest = {
        "bundle_version": 1,
        "connector": {"name": "oreilly", "version": "0.1.0"},
        "title": meta["title"],
        "authors": meta["authors"],
        "cover": "assets/cover.jpg",
        "source_url": BOOK_URL,
        "locator": BOOK_ID,
        "media": {"kind": "text"},
        "terms": {
            "statement": "O'Reilly's Membership Agreement grants access for personal use only.",
            "url": "https://www.oreilly.com/membership-agreement/",
        },
        "sections": sections,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return dest
