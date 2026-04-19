"""EPUB chapter rendering service (S149).

Provides sanitized HTML chapter content and table-of-contents for EPUB documents.
Sanitization removes script, iframe, and on* attributes; preserves prose elements.
"""

from __future__ import annotations

import asyncio
import logging
import math
from functools import lru_cache

import bleach
from bs4 import BeautifulSoup

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

    def get_toc(self, file_path: str) -> list[dict]:
        """Return table-of-contents entries for an EPUB spine.

        Returns a list of dicts: {chapter_index, title, word_count}.
        Navigation/TOC documents (EpubNav) and near-empty items are skipped.
        """
        import ebooklib  # noqa: PLC0415
        from ebooklib import epub  # noqa: PLC0415

        book = epub.read_epub(file_path, options={"ignore_ncx": False})
        chapters: list[dict] = []
        idx = 0
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            # Skip EPUB navigation documents (table-of-contents spine item)
            if isinstance(item, epub.EpubNav):
                continue
            raw = item.get_content()
            try:
                html_str = raw.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                html_str = ""
            soup = BeautifulSoup(html_str, "html.parser")
            title = _extract_chapter_title(soup)
            word_count = _count_words(soup)
            # Skip near-empty items with no discernible title (e.g. cover pages)
            if not title and word_count < 10:
                continue
            if not title:
                title = f"Chapter {idx + 1}"
            chapters.append(
                {
                    "chapter_index": idx,
                    "title": title,
                    "word_count": word_count,
                }
            )
            idx += 1
        logger.info("EPUB TOC extracted: %d chapters from %s", len(chapters), file_path)
        return chapters

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
        import ebooklib  # noqa: PLC0415
        from ebooklib import epub  # noqa: PLC0415

        book = epub.read_epub(file_path, options={"ignore_ncx": False})

        # Build same filtered list as get_toc (must stay in sync)
        filtered_items = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            if isinstance(item, epub.EpubNav):
                continue
            raw = item.get_content()
            try:
                html_str = raw.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                html_str = ""
            soup = BeautifulSoup(html_str, "html.parser")
            title = _extract_chapter_title(soup)
            word_count = _count_words(soup)
            if not title and word_count < 10:
                continue
            fallback = f"Chapter {len(filtered_items) + 1}"
            filtered_items.append((item, html_str, title if title else fallback, word_count))

        if chapter_index < 0 or chapter_index >= len(filtered_items):
            raise IndexError(
                f"chapter_index {chapter_index} out of range (0-{len(filtered_items) - 1})"
            )

        _item, html_str, title, word_count = filtered_items[chapter_index]
        clean_html = self.sanitize_html(html_str)
        logger.info(
            "EPUB chapter %d rendered: %d words, title=%r",
            chapter_index,
            word_count,
            title,
        )
        return {
            "html": clean_html,
            "chapter_title": title,
            "word_count": word_count,
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
