"""EPUB chapter rendering service

Provides sanitized HTML chapter content and table-of-contents for EPUB documents.
Sanitization removes script, iframe, and on* attributes; preserves prose elements.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import math
from collections import Counter
from functools import lru_cache
from urllib.parse import unquote

import bleach
import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

logger = logging.getLogger(__name__)

# Tags allowed in rendered EPUB HTML
_ALLOWED_TAGS = [
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "ul",
    "ol",
    "li",
    "em",
    "strong",
    "code",
    "pre",
    "blockquote",
    "figure",
    "figcaption",
    "img",
    "a",
    "span",
    "div",
    "section",
    "aside",
    "br",
    "hr",
]

# Allow safe, non-event attributes on whitelisted tags
_ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
    "a": ["href", "title", "id", "class", "name"],
    "img": ["src", "alt", "title", "width", "height", "class", "loading"],
    "figure": ["class", "id", "data-type"],
    "figcaption": ["class", "id"],
    "td": ["colspan", "rowspan", "class"],
    "th": ["colspan", "rowspan", "scope", "class"],
    "table": ["summary", "class"],
    "thead": ["class"],
    "tbody": ["class"],
    "tr": ["class"],
    "ol": ["class", "start", "type"],
    "ul": ["class"],
    "li": ["class"],
    "blockquote": ["class", "id"],
    "p": ["class", "id", "data-type"],
    "div": ["class", "id", "data-type"],
    "section": ["class", "id", "data-type"],
    "aside": ["class", "id", "data-type"],
    "span": ["class", "id", "data-type"],
    "pre": ["class", "id", "data-type"],
    "code": ["class", "id", "data-type"],
    "h1": ["id", "class"],
    "h2": ["id", "class"],
    "h3": ["id", "class"],
    "h4": ["id", "class"],
    "h5": ["id", "class"],
    "h6": ["id", "class"],
}


def _extract_chapter_title(soup: BeautifulSoup) -> str:
    """Best-effort title extraction from chapter HTML."""
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        return title_tag.get_text(strip=True)
    for heading in ("h1", "h2", "h3"):
        tag = soup.find(heading)
        if tag and tag.get_text(strip=True):
            return tag.get_text(strip=True)
    return ""


_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _split_soup_on_headings(soup: BeautifulSoup) -> list[dict]:
    """Split one document into a unit per heading, keeping fragments well-formed.

    Finds the highest-level heading present (h1 if present, else h2, etc.).
    If only one heading of that level exists, the whole chapter is kept intact.
    If multiple headings of that level exist (Gutenberg EPUBs), it splits on them.
    """
    root = soup.body or soup
    split_tag = None
    for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        candidates = root.find_all(tag)
        if candidates:
            split_tag = tag
            break

    if not split_tag:
        return [
            {
                "title": _extract_chapter_title(soup),
                "html": str(soup),
                "word_count": _count_words(soup),
            }
        ]

    headings = root.find_all(split_tag)
    counts = Counter(id(h.parent) for h in headings)
    dominant = counts.most_common(1)[0][0]
    container = next(h.parent for h in headings if id(h.parent) == dominant)
    units: list[dict] = []
    current: dict | None = None
    for child in list(container.children):
        if getattr(child, "name", None) == split_tag:
            current = {"title": child.get_text(" ", strip=True), "nodes": [child]}
            units.append(current)
            continue
        if current is None:
            # Skip empty whitespace text before the first heading
            if isinstance(child, str) and not child.strip():
                continue
            # Front matter ahead of the first heading keeps its own unit.
            current = {"title": "", "nodes": []}
            units.append(current)
        current["nodes"].append(child)

    out: list[dict] = []
    for u in units:
        html = "".join(str(n) for n in u["nodes"])
        out.append(
            {
                "title": u["title"],
                "html": html,
                "word_count": _count_words(BeautifulSoup(html, "html.parser")),
            }
        )
    return out


def _count_words(soup: BeautifulSoup) -> int:
    """Approximate word count for HTML content."""
    text = soup.get_text(" ", strip=True)
    return len(text.split())


class EpubService:
    """Service for reading EPUB files and serving sanitized chapter HTML."""

    @staticmethod
    def sanitize_html(raw_html: str) -> str:
        """Strip dangerous tags/attributes from EPUB chapter HTML.

        Removes: script, style, iframe, link[rel=stylesheet], all on* event attrs.
        Keeps: prose, tables, code, lists, headings.
        Images are intentionally excluded to avoid broken relative EPUB paths.
        """
        soup = BeautifulSoup(raw_html, "html.parser")

        # Remove head entirely (styles, scripts, meta)
        for tag in soup.find_all("head"):
            tag.decompose()

        # Remove dangerous tags by name (images are preserved and inlined)
        for tag_name in ("script", "style", "iframe", "noscript", "object", "embed", "link"):
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Serialize back to string for bleach pass
        body = soup.find("body")
        inner = body.decode_contents() if body else str(soup)

        # bleach strips any remaining on* attributes and unlisted tags
        clean = bleach.clean(
            inner,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRIBUTES,
            protocols=["http", "https", "mailto", "data"],
            strip=True,
            strip_comments=True,
        )
        return clean

    def _chapter_units(self, file_path: str) -> list[dict]:
        """Every chapter in the book, as {title, html, word_count}.

        An EPUB may pack many chapters into one document, so units come from
        headings rather than spine items. `get_toc` and `get_chapter` share this
        list so they cannot disagree about what chapter N is.
        """
        book = epub.read_epub(file_path, options={"ignore_ncx": False})
        units: list[dict] = []

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            # Skip EPUB navigation documents (table-of-contents spine item)
            if isinstance(item, epub.EpubNav):
                continue
            try:
                html_str = item.get_content().decode("utf-8", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                html_str = ""
            soup = BeautifulSoup(html_str, "html.parser")
            for unit in _split_soup_on_headings(soup):
                # Skip near-empty items with no discernible title (cover pages)
                if not unit["title"] and unit["word_count"] < 10:
                    continue
                if not unit["title"]:
                    unit["title"] = f"Chapter {len(units) + 1}"
                units.append(unit)

        logger.info("EPUB TOC extracted: %d chapters from %s", len(units), file_path)
        return units

    def get_toc(self, file_path: str) -> list[dict]:
        """Return table-of-contents entries for an EPUB.

        Returns a list of dicts: {chapter_index, title, word_count}.
        """
        return [
            {"chapter_index": i, "title": u["title"], "word_count": u["word_count"]}
            for i, u in enumerate(self._chapter_units(file_path))
        ]

    def get_chapter(
        self,
        file_path: str,
        chapter_index: int,
        section_ids: list[str] | None = None,
    ) -> dict:
        """Return sanitized HTML for a single EPUB chapter.

        Args:
            file_path: Path to the .epub file on disk.
            chapter_index: 0-based index into the filtered spine.
            section_ids: List of SectionModel IDs to associate with this chapter.

        Returns a dict: {html, chapter_title, word_count, section_ids}.
        Raises IndexError if chapter_index is out of range.
        """

        units = self._chapter_units(file_path)

        if chapter_index < 0 or chapter_index >= len(units):
            raise IndexError(f"chapter_index {chapter_index} out of range (0-{len(units) - 1})")

        unit = units[chapter_index]
        html_content = unit["html"]

        # Resolve embedded EPUB images into inline base64 data URIs so diagrams render
        if "<img" in html_content.lower():
            try:
                book = epub.read_epub(file_path, options={"ignore_ncx": True})
                images: dict[str, tuple[str, bytes]] = {}
                for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                    raw_name = item.file_name
                    base_name = raw_name.split("/")[-1]
                    media_type = item.media_type or "image/png"
                    images[raw_name] = (media_type, item.content)
                    images[base_name] = (media_type, item.content)

                soup = BeautifulSoup(html_content, "html.parser")
                for img in soup.find_all("img"):
                    src = img.get("src", "")
                    if not src:
                        continue
                    clean_src = unquote(src).lstrip("./")
                    base = clean_src.split("/")[-1]
                    img_data = images.get(clean_src) or images.get(base)
                    if img_data:
                        mime, content = img_data
                        b64 = base64.b64encode(content).decode("ascii")
                        img["src"] = f"data:{mime};base64,{b64}"
                        img["loading"] = "lazy"
                html_content = str(soup)
            except Exception as exc:
                logger.warning("Could not inline images for chapter %d: %s", chapter_index, exc)

        clean_html = self.sanitize_html(html_content)
        logger.info(
            "EPUB chapter %d rendered: %d words, title=%r",
            chapter_index,
            unit["word_count"],
            unit["title"],
        )
        return {
            "html": clean_html,
            "chapter_title": unit["title"],
            "word_count": unit["word_count"],
            "section_ids": section_ids or [],
        }

    def compute_chapter_section_ids(
        self,
        all_section_ids: list[str],
        chapter_index: int,
        total_chapters: int,
    ) -> list[str]:
        """Assign a proportional slice of section IDs to a chapter.

        Uses integer division to partition sections across chapters.
        """
        if total_chapters == 0 or not all_section_ids:
            return []
        n = len(all_section_ids)
        chapter_size = math.ceil(n / total_chapters)
        start = chapter_index * chapter_size
        end = min(start + chapter_size, n)
        return all_section_ids[start:end]


@lru_cache(maxsize=1)
def get_epub_service() -> EpubService:
    return EpubService()


async def get_toc_async(file_path: str) -> list[dict]:
    """Run get_toc in a thread pool executor to avoid blocking the event loop."""
    service = get_epub_service()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, service.get_toc, file_path)


async def get_chapter_async(
    file_path: str,
    chapter_index: int,
    section_ids: list[str] | None = None,
) -> dict:
    """Run get_chapter in a thread pool executor to avoid blocking the event loop."""
    service = get_epub_service()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, service.get_chapter, file_path, chapter_index, section_ids
    )
