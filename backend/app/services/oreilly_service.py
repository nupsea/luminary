"""O'Reilly Learning book ingestion service.

Downloads technical books from learning.oreilly.com using authenticated
session cookies, bypasses Akamai bot-defense via curl_cffi with Safari TLS
impersonation, and compiles chapters and figures into a clean EPUB 3 document
for Luminary's native local ingestion pipeline.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests
from ebooklib import epub

from app.config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://learning.oreilly.com"
_API_V2 = f"{_BASE_URL}/api/v2"

_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.5",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_OREILLY_URL_PATTERN = re.compile(
    r"(?:https?://(?:www\.|learning\.)oreilly\.com/(?:library/view/[^/]+/|videos/[^/]+/|library/cover/))([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

_COVER_WIDTH_RE = re.compile(r"/\d+w/?$")
_HIGH_RES_COVER_WIDTH = "1200w"


def is_oreilly_url(url: str) -> bool:
    """Return True if the URL points to an O'Reilly Learning resource."""
    if not url:
        return False
    u = url.strip().lower()
    return "learning.oreilly.com" in u or "oreilly.com/library/view" in u or "urn:orm:book:" in u


def parse_oreilly_book_id(url_or_id: str) -> str | None:
    """Extract book identifier/ISBN from an O'Reilly URL or identifier string.

    Examples:
        https://learning.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
        https://learning.oreilly.com/library/view/fluent-python-2nd/9781492056348/ch01.html
        urn:orm:book:9781491903063
        9781491903063
    """
    if not url_or_id:
        return None
    raw = url_or_id.strip()

    if raw.startswith("urn:orm:book:"):
        return raw.split(":")[-1]

    # Check regex on full URL
    m = _OREILLY_URL_PATTERN.search(raw)
    if m:
        return m.group(1)

    # Path-based parsing
    if "://" in raw:
        path_parts = [p for p in urlparse(raw).path.split("/") if p]
        if "view" in path_parts:
            idx = path_parts.index("view")
            # /library/view/{slug}/{id}/...
            if len(path_parts) > idx + 2:
                return path_parts[idx + 2]
        if path_parts:
            # Last segment might be the ISBN/ID if numeric or standard format
            candidate = path_parts[-1].replace(".html", "").replace(".xhtml", "")
            if re.match(r"^[0-9]{10,13}$", candidate) or re.match(r"^[A-Z0-9_-]{5,}$", candidate):
                return candidate

    # Raw ISBN or alphanumeric identifier
    if re.match(r"^[0-9]{10,13}$", raw) or (
        re.match(r"^[A-Za-z0-9_-]{5,}$", raw) and " " not in raw
    ):
        return raw

    return None


def parse_oreilly_target_chapter(url: str) -> str | None:
    """Extract specific chapter filename or identifier if present in URL.

    Examples:
        .../hands-on-rag-for/9798341621701/ch06.html#... -> "ch06.html"
        .../fluent-python-2nd/9781492056348/ch01.html -> "ch01.html"
        .../ddia/9781491903063/ -> None
    """
    if not url or "://" not in url:
        return None
    path_parts = [p for p in urlparse(url).path.split("/") if p]
    if len(path_parts) >= 2:
        last = path_parts[-1]
        is_html = last.endswith((".html", ".xhtml"))
        is_isbn = bool(re.match(r"^[0-9]{10,13}$", last.split(".")[0]))
        if is_html and not is_isbn:
            return last
    return None


def upgrade_cover_url(url: str) -> str:
    """Upgrade an O'Reilly cover URL to the 1200w high-resolution print variant."""
    if not url:
        return ""
    if "/library/cover/" not in url and "/covers/urn:orm:book:" not in url:
        return url
    stripped = _COVER_WIDTH_RE.sub("", url, count=1).rstrip("/")
    return f"{stripped}/{_HIGH_RES_COVER_WIDTH}/"


