"""Serialise an article subtree to Markdown.

Written rather than borrowed because the alternative loses structure: a
boilerplate remover keeps whatever survives its own content selection, which on
custom-element pages is the prose without any of the headings. Markdown is the
one representation every Luminary format converges on, and `sections.body` is
rendered through MarkdownRenderer already.

Every rule here comes from a measured failure, named at the rule.
"""

import logging
import re

from bs4 import NavigableString, Tag

logger = logging.getLogger(__name__)

_BLOCK_SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "form", "button"}

# Anchor links authors append to headings for deep-linking. They render as junk
# in the reading view: measured, all 21 headings of one article carried one.
_ANCHOR_ONLY = re.compile(r"^\s*(#|¶|§|link|permalink|anchor)\s*$", re.I)

_INLINE_WRAP = {"strong": "**", "b": "**", "em": "*", "i": "*", "del": "~~", "s": "~~"}

# Callout containers keep their text but lose their box; the words are what matter.
_CALLOUT_HINT = re.compile(r"callout|admonition|note|warning|tip|caution|info-box", re.I)

# A class naming an element a caption is the author saying it labels a figure.
_CAPTION_HINT = re.compile(r"caption", re.I)


def _is_caption(node: Tag) -> bool:
    """Whether the author marked this element as a figure caption."""
    return any(_CAPTION_HINT.search(name) for name in (node.get("class") or []))


def _collapse(text: str) -> str:
    """Collapse whitespace runs WITHOUT trimming the ends.

    Trimming here is what turns `is a <a>bidirectional RNN</a> (or other` into
    `is a[bidirectional RNN](url)(or other`: the space between a text node and the
    element beside it is the only thing separating those words. Trimming belongs
    at block boundaries, never between inline siblings -- the same trap
    `_flatten_inline_formatting` in article_extractor.py already warns about.
    """
    return re.sub(r"\s+", " ", text)


def _clean(text: str) -> str:
    return _collapse(text).strip()


