import asyncio
import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, NavigableString

from app.config import get_settings
from app.full_extras import require_extra
from app.types import ParsedDocument, Section

logger = logging.getLogger(__name__)

USER_AGENTS = [
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
]


_BOILERPLATE_CONTAINERS = ("nav", "header", "footer", "aside")

_INLINE_MARKERS = {
    "strong": "**",
    "b": "**",
    "em": "*",
    "i": "*",
    "code": "`",
}


class ArticleExtractor:
    """
    Unified article extraction for a high-fidelity reading experience.
    """

    async def extract(self, url: str, doc_id: str | None = None) -> ParsedDocument:
        logger.info("Extracting unified article from URL: %s", url)

        require_extra("cloudscraper", "URL article extraction")
        require_extra("trafilatura", "URL article extraction")
        import cloudscraper
        import trafilatura

        html_content = None
        # 1. Fetch with Cloudflare bypass
        try:
            scraper = cloudscraper.create_scraper()
            response = await asyncio.to_thread(scraper.get, url, timeout=15)
            if response.status_code == 200:
                html_content = response.text
        except Exception as e:
            logger.warning("cloudscraper failed for %s: %s", url, e)

        if not html_content:
            async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": USER_AGENTS[0]})
                resp.raise_for_status()
                html_content = resp.text

        # 2. Extract metadata
        metadata = trafilatura.metadata.extract_metadata(html_content)
        title = (metadata.title if metadata and metadata.title else "Untitled Article").strip()
        # Mirror images under the caller's document_id so image_extract_handler
        # (which scans images/{document_id}) finds them. Fall back to a URL hash
        # only when called outside the ingestion flow.
        doc_id = doc_id or hashlib.md5(url.encode()).hexdigest()

        # 3. Mirror Images AND Extract Markdown in one pass
        # We let trafilatura handle the extraction first to find the "real" content
        markdown_text = trafilatura.extract(
            self._prepare_html(html_content),
            url=url,
            output_format="markdown",
            include_links=True,
            include_images=True,
            include_formatting=True,
        )

        if not markdown_text:
            raise ValueError("Could not extract any meaningful content from the article.")

        logger.debug(
            "ArticleExtractor: extracted markdown (first 500 chars): %s",
            markdown_text[:500],
        )

        # 4. Localize Image Links in Markdown
        # Trafilatura outputs markdown like ![alt](url), often with root-relative
        # src (/foo/bar.png) that must be resolved against the article URL.
        markdown_text = await self._mirror_markdown_images(markdown_text, doc_id, url)

        # 5. Normalize Markdown (The "### Fix")
        markdown_text = self._normalize_markdown(markdown_text)

        # For Articles, we keep them as one primary "Section" to ensure unified flow in UI
        sections = [Section(heading=title, level=1, text=markdown_text, page_start=0, page_end=0)]

        return ParsedDocument(
            title=title,
            format="md",
            pages=1,
            word_count=len(markdown_text.split()),
            sections=sections,
            raw_text=markdown_text,
        )

    def _prepare_html(self, html: str) -> str:
        """Repairs markup that trafilatura's extractor silently drops."""
        soup = BeautifulSoup(html, "html.parser")
        self._hydrate_lazy_images(soup)
        self._flatten_inline_formatting(soup)
        return str(soup)

    def _hydrate_lazy_images(self, soup: BeautifulSoup) -> None:
        """
        Gives every <img> a real src. Lazy-loading sites ship <img> with no src at
        all and keep the true URL in a sibling <picture><source srcset> or a data-*
        attribute; trafilatura only reads img/@src, so those images vanish entirely.
        """
        for img in soup.find_all("img"):
            if not img.get("src"):
                url = None
                picture = img.find_parent("picture")
                if picture:
                    for source in picture.find_all("source"):
                        url = self._best_srcset_url(source.get("srcset")) or url
                url = (
                    url
                    or img.get("data-src")
                    or img.get("data-original")
                    or img.get("data-lazy-src")
                    or self._best_srcset_url(img.get("srcset"))
                )
                if not url:
                    continue
                img["src"] = url

            if not img.get("alt"):
                figure = img.find_parent("figure")
                caption = figure.find("figcaption") if figure else None
                if caption and caption.get_text().strip():
                    img["alt"] = caption.get_text().strip()

    def _flatten_inline_formatting(self, soup: BeautifulSoup) -> None:
        """
        Rewrites inline tags to literal markdown before extraction.

        trafilatura 2.0.0's markdown serialiser mishandles any block whose first
        child is an inline element: a <li> starting with <strong> loses its bullet
        and merges into the previous item, and one starting with <a> is dropped
        outright. Feeding it plain text sidesteps the bug and also preserves the
        inter-element spacing the serialiser otherwise strips.

        Anchors are flattened only inside non-boilerplate list items. Flattening
        them everywhere hides them from trafilatura's link-density heuristic, which
        is how it recognises navigation and ad blocks -- measured to pull sponsor
        markup into the article body on sites whose main content is already
        marginal. Innermost-first so nested tags are rewritten before their parent.
        """
        for tag in reversed(list(soup.find_all([*_INLINE_MARKERS, "a"]))):
            if tag.find_parent("pre"):
                continue
            if tag.name == "a":
                list_item = tag.find_parent("li")
                if not list_item or list_item.find_parent(_BOILERPLATE_CONTAINERS):
                    continue
            text = tag.get_text()
            if not text.strip():
                continue
            if tag.name == "a":
                href = tag.get("href")
                replacement = f"[{text}]({href})" if href else text
            else:
                marker = _INLINE_MARKERS[tag.name]
                replacement = f"{marker}{text}{marker}"
            tag.replace_with(NavigableString(replacement))

    @staticmethod
    def _best_srcset_url(srcset: str | None) -> str | None:
        """Picks the highest-resolution candidate from a srcset attribute."""
        if not srcset:
            return None
        candidates: list[tuple[int, str]] = []
        for candidate in srcset.split(","):
            parts = candidate.strip().split()
            if not parts:
                continue
            width = 0
            if len(parts) > 1 and parts[1].endswith("w"):
                try:
                    width = int(parts[1][:-1])
                except ValueError:
                    width = 0
            candidates.append((width, parts[0]))
        return max(candidates)[1] if candidates else None

    async def _mirror_markdown_images(self, md: str, doc_id: str, base_url: str) -> str:
        """Finds ![alt](url) in markdown, downloads them, and updates to local path."""
        import cloudscraper

        img_re = re.compile(r"!\[(.*?)\]\((.*?)\)")
        settings = get_settings()
        images_dir = Path(settings.DATA_DIR).expanduser() / "images" / doc_id
        images_dir.mkdir(parents=True, exist_ok=True)

        async def replace_match(match):
            alt = match.group(1)
            url = match.group(2)
            if url.startswith("__LUMINARY_IMG__") or url.startswith("data:"):
                return match.group(0)

            # Trafilatura emits root-relative or protocol-relative src; resolve
            # against the article URL so the download has a scheme + host.
            url = urljoin(base_url, url)

            try:
                ext = url.split(".")[-1].split("?")[0].lower()
                if len(ext) > 4 or len(ext) < 2:
                    ext = "png"
                filename = f"{hashlib.md5(url.encode()).hexdigest()}.{ext}"
                dest_path = images_dir / filename

                if not dest_path.exists():
                    scraper = cloudscraper.create_scraper()
                    resp = await asyncio.to_thread(scraper.get, url, timeout=300.0)
                    if resp.status_code == 200:
                        dest_path.write_bytes(resp.content)

                return f"![{alt}](__LUMINARY_IMG__/{doc_id}/{filename})"
            except Exception as e:
                logger.warning("Failed to mirror image %s: %s", url, e)
                return match.group(0)

        # This is a bit complex for a regex replace, so we do it manually
        new_md = md
        for match in list(img_re.finditer(md)):
            original = match.group(0)
            replacement = await replace_match(match)
            new_md = new_md.replace(original, replacement)

        return new_md

    def _normalize_markdown(self, text: str) -> str:
        """Fixes common markdown parsing issues."""
        # Fix #Header -> # Header (ensure space after hashes)
        text = re.sub(r"^(#{1,6})([^\s#])", r"\1 \2", text, flags=re.M)
        # Ensure double newlines before headers for proper block separation
        text = re.sub(r"([^\n])\n(#{1,6}\s)", r"\1\n\n\2", text)
        return text


_extractor = ArticleExtractor()


def get_article_extractor() -> ArticleExtractor:
    return _extractor
