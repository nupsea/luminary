"""A three-chapter O'Reilly book served by a stand-in for `OreillyClient`'s network calls."""

from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from ebooklib import epub

_BASE_URL = "https://learning.oreilly.com"
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

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
        "description": meta["description"],
        "labels": ["oreilly", "Tech Book", "oreilly"],
        "sections": sections,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return dest


# What Luminary's built-in O'Reilly import wrote, kept so EPUB-era books stay tested (#467): the
# connector writes the same chapters into a bundle (`write_book_bundle`).


def _asset_name(url: str) -> str:
    """A local file name for a remote asset, unique per source URL.

    Figures from different chapters routinely share a base name ("figure1.png");
    keyed by base name alone, the last download silently replaced the others.
    """
    base = unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "asset"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]  # noqa: S324 - a name, not a MAC
    return f"{digest}-{_UNSAFE_FILENAME_CHARS.sub('_', base)}"


def _chapter_file_name(filename: str, index: int, taken: set[str]) -> str:
    """The chapter's own name as .xhtml, so the book's cross-references still resolve.

    The suffix matters: ebooklib types a `.html` item as text/html rather than a
    document, and the parser only reads documents, so the chapter would vanish.
    """
    stem = _UNSAFE_FILENAME_CHARS.sub("_", Path(filename).stem) if filename else ""
    name = f"{stem}.xhtml" if stem else f"chapter_{index + 1:03d}.xhtml"
    if name in taken:
        name = f"{Path(name).stem}_{index + 1:03d}.xhtml"
    taken.add(name)
    return name


def _in_book_href(href: str, book_id: str) -> str:
    """A link into the same book, pointed at the chapter file the EPUB stores."""
    path, sep, fragment = href.rsplit(book_id, maxsplit=1)[-1].partition("#")
    name = Path(path).name
    if name:
        name = f"{_UNSAFE_FILENAME_CHARS.sub('_', Path(name).stem)}.xhtml"
    return f"{name}{sep}{fragment}"


def process_chapter_html(
    raw_html: str, book_id: str, chapter_url: str | None = None
) -> tuple[str, dict[str, str]]:
    """Clean chapter HTML, extract main content, and locate referenced images.

    Image sources are resolved against the chapter's own URL, since a relative
    `src` is relative to the page that contains it.

    Returns:
        (cleaned_html, {absolute_image_url: local_file_name})
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    content_div = soup.find("div", id="sbo-rt-content")
    if not content_div:
        content_div = soup.body or soup

    # Convert SVG <image> tags to <img> tags
    for img_tag in content_div.find_all("image"):
        href = img_tag.get("href") or img_tag.get("xlink:href")
        if href:
            new_img = soup.new_tag("img", src=href)
            parent = img_tag.parent
            if parent and parent.name == "svg":
                parent.replace_with(new_img)
            else:
                img_tag.replace_with(new_img)

    base = chapter_url or f"{_BASE_URL}/"
    images_found: dict[str, str] = {}
    for img in content_div.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:"):
            continue
        absolute = urljoin(base, src)
        local = images_found.setdefault(absolute, _asset_name(absolute))
        img["src"] = f"images/{local}"

    # Links into the same book become relative, pointing at the chapter file
    for a in content_div.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:") or href.startswith("#"):
            continue
        if book_id in href:
            a["href"] = _in_book_href(href, book_id)

    return str(content_div), images_found


def build_epub(
    book_meta: dict[str, Any],
    chapters_content: list[tuple[str, str, str]],  # [(title, xhtml_content, file_name)]
    images_data: dict[str, bytes],  # {filename: image_bytes}
    dest_path: Path,
    cover_bytes: bytes | None = None,
) -> Path:
    """Build a compliant EPUB 3 document from processed chapters and assets."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    book = epub.EpubBook()

    book_id = str(book_meta.get("id", "oreilly_book"))
    book.set_identifier(f"urn:orm:book:{book_id}")
    book.set_title(book_meta.get("title", "Untitled Book"))
    book.set_language("en")

    authors = book_meta.get("authors") or []
    for author in authors:
        book.add_author(author)

    desc = book_meta.get("description")
    if desc:
        book.add_metadata("DC", "description", desc)

    # Add cover image if available
    if cover_bytes:
        book.set_cover("images/cover.jpg", cover_bytes)

    # Add embedded images
    for fname, img_bytes in images_data.items():
        mime_type, _ = mimetypes.guess_type(fname)
        mime_type = mime_type or "image/jpeg"
        item = epub.EpubItem(
            uid=f"img_{fname.replace('.', '_')}",
            file_name=f"images/{fname}",
            media_type=mime_type,
            content=img_bytes,
        )
        book.add_item(item)

    # Add chapters
    epub_chapters: list[epub.EpubHtml] = []
    for ch_title, ch_html, filename in chapters_content:
        ch = epub.EpubHtml(title=ch_title, file_name=filename, lang="en")
        # Wrap content in basic XHTML envelope
        ch.content = (
            f'<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" lang="en">\n'
            f"<head><title>{html.escape(ch_title or '')}</title></head>\n"
            f"<body>\n{ch_html}\n</body>\n</html>"
        )
        book.add_item(ch)
        epub_chapters.append(ch)

    # Table of contents & spine
    book.toc = tuple(epub_chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *epub_chapters]

    # Write EPUB file
    epub.write_epub(str(dest_path), book)
    return dest_path


def write_book_epub(dest: Path, client: FixtureBookClient) -> Path:
    """The book as the built-in import stored it before connectors: an EPUB 3."""
    meta = client.fetch_book_metadata(BOOK_ID)
    chapters, figures, taken = [], {}, set()
    for index, ch in enumerate(client.fetch_chapter_list(BOOK_ID)):
        url = ch["content_url"]
        body, found = process_chapter_html(client.fetch_chapter_html(url), BOOK_ID, url)
        chapters.append((ch["title"], body, _chapter_file_name(ch["filename"], index, taken)))
        figures.update(found)
    images = {local: client.fetch_bytes(url) for url, local in figures.items()}
    cover = client.fetch_bytes(meta["cover_url"])
    return build_epub(meta, chapters, images, dest, cover_bytes=cover)
