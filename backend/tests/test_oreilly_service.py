"""Tests for O'Reilly service and endpoints."""

import sys
from pathlib import Path

import pytest
from ebooklib import epub

from app.services.oreilly_service import (
    OreillyClient,
    OreillyDownloadError,
    build_epub,
    delete_oreilly_cookies,
    download_oreilly_book_to_epub,
    is_oreilly_url,
    parse_cookies_input,
    parse_oreilly_book_id,
    parse_oreilly_target_chapter,
    process_chapter_html,
    save_oreilly_cookies,
    upgrade_cover_url,
)
from app.services.parser import DocumentParser


def test_parse_oreilly_target_chapter():
    url1 = "https://learning.oreilly.com/library/view/hands-on-rag-for/9798341621701/ch06.html#ch06"
    assert parse_oreilly_target_chapter(url1) == "ch06.html"

    url2 = "https://learning.oreilly.com/library/view/fluent-python-2nd/9781492056348/ch01.xhtml"
    assert parse_oreilly_target_chapter(url2) == "ch01.xhtml"

    url3 = "https://learning.oreilly.com/library/view/ddia/9781491903063/"
    assert parse_oreilly_target_chapter(url3) is None

    assert parse_oreilly_target_chapter("") is None


def test_is_oreilly_url():
    assert is_oreilly_url("https://learning.oreilly.com/library/view/ddia/9781491903063/")
    assert is_oreilly_url("https://www.oreilly.com/library/view/fluent-python/9781492056348/")
    assert is_oreilly_url("urn:orm:book:9781491903063")
    assert not is_oreilly_url("https://youtube.com/watch?v=123")
    assert not is_oreilly_url("https://example.com/article")
    assert not is_oreilly_url("https://example.com/review?via=learning.oreilly.com")
    assert not is_oreilly_url("https://www.oreilly.com/radar/some-article/")
    assert not is_oreilly_url("")


def test_parse_oreilly_book_id():
    # Standard view URL
    assert (
        parse_oreilly_book_id(
            "https://learning.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/"
        )
        == "9781491903063"
    )
    # Deep chapter URL
    assert (
        parse_oreilly_book_id(
            "https://learning.oreilly.com/library/view/fluent-python-2nd/9781492056348/ch01.html"
        )
        == "9781492056348"
    )
    # URN format
    assert parse_oreilly_book_id("urn:orm:book:9781491903063") == "9781491903063"
    # Bare ISBN
    assert parse_oreilly_book_id("9781491903063") == "9781491903063"
    # Invalid / empty
    assert parse_oreilly_book_id("") is None
    assert parse_oreilly_book_id("https://google.com") is None


def test_upgrade_cover_url():
    # Strips existing width and adds 1200w
    url = "https://learning.oreilly.com/library/cover/9781491903063/400w/"
    assert (
        upgrade_cover_url(url) == "https://learning.oreilly.com/library/cover/9781491903063/1200w/"
    )

    # Adds 1200w to base cover
    url_base = "https://learning.oreilly.com/covers/urn:orm:book:9781491903063"
    assert (
        upgrade_cover_url(url_base)
        == "https://learning.oreilly.com/covers/urn:orm:book:9781491903063/1200w/"
    )

    # Leaves unrelated URLs alone
    assert upgrade_cover_url("https://example.com/img.jpg") == "https://example.com/img.jpg"


def test_parse_cookies_input():
    # 1. JSON Array (Cookie-Editor format)
    cookie_array = [
        {"name": "_abck", "value": "abc123token"},
        {"name": "sessionid", "value": "sess456"},
    ]
    import json

    parsed_arr = parse_cookies_input(json.dumps(cookie_array))
    assert parsed_arr == {"_abck": "abc123token", "sessionid": "sess456"}

    # 2. JSON Dict
    cookie_dict = {"_abck": "token1", "orm-jwt": "jwt2"}
    assert parse_cookies_input(cookie_dict) == cookie_dict
    assert parse_cookies_input(json.dumps(cookie_dict)) == cookie_dict

    # 3. HTTP Cookie header string
    header_str = "_abck=token1; bm_sz=token2; sessionid=token3"
    parsed_header = parse_cookies_input(header_str)
    assert parsed_header == {
        "_abck": "token1",
        "bm_sz": "token2",
        "sessionid": "token3",
    }

    # 4. DevTools raw header with Cookie: prefix
    devtools_str = "cookie: _abck=token1; bm_sz=token2; sessionid=token3"
    assert parse_cookies_input(devtools_str) == {
        "_abck": "token1",
        "bm_sz": "token2",
        "sessionid": "token3",
    }

    # 5. Multiline / tab-separated table paste
    table_paste = "_abck\ttoken1\nsessionid\ttoken3"
    assert parse_cookies_input(table_paste) == {
        "_abck": "token1",
        "sessionid": "token3",
    }


def test_process_chapter_html():
    raw = """
    <html>
      <head><title>Chapter 1</title></head>
      <body>
        <div class="nav-header">Header to ignore</div>
        <div id="sbo-rt-content">
          <h1>Chapter 1: Foundations</h1>
          <p>Introductory text with an image.</p>
          <img src="https://learning.oreilly.com/assets/ch01_fig1.png" alt="Architecture" />
          <svg><image href="diagram.svg" /></svg>
        </div>
      </body>
    </html>
    """
    chapter_url = (
        "https://learning.oreilly.com/api/v2/epubs/urn:orm:book:9781491903063/files/ch01.html"
    )
    cleaned, images = process_chapter_html(raw, "9781491903063", chapter_url)
    assert "Chapter 1: Foundations" in cleaned
    assert "Header to ignore" not in cleaned
    assert set(images) == {
        "https://learning.oreilly.com/assets/ch01_fig1.png",
        # Relative to the chapter's own URL, not the site root.
        "https://learning.oreilly.com/api/v2/epubs/urn:orm:book:9781491903063/files/diagram.svg",
    }
    for local in images.values():
        assert f"images/{local}" in cleaned


