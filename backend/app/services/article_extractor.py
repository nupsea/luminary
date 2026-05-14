import asyncio
import hashlib
import logging
import re
from pathlib import Path

import cloudscraper
import httpx
import trafilatura

from app.config import get_settings
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


class ArticleExtractor:
    """
    Unified article extraction for a high-fidelity reading experience.
    """

    async def extract(self, url: str) -> ParsedDocument:
        logger.info("Extracting unified article from URL: %s", url)

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
        doc_id = hashlib.md5(url.encode()).hexdigest()

        # 3. Mirror Images AND Extract Markdown in one pass
        # We let trafilatura handle the extraction first to find the "real" content
        markdown_text = trafilatura.extract(
            html_content,
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
        # Trafilatura outputs markdown like ![alt](url)
        markdown_text = await self._mirror_markdown_images(markdown_text, doc_id)

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

    async def _mirror_markdown_images(self, md: str, doc_id: str) -> str:
        """Finds ![alt](url) in markdown, downloads them, and updates to local path."""
        img_re = re.compile(r"!\[(.*?)\]\((.*?)\)")
        settings = get_settings()
        images_dir = Path(settings.DATA_DIR).expanduser() / "images" / doc_id
        images_dir.mkdir(parents=True, exist_ok=True)

        async def replace_match(match):
            alt = match.group(1)
            url = match.group(2)
            if url.startswith("__LUMINARY_IMG__"):
                return match.group(0)

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