def parse_cookies_input(cookie_input: str | dict | list) -> dict[str, str]:
    """Parse cookie input into a flat name-value dictionary.

    Supports:
    - JSON array of cookie objects: `[{"name": "...", "value": "..."}, ...]`
    - JSON object: `{"_abck": "...", "sessionid": "..."}`
    - HTTP Cookie header string: `_abck=xyz; bm_sz=123; sessionid=abc`
    """
    if isinstance(cookie_input, dict):
        return {str(k).strip(): str(v).strip() for k, v in cookie_input.items() if k and v}

    if isinstance(cookie_input, list):
        cookies: dict[str, str] = {}
        for item in cookie_input:
            if isinstance(item, dict) and "name" in item and "value" in item:
                cookies[str(item["name"]).strip()] = str(item["value"]).strip()
        return cookies

    if isinstance(cookie_input, str):
        raw = cookie_input.strip()
        if not raw:
            return {}

        # Strip optional "Cookie:" / "cookie:" header label
        if raw.lower().startswith("cookie:"):
            raw = raw[len("cookie:"):].strip()

        # Attempt JSON parse
        if raw.startswith(("[", "{")):
            try:
                parsed = json.loads(raw)
                return parse_cookies_input(parsed)
            except Exception:
                logger.debug("Failed to parse cookie input as JSON, falling back to header parsing")

        # Parse as HTTP Cookie header or lines of key=value / key\tvalue
        cookies = {}
        parts = re.split(r"[;\n\r]+", raw)
        for part in parts:
            cleaned = part.strip()
            if not cleaned:
                continue
            if "=" in cleaned:
                k, v = cleaned.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k:
                    cookies[k] = v
            elif "\t" in cleaned:
                tokens = cleaned.split("\t")
                if len(tokens) >= 2 and tokens[0].strip():
                    cookies[tokens[0].strip()] = tokens[1].strip()
        return cookies

    return {}


def _cookies_file_path() -> Path:
    settings = get_settings()
    data_dir = Path(settings.DATA_DIR).expanduser()
    return data_dir / "oreilly_cookies.json"


def get_oreilly_cookies() -> dict[str, str] | None:
    """Retrieve saved O'Reilly cookies from local storage."""
    path = _cookies_file_path()
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        cookies = json.loads(content)
        return cookies if isinstance(cookies, dict) and cookies else None
    except Exception as e:
        logger.warning("Could not read O'Reilly cookies from %s: %s", path, e)
        return None


def save_oreilly_cookies(cookies: dict[str, str]) -> None:
    """Save O'Reilly cookies to local storage."""
    path = _cookies_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    logger.info("Saved O'Reilly cookies (%d entries)", len(cookies))


def delete_oreilly_cookies() -> None:
    """Remove saved O'Reilly cookies from local storage."""
    path = _cookies_file_path()
    if path.exists():
        with contextlib.suppress(Exception):
            path.unlink()
        logger.info("Deleted O'Reilly cookies")


