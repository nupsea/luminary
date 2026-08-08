"""EPUB chapter rendering service

Provides sanitized HTML chapter content and table-of-contents for EPUB documents.
Sanitization removes script, iframe, and on* attributes; preserves prose elements.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import Counter
from functools import lru_cache

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
    "a",
    "span",
    "div",
    "br",
    "hr",
]

# Allow only safe, non-event attributes on whitelisted tags
_ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
    "a": ["href", "title"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan", "scope"],
    "table": ["summary"],
    "p": ["class"],
    "div": ["class"],
    "span": ["class"],
    "pre": ["class"],
    "code": ["class"],
    "h1": ["id"],
    "h2": ["id"],
    "h3": ["id"],
    "h4": ["id"],
    "h5": ["id"],
    "h6": ["id"],
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

    Splits the children of the element holding most headings; deeper-nested
    headings are sub-headings of their block, not split points.
    """
    root = soup.body or soup
    headings = root.find_all(_HEADING_TAGS)
    if not headings:
        return [
            {
                "title": _extract_chapter_title(soup),
                "html": str(soup),
                "word_count": _count_words(soup),
            }
        ]

    counts = Counter(id(h.parent) for h in headings)
    dominant = counts.most_common(1)[0][0]
    container = next(h.parent for h in headings if id(h.parent) == dominant)
    units: list[dict] = []
    current: dict | None = None
    for child in list(container.children):
        if getattr(child, "name", None) in _HEADING_TAGS:
            current = {"title": child.get_text(" ", strip=True), "nodes": [child]}
            units.append(current)
            continue
        if current is None:
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

        # Remove dangerous tags by name
        for tag_name in ("script", "style", "iframe", "noscript", "object", "embed", "link", "img"):
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
        clean_html = self.sanitize_html(unit["html"])
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
