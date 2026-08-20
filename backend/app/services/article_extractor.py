import asyncio
import hashlib
import logging
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, NavigableString

from app.config import get_settings
from app.full_extras import require_extra
from app.services.html_region import region_is_plausible, select_region
from app.services.html_to_markdown import to_markdown
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

# Substrings that betray a client-hydrated JavaScript page across the common
# SSR frameworks. Their presence means the initial HTML we fetch is a hydration
# shell: prose is often server-rendered, but figures drawn by client-only
# components (charts, diagrams, canvases) exist only after JS runs in a browser,
# which a static fetch never does. Matched case-insensitively.
_JS_HYDRATION_MARKERS = (
    "__next_data__",
    "self.__next_f",
    "__nuxt__",
    "data-server-rendered",
    "data-reactroot",
    "astro-island",
    "data-sveltekit",
    "dehydratedstate",
    "dehydrateddata",
    "dehydratedqueryclient",
    "stream-barrier",
)

# Below this word count the page is not a real article, so a lack of images is
# unremarkable and must not trigger a warning.
_MIN_ARTICLE_WORDS_FOR_VISUAL_WARNING = 200

# Placeholder tokens for content restored after extraction. Letters and digits
# only, and long enough that no article writes one by accident: trafilatura
# normalises punctuation and drops paragraphs that read as bare symbols.
_MARK_PREFIX = "LUMINARYPROTECTEDBLOCK"
_MARK_SUFFIX = "ENDPROTECTED"

# An <svg> is content only when it is drawn large in BOTH axes. Markup length is
# a bad proxy and position alone is not enough: measured across seven real
# articles, every inline <svg> that passed a 400-character floor was chrome --
# a 12x6.13 nav chevron whose path data runs to 631 characters, Tailwind `h-5 w-5`
# icons at 20px, and a 570x64 logo wordmark that is wide but only a strip tall.
# Requiring both axes rejects the wordmark, which a single-axis rule would keep.
# Not one of those pages carried a real inline-SVG diagram, so this path stays
# silent by design rather than reporting furniture as lost figures.
_SVG_CHROME_ANCESTORS = (*_BOILERPLATE_CONTAINERS, "button", "a", "form", "summary", "details")
_MIN_SVG_DIMENSION = 200


def _svg_dimensions(svg) -> tuple[float, float] | None:
    """Rendered size from width/height, else the viewBox. None when undeclared."""

    def _num(raw: str | None) -> float | None:
        if not raw:
            return None
        match = re.match(r"\s*([0-9]*\.?[0-9]+)\s*(px)?\s*$", raw)
        return float(match.group(1)) if match else None

    width, height = _num(svg.get("width")), _num(svg.get("height"))
    if width and height:
        return width, height
    box = (svg.get("viewBox") or "").replace(",", " ").split()
    if len(box) == 4:
        try:
            return abs(float(box[2])), abs(float(box[3]))
        except ValueError:
            return None
    return None


def _decoded(response) -> str:
    """Decode the body by what it is, not by what HTTP defaults to.

    RFC 9110 says a `text/*` response with no `charset` is ISO-8859-1, and
    requests obeys it -- so a UTF-8 page that omits the parameter comes back with
    every curly quote, dash and accent mangled. Measured on a real article:
    a right single quote (U+2019) arrived as the three characters it encodes to
    under latin-1, and 24 such sequences were stored as the document's text.

    A declared charset is the server's own statement and is trusted. Only when
    none is declared do we fall back to detection.
    """
    content_type = (response.headers.get("content-type") or "").lower()
    if "charset=" not in content_type:
        detected = response.apparent_encoding
        if detected:
            response.encoding = detected
    return response.text


def _describe_block(markdown: str) -> str:
    """Name a protected block by what it is, for the report the reader sees."""
    if markdown.startswith("```"):
        return "code block"
    if markdown.startswith("!["):
        return "diagram"
    return "formula"


def _wrap_tex(tex: str, display: bool) -> str:
    """TeX as markdown math. Display math takes its own block."""
    return f"$$\n{tex}\n$$" if display else f"${tex}$"


