"""Running heads, footers and page numbers: text a PDF prints on every page, not prose.

Left in, they land mid-sentence in the stored text ("two families of 69 storage engines"),
where a quote check cannot match them, a card can be written from them and the reader shows
them as paragraphs. Only text that recurs in a page margin goes: a chapter title or a single
folio printed once is content, and stays.
"""

from __future__ import annotations

import re
from collections import defaultdict

# Running headers and footers sit in the page margins and are short.
MARGIN_FRACTION = 0.1
FURNITURE_MAX_CHARS = 80

# Pages a margin line must recur on to be furniture. A running head repeats on every page
# of a chapter; a heading set at the top of a page appears once, and two pages is still
# too few to tell a repeated label from a running head.
MIN_RUNNING_PAGES = 3

_DIGITS = re.compile(r"\d+")
_WHITESPACE = re.compile(r"\s+")


def in_margin(top: float, bottom: float, page_height: float) -> bool:
    margin = page_height * MARGIN_FRACTION
    return bottom <= margin or top >= page_height - margin


def signature(text: str) -> str:
    """The line with its numbers blanked, so "74 | Chapter 3" and "76 | Chapter 3" agree.
    Spaces go too: block text and span-joined text space the same line differently."""
    return _DIGITS.sub("#", _WHITESPACE.sub("", text).lower())


def running_signatures(doc) -> frozenset[str]:
    """Signatures of the short margin lines that recur on MIN_RUNNING_PAGES pages or more."""
    pages: dict[str, set[int]] = defaultdict(set)
    for index, page in enumerate(doc):
        height = float(page.rect.height) or 1.0
        # (x0, y0, x1, y1, text, block_no, block_type); type 0 is text.
        for block in page.get_text("blocks"):
            text = str(block[4]).strip()
            if block[6] != 0 or not 0 < len(text) <= FURNITURE_MAX_CHARS:
                continue
            if in_margin(float(block[1]), float(block[3]), height):
                pages[signature(text)].add(index)
    return frozenset(sig for sig, seen in pages.items() if len(seen) >= MIN_RUNNING_PAGES)


def is_running(
    text: str, top: float, bottom: float, page_height: float, running: frozenset[str]
) -> bool:
    return in_margin(top, bottom, page_height) and signature(text) in running