class OreillyClient:
    """HTTP client for O'Reilly Learning with TLS/Safari impersonation."""

    def __init__(self, cookies: dict[str, str] | None = None):
        self._cookies = cookies or get_oreilly_cookies() or {}
        # safari17_0 TLS impersonation ensures Akamai accepts the request
        self.session = requests.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)
        self._apply_cookies()

    def _apply_cookies(self) -> None:
        self.session.cookies.clear()
        if self._cookies:
            self.session.cookies.update(self._cookies)

    def is_configured(self) -> bool:
        return bool(self._cookies)

    def validate_session(self) -> tuple[bool, str | None]:
        """Check if current cookies provide an authenticated session.

        Returns (is_valid, user_identifier_or_message).
        """
        if not self._cookies:
            return False, "No cookies configured"

        self._apply_cookies()
        try:
            resp = self.session.get(f"{_BASE_URL}/profile/", timeout=15)
            if resp.status_code == 200 and "login" not in resp.url.lower():
                # Extract username or email if visible in HTML
                soup = BeautifulSoup(resp.text, "html.parser")
                email_el = soup.find("span", class_="user-email") or soup.find(id="user-email")
                user_label = email_el.get_text(strip=True) if email_el else "Active Subscriber"
                return True, user_label
            return False, f"Session expired or invalid (HTTP {resp.status_code})"
        except Exception as exc:
            logger.warning("O'Reilly session validation failed: %s", exc)
            return False, str(exc)

    def fetch_book_metadata(self, book_id: str) -> dict[str, Any]:
        """Fetch book metadata via O'Reilly V2 APIs."""
        self._apply_cookies()
        meta: dict[str, Any] = {
            "id": book_id,
            "title": f"O'Reilly Book {book_id}",
            "authors": [],
            "publishers": [],
            "description": "",
            "cover_url": "",
            "isbn": book_id,
        }

        # 1. Primary: /api/v2/epubs/{book_id}/
        try:
            resp = self.session.get(f"{_API_V2}/epubs/{book_id}/", timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                meta["title"] = data.get("title") or meta["title"]
                authors_raw = data.get("authors") or []
                meta["authors"] = [
                    a.get("name", str(a)) if isinstance(a, dict) else str(a) for a in authors_raw
                ]
                publishers_raw = data.get("publishers") or []
                meta["publishers"] = [
                    p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in publishers_raw
                ]
                meta["description"] = data.get("description", "")
                meta["isbn"] = data.get("isbn") or book_id
                cover = data.get("cover_url") or data.get("cover")
                if cover:
                    meta["cover_url"] = upgrade_cover_url(cover)
                return meta
        except Exception as exc:
            logger.debug("O'Reilly /epubs/ API call error: %s", exc)

        # 2. Fallback: /api/v2/search/?query={book_id}
        try:
            resp = self.session.get(f"{_API_V2}/search/?query={book_id}", timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                match = None
                for r in results:
                    if r.get("archive_id") == book_id or r.get("ourn", "").endswith(f":{book_id}"):
                        match = r
                        break
                if not match and results:
                    match = results[0]
                if match:
                    meta["title"] = match.get("title") or meta["title"]
                    meta["authors"] = match.get("authors", [])
                    meta["publishers"] = match.get("publishers", [])
                    meta["description"] = match.get("description", "")
                    cover = match.get("cover_url")
                    if cover:
                        meta["cover_url"] = upgrade_cover_url(cover)
        except Exception as exc:
            logger.debug("O'Reilly search API fallback error: %s", exc)

        return meta

    def fetch_chapter_list(self, book_id: str) -> list[dict[str, Any]]:
        """Fetch all chapters for a book from O'Reilly V2 epub-chapters API."""
        self._apply_cookies()
        url = f"{_API_V2}/epub-chapters/?epub_identifier=urn:orm:book:{book_id}"
        chapters: list[dict[str, Any]] = []

        while url:
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                logger.error("Failed to fetch chapters for %s (HTTP %d)", book_id, resp.status_code)
                break

            data = resp.json()
            for ch in data.get("results", []):
                ref_id = ch.get("reference_id", "")
                filename = ref_id.split("/")[-1] if "/" in ref_id else ref_id
                if not filename:
                    filename = f"chapter_{len(chapters) + 1}.xhtml"

                chapters.append({
                    "title": ch.get("title", f"Chapter {len(chapters) + 1}"),
                    "filename": filename,
                    "content_url": ch.get("content_url", ""),
                    "images": (ch.get("related_assets") or {}).get("images", []),
                    "virtual_pages": ch.get("virtual_pages"),
                    "minutes_required": ch.get("minutes_required"),
                    "order": len(chapters),
                })
            url = data.get("next")

        return chapters

    def fetch_chapter_html(self, content_url: str) -> str:
        """Fetch raw HTML content for a specific chapter."""
        self._apply_cookies()
        resp = self.session.get(content_url, timeout=30)
        resp.raise_for_status()
        return resp.text

    def fetch_bytes(self, url: str) -> bytes:
        """Fetch binary content (e.g. image or cover)."""
        self._apply_cookies()
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.content


def process_chapter_html(raw_html: str, book_id: str) -> tuple[str, list[str]]:
    """Clean chapter HTML, extract main content, and locate referenced images.

    Returns:
        (cleaned_html, list_of_image_src_urls)
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

    # Rewrite image links to relative images/ directory and record URLs
    images_found: list[str] = []
    for img in content_div.find_all("img"):
        src = img.get("src", "")
        if not src:
            continue
        filename = unquote(src.split("/")[-1])
        img["src"] = f"images/{filename}"
        images_found.append(src)

    # Rewrite hrefs
    for a in content_div.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:") or href.startswith("#"):
            continue
        if book_id in href:
            path = href.split(book_id)[-1].lstrip("/")
            a["href"] = path

    return str(content_div), images_found


def build_epub(
    book_meta: dict[str, Any],
    chapters_content: list[tuple[str, str]],  # [(title, xhtml_content)]
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
    for i, (ch_title, ch_html) in enumerate(chapters_content):
        filename = f"chapter_{i + 1:03d}.xhtml"
        ch = epub.EpubHtml(
            title=ch_title or f"Chapter {i + 1}",
            file_name=filename,
            lang="en",
        )
        # Wrap content in basic XHTML envelope
        ch.content = (
            f'<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" lang="en">\n'
            f'<head><title>{html.escape(ch_title)}</title></head>\n'
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
    logger.info("Assembled EPUB with %d chapters at %s", len(epub_chapters), dest_path)
    return dest_path


def download_oreilly_book_to_epub(
    book_id: str,
    dest_path: Path,
    client: OreillyClient,
    selected_chapter_indices: list[int] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Synchronously/threaded download book chapters, images, and compile into EPUB.

    Returns:
        (epub_path, book_metadata)
    """
    logger.info("Fetching O'Reilly metadata for book %s", book_id)
    meta = client.fetch_book_metadata(book_id)

    # Fetch cover art
    cover_bytes: bytes | None = None
    if meta.get("cover_url"):
        try:
            cover_bytes = client.fetch_bytes(meta["cover_url"])
        except Exception as exc:
            logger.debug("Could not download cover image: %s", exc)

    logger.info("Fetching chapter list for book %s", book_id)
    all_chapters = client.fetch_chapter_list(book_id)
    if not all_chapters:
        msg = f"No chapters found for O'Reilly book {book_id}. Session may have expired."
        raise RuntimeError(msg)

    # Filter chapters if selective ingestion was requested
    if selected_chapter_indices is not None:
        idx_set = set(selected_chapter_indices)
        target_chapters = [ch for i, ch in enumerate(all_chapters) if i in idx_set]
    else:
        target_chapters = all_chapters

    chapters_content: list[tuple[str, str]] = []
    images_to_fetch: set[str] = set()

    for ch in target_chapters:
        content_url = ch.get("content_url")
        if not content_url:
            continue
        try:
            raw_html = client.fetch_chapter_html(content_url)
            cleaned_html, img_urls = process_chapter_html(raw_html, book_id)
            chapters_content.append((ch.get("title", ""), cleaned_html))
            images_to_fetch.update(img_urls)
        except Exception as exc:
            logger.warning("Failed to fetch chapter '%s': %s", ch.get("title"), exc)

    if not chapters_content:
        raise RuntimeError(f"Failed to download any chapters for O'Reilly book {book_id}")

    # Download referenced images
    images_data: dict[str, bytes] = {}
    for img_url in images_to_fetch:
        try:
            # Construct full URL if relative
            if img_url.startswith("http"):
                full_url = img_url
            else:
                full_url = f"{_BASE_URL}/{img_url.lstrip('/')}"
            fname = unquote(img_url.split("/")[-1])
            img_bytes = client.fetch_bytes(full_url)
            images_data[fname] = img_bytes
        except Exception as exc:
            logger.debug("Could not download figure %s: %s", img_url, exc)

    epub_path = build_epub(
        book_meta=meta,
        chapters_content=chapters_content,
        images_data=images_data,
        dest_path=dest_path,
        cover_bytes=cover_bytes,
    )
    return epub_path, meta


async def download_and_launch_ingestion(
    doc_id: str,
    book_id: str,
    dest_path: Path,
    client: OreillyClient,
    selected_chapters: list[int] | None = None,
) -> None:
    """Download chapters, compile EPUB, and trigger local LLM ingestion pipeline."""
    from app.database import get_session_factory  # noqa: PLC0415
    from app.models import DocumentModel  # noqa: PLC0415
    from app.workflows.ingestion import run_ingestion  # noqa: PLC0415

    try:
        await asyncio.to_thread(
            download_oreilly_book_to_epub,
            book_id=book_id,
            dest_path=dest_path,
            client=client,
            selected_chapter_indices=selected_chapters,
        )
        await run_ingestion(doc_id, str(dest_path), "epub", "technical")
    except Exception as exc:
        logger.exception("O'Reilly book download or ingestion failed for %s", book_id)
        async with get_session_factory()() as session:
            doc = await session.get(DocumentModel, doc_id)
            if doc:
                doc.stage = "error"
                doc.error_message = f"O'Reilly download failed: {exc}"
                await session.commit()


async def start_oreilly_ingestion(
    url: str,
    settings: Any,
    selected_chapters: list[int] | None = None,
) -> dict[str, Any]:
    """Validate session, parse book ID, create document, and launch background ingestion."""
    from fastapi import HTTPException  # noqa: PLC0415

    from app.database import get_session_factory  # noqa: PLC0415
    from app.models import DocumentModel  # noqa: PLC0415
    from app.services.ingestion_jobs import get_ingestion_jobs  # noqa: PLC0415

    client = OreillyClient()
    if not client.is_configured():
        raise HTTPException(
            status_code=401,
            detail=(
                "O'Reilly subscription cookies not configured. "
                "Please connect your O'Reilly subscription in Settings."
            ),
        )

    book_id = parse_oreilly_book_id(url)
    if not book_id:
        raise HTTPException(
            status_code=400,
            detail=f"Could not extract O'Reilly book ID or ISBN from URL: {url}",
        )

    # Fetch metadata for book title
    book_title = f"O'Reilly Book {book_id}"
    try:
        meta = await asyncio.to_thread(client.fetch_book_metadata, book_id)
        book_title = meta.get("title") or book_title
    except Exception as exc:
        logger.warning(
            "Could not fetch metadata for %s, proceeding with fallback title: %s",
            book_id,
            exc,
        )

    # Detect if a specific chapter was requested in the URL
    target_chapter = parse_oreilly_target_chapter(url) if selected_chapters is None else None
    matched_chapter_title: str | None = None

    if target_chapter:
        try:
            all_chapters = await asyncio.to_thread(client.fetch_chapter_list, book_id)
            target_norm = target_chapter.lower().replace(".xhtml", ".html")
            for idx, ch in enumerate(all_chapters):
                fn = ch.get("filename", "").lower().replace(".xhtml", ".html")
                ref = ch.get("reference_id", "").lower().replace(".xhtml", ".html")
                if fn == target_norm or ref.endswith(target_norm):
                    selected_chapters = [idx]
                    matched_chapter_title = ch.get("title")
                    break
        except Exception as exc:
            logger.warning("Could not resolve chapter %s for %s: %s", target_chapter, book_id, exc)

    if matched_chapter_title:
        book_title = f"{book_title} — {matched_chapter_title}"
        doc_tags = ["oreilly", "tech_chapter"]
    else:
        doc_tags = ["oreilly", "tech_book"]

    doc_id = str(uuid.uuid4())
    data_dir = Path(settings.DATA_DIR).expanduser()
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest_epub = raw_dir / f"{doc_id}.epub"

    async with get_session_factory()() as session:
        doc = DocumentModel(
            id=doc_id,
            title=book_title,
            format="epub",
            content_type="technical",
            word_count=0,
            page_count=0,
            file_path=str(dest_epub),
            file_hash=None,
            stage="parsing",
            source_url=url,
            tags=doc_tags,
        )
        session.add(doc)
        await session.commit()

    get_ingestion_jobs().launch(
        doc_id,
        download_and_launch_ingestion(
            doc_id=doc_id,
            book_id=book_id,
            dest_path=dest_epub,
            client=client,
            selected_chapters=selected_chapters,
        ),
    )

    logger.info("O'Reilly book ingestion launched", extra={"doc_id": doc_id, "book_id": book_id})
    return {
        "document_id": doc_id,
        "status": "processing",
        "title": book_title,
    }

