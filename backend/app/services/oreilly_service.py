"""O'Reilly Learning book ingestion service.

Downloads technical books from learning.oreilly.com using authenticated
session cookies, bypasses Akamai bot-defense via curl_cffi with Safari TLS
impersonation, and compiles chapters and figures into a clean EPUB 3 document
for Luminary's native local ingestion pipeline.
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import json
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests
from ebooklib import epub

from app.config import get_settings
from app.exceptions import LuminaryError

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

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class OreillyDownloadError(LuminaryError):
    """The book could not be downloaded whole; nothing partial is ingested."""

    status_code = 502


def is_oreilly_url(url: str) -> bool:
    """Return True if the URL points to an O'Reilly Learning resource."""
    if not url:
        return False
    raw = url.strip()
    if raw.lower().startswith("urn:orm:book:"):
        return True
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host == "learning.oreilly.com":
        return True
    return host in {"oreilly.com", "www.oreilly.com"} and parsed.path.startswith("/library/view/")


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
            raw = raw[len("cookie:") :].strip()

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
    # Session cookies are a login credential: owner-only, including when the
    # file already exists with wider permissions.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(cookies, indent=2))
    with contextlib.suppress(OSError):
        path.chmod(0o600)
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

                chapters.append(
                    {
                        "title": ch.get("title", f"Chapter {len(chapters) + 1}"),
                        "filename": filename,
                        "content_url": ch.get("content_url", ""),
                        "images": (ch.get("related_assets") or {}).get("images", []),
                        "virtual_pages": ch.get("virtual_pages"),
                        "minutes_required": ch.get("minutes_required"),
                        "order": len(chapters),
                    }
                )
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
        raise OreillyDownloadError(msg)

    # Filter chapters if selective ingestion was requested
    if selected_chapter_indices is not None:
        idx_set = set(selected_chapter_indices)
        target_chapters = [ch for i, ch in enumerate(all_chapters) if i in idx_set]
    else:
        target_chapters = all_chapters

    chapters_content: list[tuple[str, str, str]] = []
    images_to_fetch: dict[str, str] = {}
    failed: list[str] = []
    taken_names: set[str] = set()

    for index, ch in enumerate(target_chapters):
        title = ch.get("title") or ""
        content_url = ch.get("content_url")
        if not content_url:
            failed.append(title or f"#{index + 1}")
            continue
        try:
            raw_html = client.fetch_chapter_html(content_url)
        except Exception as exc:
            logger.warning("Failed to fetch chapter '%s': %s", title, exc)
            failed.append(title or f"#{index + 1}")
            continue
        cleaned_html, images = process_chapter_html(raw_html, book_id, content_url)
        file_name = _chapter_file_name(ch.get("filename", ""), index, taken_names)
        chapters_content.append((title, cleaned_html, file_name))
        images_to_fetch.update(images)

    # A book missing chapters would ingest as complete and answer as if whole.
    if failed:
        raise OreillyDownloadError(
            f"Could not download {len(failed)} of {len(target_chapters)} chapters "
            f"of O'Reilly book {book_id}: {', '.join(failed[:5])}"
            + (" ..." if len(failed) > 5 else "")
        )

    # A missing figure leaves a broken image in the reader but loses no text, so
    # it is reported rather than fatal.
    images_data: dict[str, bytes] = {}
    for img_url, local_name in images_to_fetch.items():
        try:
            images_data[local_name] = client.fetch_bytes(img_url)
        except Exception as exc:
            logger.warning("Could not download figure %s: %s", img_url, exc)
    if len(images_data) < len(images_to_fetch):
        logger.warning(
            "O'Reilly book %s: %d of %d figures could not be downloaded",
            book_id,
            len(images_to_fetch) - len(images_data),
            len(images_to_fetch),
        )

    epub_path = build_epub(
        book_meta=meta,
        chapters_content=chapters_content,
        images_data=images_data,
        dest_path=dest_path,
        cover_bytes=cover_bytes,
    )
    return epub_path, meta
