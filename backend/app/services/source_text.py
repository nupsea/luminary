"""Decode a text source and remove the page furniture a web scrape left in it.

Three parsers previously decoded text themselves — `parser._parse_txt`,
`BookParser.parse` and `UniversalParser._read_text` — each with its own chardet
call. Decoding is one job, so it lives here once and they call it.

**Why furniture removal belongs in ingestion.** A document captured by scraping a
site carries that site's navigation, footers and any error page the scrape walked
into, interleaved with the prose rather than bracketing it, because every page
contributes its own chrome. Luminary ingests web content as a first-class path
(`POST /documents/ingest-url`), so this reaches a real library, not just a test
corpus: nav lines become chunks, retrieval returns them, and entity extraction
turns the site's own name into a document tag.

**How it is detected.** Structurally, never by keyword — a keyword list only
recognises the sites someone already looked at. Furniture is text that repeats
verbatim: prose does not appear eight times in a document, and navigation does.
A run of consecutive lines that each recur is furniture, whatever it says, in
whatever language.

Measured over the 14 text corpora in DATA: 18.6% of the one scraped document
removed (403 lines of 2166), and **nothing at all from the other 13**, including
two verse texts and a legal corpus whose repetition would defeat a naive
frequency filter.

Consecutive is literal, and that is the limit of the detector: a blank line
between two furniture lines ends the run, so a scrape that double-spaces its
navigation is not collapsed. Relaxing it — blanks neutral, neither breaking a
run nor counting toward it — was measured and rejected: it deletes Hamlet's
repeated speaker exchanges, the Federalist Papers' per-paper bylines and Alice's
scene breaks. Those are content at that position which happens to recur, and no
frequency rule can tell them from a pager.

This matters for I-30. A scrape repeats a chapter heading as heading, breadcrumb
and body text, so the heading sits inside a furniture run, and a filter that
deletes runs outright removes an authored label entirely — measured on the
scraped corpus, deleting runs loses 8 of its 10 chapter headings, collapsing
them loses none.

The rule is a collapse, never a delete: a line is dropped only where the
document still holds it elsewhere. That makes losing content impossible by
construction rather than by threshold, at the cost of leaving one instance of
each furniture line behind.
"""

from __future__ import annotations

import html
import logging
from collections import Counter
from pathlib import Path

import chardet

logger = logging.getLogger(__name__)

# A line must recur at least this often to count as furniture at all.
_MIN_REPEATS = 3
# ...and that many must sit consecutively. One repeated line is a refrain; a
# block of them is a template.
_MIN_RUN = 3


def _collapse_repeated_furniture(lines: list[str]) -> list[str]:
    """Collapse runs of recurring lines to a single instance of each line.

    Collapse, not delete: a line is removed only where the document still holds
    it somewhere else. Nothing distinct is ever lost, so an authored label that
    a scrape happened to bury inside its navigation survives (I-30) without the
    function needing to tell a heading from a pager. Trying to make that
    distinction is what a frequency threshold does, and it is guesswork -- it
    silently deletes any label that recurs more often than the furniture does.

    The residue is one instance of each furniture line: 403 lines removed on the
    scraped corpus, 61 left standing, against zero risk of dropping content.
    """
    freq = Counter(line.strip() for line in lines if line.strip())
    recurring = [bool(ln.strip()) and freq[ln.strip()] >= _MIN_REPEATS for ln in lines]

    in_run = [False] * len(lines)
    i = 0
    while i < len(lines):
        if not recurring[i]:
            i += 1
            continue
        j = i
        while j < len(lines) and recurring[j]:
            j += 1
        if j - i >= _MIN_RUN:
            for k in range(i, j):
                in_run[k] = True
        i = j

    if not any(in_run):
        return lines

    # Everything outside a run stays, and each distinct line inside one keeps
    # its first occurrence.
    seen = {ln.strip() for k, ln in enumerate(lines) if not in_run[k] and ln.strip()}
    kept: list[str] = []
    for k, line in enumerate(lines):
        if not in_run[k]:
            kept.append(line)
            continue
        text = line.strip()
        if text and text not in seen:
            seen.add(text)
            kept.append(line)
    return kept


def normalise(text: str) -> str:
    """Unescape HTML entities and drop scrape furniture. Pure, not idempotent.

    `&nbsp;` unescapes to U+00A0, so unescaping alone trades one artifact for
    another: a non-breaking space splits phrases for anything matching on
    whitespace, including the eval's own hint matching.

    One pass, deliberately. Removing a run makes lines that were separated
    adjacent, so a second pass finds new runs and keeps nibbling — 403 lines on
    the first pass over the scraped corpus, then one per pass indefinitely. Every
    caller normalises the original file, so chasing a fixed point would only cost
    content.
    """
    unescaped = html.unescape(text).replace("\xa0", " ")
    lines = unescaped.splitlines()
    kept = _collapse_repeated_furniture(lines)
    if len(kept) != len(lines):
        logger.info(
            "source_text: removed %d furniture lines of %d", len(lines) - len(kept), len(lines)
        )
    return "\n".join(kept)


def decode(raw_bytes: bytes) -> str:
    """Bytes to text, guessing the encoding. Never raises on a bad byte."""
    encoding = chardet.detect(raw_bytes).get("encoding") or "utf-8"
    return raw_bytes.decode(encoding, errors="replace")


def read_source_text(file_path: Path) -> str:
    """Read a text source, decoded and normalised. The one way to read one."""
    return normalise(decode(Path(file_path).read_bytes()))


__all__ = ["decode", "normalise", "read_source_text"]