def test_figures_sharing_a_base_name_keep_separate_files():
    """Two chapters' "figure1.png" used to collapse into one file and show one figure twice."""
    html = '<div id="sbo-rt-content"><img src="figs/figure1.png"/></div>'
    _, first = process_chapter_html(html, "b1", "https://learning.oreilly.com/x/ch01/index.html")
    _, second = process_chapter_html(html, "b1", "https://learning.oreilly.com/x/ch02/index.html")
    assert len(set(first.values()) | set(second.values())) == 2


def test_build_epub(tmp_path: Path):
    dest = tmp_path / "test_oreilly_book.epub"
    meta = {
        "id": "9781491903063",
        "title": "Designing Data-Intensive Applications",
        "authors": ["Martin Kleppmann"],
        "description": "The big ideas behind reliable systems.",
    }
    chapters = [
        (
            "Chapter 1: Reliable, Scalable, and Maintainable",
            "<h1>Chapter 1</h1><p>Systems are reliable.</p>",
            "ch01.xhtml",
        ),
        (
            "Chapter 2: Data Models and Query Languages",
            '<h1>Chapter 2</h1><p>Relational vs <a href="ch01.xhtml#x">Document</a>.</p>',
            "ch02.xhtml",
        ),
    ]
    images = {"diagram.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"}

    epub_path = build_epub(
        book_meta=meta,
        chapters_content=chapters,
        images_data=images,
        dest_path=dest,
    )
    assert epub_path.exists()
    assert epub_path.stat().st_size > 0

    # Verify readable by ebooklib
    book = epub.read_epub(str(epub_path))
    assert book.get_metadata("DC", "title")[0][0] == "Designing Data-Intensive Applications"
    assert book.get_metadata("DC", "creator")[0][0] == "Martin Kleppmann"
    # 2 chapters + nav + ncx
    html_items = [it for it in book.get_items() if it.get_type() == 9]  # 9 = ITEM_DOCUMENT
    assert len(html_items) >= 2
    # Chapters keep their source names, so the book's own cross-references resolve.
    assert {"ch01.xhtml", "ch02.xhtml"} <= {it.get_name() for it in html_items}


class _FakeClient:
    def __init__(self, failing: set[str]):
        self.failing = failing

    def fetch_book_metadata(self, book_id):
        return {"id": book_id, "title": "Book", "authors": [], "cover_url": ""}

    def fetch_chapter_list(self, book_id):
        return [
            {
                "title": t,
                "filename": f"{t}.html",
                "content_url": f"https://learning.oreilly.com/{t}.html",
            }
            for t in ("ch01", "ch02", "ch03")
        ]

    def fetch_chapter_html(self, url):
        if any(name in url for name in self.failing):
            raise ConnectionError("reset")
        return (
            '<div id="sbo-rt-content"><h1>Title</h1>'
            "<p>Body. The parser keeps only sections of fifty characters or more.</p></div>"
        )

    def fetch_bytes(self, url):
        return b""


def test_a_book_missing_a_chapter_is_not_ingested(tmp_path: Path):
    """A skipped chapter used to leave a book that ingested as complete without it."""
    dest = tmp_path / "book.epub"
    with pytest.raises(OreillyDownloadError, match="1 of 3 chapters"):
        download_oreilly_book_to_epub("b1", dest, _FakeClient(failing={"ch02"}))
    assert not dest.exists()

    path, _ = download_oreilly_book_to_epub("b1", dest, _FakeClient(failing=set()))
    parsed = DocumentParser().parse(path, "epub")
    # Every chapter must reach the parser as a document, not only exist in the archive.
    assert sum("Body." in s.text for s in parsed.sections) == 3


def test_links_into_the_book_point_at_the_stored_chapter():
    html = (
        '<div id="sbo-rt-content"><a href="/library/view/x/b1/ch04.html#sec2">see</a>'
        '<a href="https://example.com/">out</a></div>'
    )
    cleaned, _ = process_chapter_html(html, "b1")
    assert 'href="ch04.xhtml#sec2"' in cleaned
    assert 'href="https://example.com/"' in cleaned


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "NTFS has no POSIX mode bits: os.chmod on Windows can only toggle the "
        "read-only attribute, so stat().st_mode always reports 0o666 for a "
        "regular file regardless of the mode os.open() was given. The file's "
        "actual access is the user profile directory's ACL, which chmod cannot "
        "narrow and this test cannot observe through st_mode."
    ),
)
def test_saved_cookies_are_owner_only():
    save_oreilly_cookies({"sessionid": "secret"})
    from app.services.oreilly_service import _cookies_file_path

    try:
        assert _cookies_file_path().stat().st_mode & 0o777 == 0o600
    finally:
        delete_oreilly_cookies()


@pytest.mark.asyncio
async def test_oreilly_client_configured():
    client_empty = OreillyClient(cookies={})
    assert not client_empty.is_configured()

    client_configured = OreillyClient(cookies={"_abck": "valid"})
    assert client_configured.is_configured()