class MarkdownSerializer:
    """DOM -> Markdown. Stateless apart from the footnote table it accumulates."""

    def __init__(self, protect: dict[str, str] | None = None) -> None:
        # Tokens minted by the extractor's protection passes (code, math, mirrored
        # SVG). They arrive as opaque text and must pass through untouched.
        self._protect = protect or {}
        self._footnotes: list[tuple[str, str]] = []

    # -- inline ---------------------------------------------------------------

    def _inline(self, node) -> str:
        if isinstance(node, NavigableString):
            return _collapse(str(node))
        if not isinstance(node, Tag):
            return ""
        name = node.name
        if name in _BLOCK_SKIP:
            return ""
        if name == "br":
            return "\n"
        if name == "code":
            text = node.get_text()
            return f"`{text}`" if text.strip() else ""
        if name == "img":
            src = node.get("src") or ""
            return f"![{_clean(node.get('alt') or '')}]({src})" if src else ""
        if name == "a":
            text = self._children_inline(node)
            href = node.get("href") or ""
            # An anchor whose whole text is "#" is a deep-link affordance, not content.
            if _ANCHOR_ONLY.match(text) or not text:
                return ""
            return f"[{text}]({href})" if href and not href.startswith("javascript:") else text
        if name in _INLINE_WRAP:
            text = self._children_inline(node)
            mark = _INLINE_WRAP[name]
            return f"{mark}{text}{mark}" if text else ""
        if name == "sup":
            text = self._children_inline(node)
            return f"[^{text}]" if text else ""
        return self._children_inline(node)

    def _children_inline(self, node: Tag) -> str:
        parts = [self._inline(child) for child in node.children]
        return _clean("".join(parts))

    # -- blocks ---------------------------------------------------------------

    def _list(self, node: Tag, depth: int) -> list[str]:
        ordered = node.name == "ol"
        pad = "  " * depth
        out: list[str] = []
        index = 1
        for item in node.find_all("li", recursive=False):
            nested = list(item.find_all(["ul", "ol"], recursive=False))
            for child in nested:
                child.extract()
            text = self._children_inline(item)
            marker = f"{index}." if ordered else "-"
            if text:
                out.append(f"{pad}{marker} {text}")
                index += 1
            for child in nested:
                out.extend(self._list(child, depth + 1))
        return out

    def _table(self, node: Tag) -> list[str]:
        rows: list[list[str]] = []
        for tr in node.find_all("tr"):
            cells = [self._children_inline(td) for td in tr.find_all(["td", "th"], recursive=False)]
            if cells:
                rows.append(cells)
        if not rows:
            return []
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        head, *body = rows
        out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * width) + "|"]
        out += ["| " + " | ".join(r) + " |" for r in body]
        return out

    def _block(self, node, depth: int = 0) -> list[str]:
        if isinstance(node, NavigableString):
            text = _clean(str(node))
            return [text] if text else []
        if not isinstance(node, Tag) or node.name in _BLOCK_SKIP:
            return []

        name = node.name
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = self._children_inline(node)
            if not text:
                return []
            # A heading the author marked as a caption labels a figure, not a
            # section of the document. One article carried 13 of them, all
            # reading "Original" -- the label under each comparison image -- and
            # each became a section in the contents beside the real chapters.
            # The text is kept: it is what names the figure.
            if _is_caption(node):
                return [text]
            return [f"{'#' * int(name[1])} {text}"]
        if name == "p":
            text = self._children_inline(node)
            return [text] if text else []
        if name in ("ul", "ol"):
            return self._list(node, depth)
        if name == "table":
            return self._table(node)
        if name == "blockquote":
            inner = [line for child in node.children for line in self._block(child, depth)]
            return [f"> {line}" for line in inner if line]
        if name == "pre":
            # Code has already been protected upstream; a bare <pre> reaching here
            # keeps its text verbatim rather than being collapsed to one line.
            text = node.get_text().strip("\n")
            return ["```", *text.split("\n"), "```"] if text.strip() else []
        if name == "figure":
            return self._figure(node, depth)
        if name == "figcaption":
            text = self._children_inline(node)
            return [text] if text else []
        if name == "img":
            line = self._inline(node)
            return [line] if line else []
        if name == "hr":
            return ["---"]
        if name == "details":
            return self._details(node, depth)
        if name == "dl":
            return self._definition_list(node)

        return self._descend(node, depth)

    def _figure(self, node: Tag, depth: int) -> list[str]:
        """Image then caption, both kept.

        The caption is where a technical article explains its figure, and a plain
        extraction drops it while keeping the image.
        """
        out: list[str] = []
        for img in node.find_all("img"):
            line = self._inline(img)
            if line:
                out.append(line)
        for caption in node.find_all("figcaption"):
            text = self._children_inline(caption)
            if text:
                out.append(text)
        return out or self._descend(node, depth)

    def _details(self, node: Tag, depth: int) -> list[str]:
        """A collapsed section is still content; readers must not lose it."""
        out: list[str] = []
        summary = node.find("summary")
        if summary is not None:
            text = self._children_inline(summary)
            summary.extract()
            if text:
                out.append(f"**{text}**")
        out.extend(self._descend(node, depth))
        return out

    def _definition_list(self, node: Tag) -> list[str]:
        out: list[str] = []
        for child in node.find_all(["dt", "dd"], recursive=False):
            text = self._children_inline(child)
            if text:
                out.append(f"**{text}**" if child.name == "dt" else f": {text}")
        return out

    def _descend(self, node: Tag, depth: int) -> list[str]:
        out: list[str] = []
        for child in node.children:
            out.extend(self._block(child, depth))
        return out

    # -- entry point ----------------------------------------------------------

    def serialize(self, region: Tag) -> str:
        blocks = self._descend(region, 0)
        # Collapse runs of blank output without joining two real paragraphs.
        lines: list[str] = []
        for block in blocks:
            if not block:
                continue
            if lines and lines[-1] == block:
                continue  # a caption duplicated as alt text and again as prose
            lines.append(block)
        return "\n\n".join(lines).strip() + "\n"


def to_markdown(region: Tag, protect: dict[str, str] | None = None) -> str:
    return MarkdownSerializer(protect).serialize(region)