_INLINE_MARKERS = {
    "strong": "**",
    "b": "**",
    "em": "*",
    "i": "*",
    "code": "`",
}


# Separators sites put between a page title and the site name.
_TITLE_SEPARATORS = " |-–—·»:"

# Below this a recovered head is more likely a fragment than a title ("Ch 4"),
# and keeping the metadata title is the safer answer.
_MIN_RECOVERED_TITLE_CHARS = 12


def _title_specific_to_this_page(title: str, html: str) -> str:
    """Recover a page title that `og:title` gave over to the site name.

    Metadata is trusted first because it is usually right. It is wrong in one
    specific, common way: a site that sets one `og:title` for every page. Every
    chapter of one book imported as "The Builder's Gita", so a library of them
    was a list of identical rows and the reader could not tell which they had
    opened.

    The `<title>` tag still carried "Chapter 4: Databases — Where Data Lives —
    The Builder's Gita". The site name conventionally goes **last**, so the
    metadata title being a *suffix* of `<title>` is the signal that it named the
    site rather than the page. Both cases that decide this are real:
    "Attention? Attention! | Lil'Log" has its metadata as a *prefix* and is
    already correct, so the rule must not fire there.
    """
    if not title or not html:
        return title
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if not match:
        return title

    document_title = unescape(match.group(1)).strip()
    metadata_title = unescape(title).strip()
    if not document_title.lower().endswith(metadata_title.lower()):
        return title
    if len(document_title) <= len(metadata_title):
        return title

    head = document_title[: len(document_title) - len(metadata_title)]
    head = head.strip().strip(_TITLE_SEPARATORS).strip()
    return head if len(head) >= _MIN_RECOVERED_TITLE_CHARS else title


class ArticleExtractor:
    """
    Unified article extraction for a high-fidelity reading experience.
    """

    async def extract(
        self, url: str, doc_id: str | None = None, rendered_html: str | None = None
    ) -> ParsedDocument:
        logger.info("Extracting unified article from URL: %s", url)

        require_extra("cloudscraper", "URL article extraction")
        require_extra("trafilatura", "URL article extraction")
        import cloudscraper
        import trafilatura

        # HTML the caller already rendered, if any. The desktop shell can load a
        # page in a hidden webview -- the OS one it already ships -- and hand the
        # post-JS DOM here. That matters only for pages that *compute* their
        # content: measured across four JS-heavy articles, rendering changed
        # nothing on three, and on the fourth it was the difference between 0 and
        # 78 figures. Everywhere else (dev, Docker, the script installs) this is
        # None and the static fetch below is the whole story.
        html_content = rendered_html or None
        fetch_mode = "webview" if html_content else "static"

        # 1. Fetch with Cloudflare bypass
        try:
            if html_content is None:
                scraper = cloudscraper.create_scraper()
                response = await asyncio.to_thread(scraper.get, url, timeout=15)
                if response.status_code == 200:
                    html_content = _decoded(response)
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
        title = _title_specific_to_this_page(title, html_content)
        # Mirror images under the caller's document_id so image_extract_handler
        # (which scans images/{document_id}) finds them. Fall back to a URL hash
        # only when called outside the ingestion flow.
        doc_id = doc_id or hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()

        # 3. Mirror Images AND Extract Markdown in one pass
        # We let trafilatura handle the extraction first to find the "real" content
        prepared_html, protected = self._prepare_html(html_content, doc_id)
        reference = trafilatura.extract(
            prepared_html,
            url=url,
            output_format="markdown",
            include_links=True,
            include_images=True,
            include_formatting=True,
            include_tables=True,
            # Recall over precision. A reading app can survive a stray line of
            # furniture; it cannot survive losing a section of the article, and
            # the reader has no original to compare against. Measured across
            # seven articles: this recovers 502 words on a Next.js page whose
            # <ol> sections were being pruned from inside <article> (63% -> 100%
            # of prose), and leaves the other six byte-identical with no
            # boilerplate pulled in.
            favor_recall=True,
        )

        # Serialise the article subtree ourselves; fall back to trafilatura's own
        # output when our region cannot be trusted. It decides content well and
        # structure badly -- on a custom-element page its pruned tree holds zero
        # headings, so a page extracted through it reads as one unbroken wall.
        markdown_text, serializer = self._serialize(prepared_html, reference or "")

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

        # 5. Measure fidelity BEFORE restoring, then restore. Order is
        # load-bearing: restoration replaces every token with its content, so a
        # report taken afterwards finds no tokens and calls a clean import a
        # total loss. Restore after mirroring, never before -- a fenced block can
        # legitimately contain an ![alt](url) line the mirror pass would fetch.
        dropped = self._dropped_blocks(markdown_text, protected)
        markdown_text = self._restore_protected(markdown_text, protected)

        # 6. Normalize Markdown (The "### Fix")
        markdown_text = self._normalize_markdown(markdown_text)

        word_count = len(markdown_text.split())
        warnings = self._detect_uncaptured_visuals(
            html_content, markdown_text, word_count, fetch_mode
        )
        report = self._extraction_report(markdown_text, dropped, warnings)
        # Two independent choices, recorded separately: how the HTML was obtained,
        # and what turned it into Markdown. Collapsing them into one field makes a
        # regression in either impossible to attribute.
        report["fetch"] = fetch_mode
        report["serializer"] = serializer
        for warning in warnings:
            logger.info("ArticleExtractor notice for %s: %s", url, warning)
        if report["dropped"]:
            logger.warning("ArticleExtractor dropped content for %s: %s", url, report["dropped"])

        # For Articles, we keep them as one primary "Section" to ensure unified flow in UI
        sections = [Section(heading=title, level=1, text=markdown_text, page_start=0, page_end=0)]

        return ParsedDocument(
            title=title,
            format="md",
            pages=1,
            word_count=word_count,
            sections=sections,
            raw_text=markdown_text,
            warnings=warnings,
            extraction_report=report,
        )

    def _detect_uncaptured_visuals(
        self, html: str, markdown: str, word_count: int, fetch_mode: str = "static"
    ) -> list[str]:
        """Warns when a page's figures were almost certainly lost to static fetching.

        A static HTTP fetch cannot run JavaScript, so figures drawn by client-only
        components (chart/diagram widgets, canvases) are absent from the HTML we
        receive and vanish silently. We cannot see those unrendered components to
        count them, so we infer the loss from a conservative signature: a real
        article's worth of prose came through, yet not a single image did, on a
        page that is a client-hydrated JS app. A plain static text-only article
        trips none of these (no hydration markers), and any page from which we did
        mirror an image is left alone -- keeping false positives rare.

        **The inference only holds for the static path.** Once the page has been
        rendered, its scripts have run and what the browser drew is what we saw,
        so "no images" means the page has none rather than that we missed them.
        Inferring anyway told a reader that content was missing from a chapter of
        prose and code that had no figures at all -- and a warning that fires when
        nothing is wrong is one the reader learns to scroll past, which costs the
        warnings that are real. After rendering, only a `<canvas>` still justifies
        it: its pixels need a screenshot, which a DOM capture does not take.
        """
        if word_count < _MIN_ARTICLE_WORDS_FOR_VISUAL_WARNING:
            return []
        if "![" in markdown:
            return []
        lowered = html.lower()
        if fetch_mode == "webview":
            return (
                [
                    "Some figures on this page are drawn onto a canvas by the browser "
                    "and could not be captured. The text was imported in full."
                ]
                if "<canvas" in lowered
                else []
            )
        if not any(marker in lowered for marker in _JS_HYDRATION_MARKERS):
            return []
        return [
            "Some figures on this page are drawn by JavaScript in the browser and "
            "could not be captured. The text was imported in full; interactive "
            "charts or diagrams may be missing."
        ]

    def _prepare_html(self, html: str, doc_id: str) -> tuple[str, dict[str, str]]:
        """Repairs markup that trafilatura's extractor silently drops.

        Returns the repaired HTML plus a token -> markdown map for content that
        cannot survive extraction as markup and is restored afterwards. Measured
        losses that these passes exist to close: code blocks come back with every
        leading space stripped and no language, inline math takes the words after
        it with it, figure captions vanish, and an inline <svg> extracts as
        nothing at all.
        """
        soup = BeautifulSoup(html, "html.parser")
        protected: dict[str, str] = {}
        # Order matters: hydrate first so a lazy <img> inside a <figure> has a
        # src before the figure is rewritten, and protect <pre> before the
        # inline pass, which must never reach inside a code block.
        self._hydrate_lazy_images(soup)
        self._inline_svg_to_img(soup, doc_id, protected)
        self._promote_figcaptions(soup)
        self._protect_code_blocks(soup, protected)
        self._protect_math(soup, protected)
        self._flatten_inline_formatting(soup)
        return str(soup), protected

    def _serialize(self, prepared_html: str, reference: str) -> tuple[str, str]:
        """Our Markdown if the region holds up, else the reference extraction.

        Returns the markdown and the name of what produced it, so the extraction
        report can record which path a document came through instead of leaving
        the difference invisible.
        """
        try:
            region = select_region(prepared_html)
            if region_is_plausible(region, reference):
                mine = to_markdown(region)
                if len(mine.split()) >= len(reference.split()) * 0.9:
                    return mine, "region"
                logger.info("region serialiser under-produced; using reference extraction")
            else:
                logger.info("region failed the plausibility check; using reference extraction")
        except Exception:
            logger.warning("region serialiser failed; using reference extraction", exc_info=True)
        return reference, "trafilatura"

    def _token(self, protected: dict[str, str], markdown: str) -> str:
        """Mint a placeholder trafilatura will carry through as ordinary text.

        Letters and digits only: any punctuation risks being normalised, and a
        token that reads as a bare symbol invites the boilerplate heuristics to
        drop the paragraph holding it.
        """
        token = f"{_MARK_PREFIX}{len(protected):04d}{_MARK_SUFFIX}"
        protected[token] = markdown
        return token

    def _protect_code_blocks(self, soup: BeautifulSoup, protected: dict[str, str]) -> None:
        """Fence each <pre> verbatim, keeping indentation and language.

        trafilatura strips every leading space inside <pre><code>, which for
        Python is not a cosmetic loss -- the code stops meaning what it said.
        """
        for pre in soup.find_all("pre"):
            code = pre.find("code")
            text = (code or pre).get_text()
            text = text.replace("\r\n", "\n").strip("\n")
            if not text.strip():
                continue
            lang = self._code_language(pre) or self._code_language(code)
            fence = "```" + (lang or "") + "\n" + text + "\n```"
            placeholder = soup.new_tag("p")
            placeholder.string = self._token(protected, fence)
            pre.replace_with(placeholder)

    @staticmethod
    def _code_language(tag) -> str | None:
        """Language from a `language-x` / `lang-x` / bare `x` class, if any."""
        if tag is None:
            return None
        for cls in tag.get("class") or []:
            for prefix in ("language-", "lang-", "highlight-"):
                if cls.startswith(prefix) and len(cls) > len(prefix):
                    return cls[len(prefix) :]
        return None

    def _protect_math(self, soup: BeautifulSoup, protected: dict[str, str]) -> None:
        """Keep the TeX, and the sentence it sits in.

        A rendered KaTeX span is a tree of presentational elements; trafilatura
        drops it and takes the rest of the text node with it, so `Loss <math>
        here.` extracted as `Loss`. The formula is replaced inline by a token so
        the surrounding prose is never orphaned.
        """
        for script in soup.find_all("script", attrs={"type": re.compile(r"math/tex")}):
            tex = script.get_text().strip()
            display = "mode=display" in (script.get("type") or "")
            if tex:
                script.replace_with(
                    NavigableString(self._token(protected, _wrap_tex(tex, display)))
                )

        for node in soup.select(".katex, mjx-container"):
            annotation = node.find("annotation", attrs={"encoding": "application/x-tex"})
            tex = annotation.get_text().strip() if annotation else ""
            if not tex:
                continue
            classes = node.get("class") or []
            display = "katex-display" in classes or node.get("display") == "true"
            node.replace_with(NavigableString(self._token(protected, _wrap_tex(tex, display))))

    def _promote_figcaptions(self, soup: BeautifulSoup) -> None:
        """Lift <figcaption> out of its <figure> so it survives as prose.

        trafilatura emits the image and drops the caption, which in a technical
        article is where the figure is actually explained.
        """
        for figure in soup.find_all("figure"):
            caption = figure.find("figcaption")
            if caption is None:
                continue
            text = caption.get_text(" ", strip=True)
            caption.extract()
            if not text:
                continue
            para = soup.new_tag("p")
            para.append(soup.new_string(text))
            figure.insert_after(para)

    def _inline_svg_to_img(
        self, soup: BeautifulSoup, doc_id: str, protected: dict[str, str]
    ) -> None:
        """Mirror inline <svg> to the document's image dir and link it.

        An inline <svg> extracts as nothing whatsoever -- not the graphic, not a
        placeholder -- so architecture diagrams disappear without trace. Writing
        it out turns it into an ordinary image the rest of the pipeline handles.
        """
        svgs = soup.find_all("svg")
        if not svgs:
            return
        images_dir = Path(get_settings().DATA_DIR).expanduser() / "images" / doc_id
        for svg in svgs:
            if any(p.name in _SVG_CHROME_ANCESTORS for p in svg.parents):
                continue
            size = _svg_dimensions(svg)
            if size is None or min(size) < _MIN_SVG_DIMENSION:
                continue
            markup = str(svg)
            name = hashlib.md5(markup.encode(), usedforsecurity=False).hexdigest() + ".svg"
            try:
                images_dir.mkdir(parents=True, exist_ok=True)
                (images_dir / name).write_text(markup, encoding="utf-8")
            except OSError as exc:
                logger.warning("Could not mirror inline svg for %s: %s", doc_id, exc)
                continue
            # A token rather than an <img>: trafilatura validates the src and
            # drops `__LUMINARY_IMG__/...`, which is a local convention and not a
            # URL, so the mirrored diagram vanished exactly as the inline svg had.
            alt = svg.get("aria-label") or "Diagram"
            placeholder = soup.new_tag("p")
            placeholder.string = self._token(
                protected, f"![{alt}](__LUMINARY_IMG__/{doc_id}/{name})"
            )
            svg.replace_with(placeholder)

    @staticmethod
    def _restore_protected(markdown: str, protected: dict[str, str]) -> str:
        """Put the protected blocks back where their tokens landed."""
        for token, replacement in protected.items():
            markdown = markdown.replace(token, replacement)
        return markdown

    @staticmethod
    def _dropped_blocks(markdown: str, protected: dict[str, str]) -> list[str]:
        """Protected blocks whose token never reached the output.

        This is an exact signal, not a heuristic: we know precisely what was set
        aside, so a token that is absent means extraction discarded the paragraph
        holding it. Counting raw <img> or <pre> tags in the source instead would
        charge us for every nav logo and share widget trafilatura correctly
        removes, and a warning that cries wolf is not a warning.
        """
        return [
            _describe_block(body) for token, body in protected.items() if token not in markdown
        ]

    def _extraction_report(self, markdown: str, dropped: list[str], notes: list[str]) -> dict:
        """What arrived, and what did not.

        Persisted with the document so an incomplete import is visible to whoever
        reads it, rather than a silence the reader has no way to interpret.
        `dropped` must be measured before restoration -- see the call site.
        """
        counts: dict[str, int] = {}
        for kind in dropped:
            counts[kind] = counts.get(kind, 0) + 1
        return {
            "captured": {
                "code_blocks": markdown.count("```") // 2,
                "images": len(re.findall(r"!\[[^\]]*\]\(", markdown)),
                "tables": len(re.findall(r"^\|[-\s|:]+\|$", markdown, flags=re.M)),
                "math": len(re.findall(r"\$[^$\n]+\$", markdown)),
            },
            "dropped": counts,
            "notes": notes,
            "complete": not counts and not notes,
        }

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
                filename = f"{hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()}.{ext}"
                dest_path = images_dir / filename

                if not dest_path.exists():
                    scraper = cloudscraper.create_scraper()
                    resp = await asyncio.to_thread(scraper.get, url, timeout=300.0)
                    if resp.status_code == 200:
                        await asyncio.to_thread(dest_path.write_bytes, resp.content)

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
