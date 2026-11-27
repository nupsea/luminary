"""What a quiz question may be written from: a passage worth testing and the sentence it tests.

Code picks the sentence and the model only phrases a question about it, as for unit-first cards:
a model asked to choose what is worth testing wrote about licences and tables of contents (#191).
Pure module: no I/O, no LLM calls.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.services.flashcard_units import _LEADING_LABEL, _learnable_words, split_units

# Chunks repeat the tail of the one before (the chunker's overlap). Shorter shared runs are
# ordinary repetition, not overlap.
_MIN_OVERLAP_CHARS = 20
_MAX_OVERLAP_CHARS = 1200

# A contents page: most lines are headings ("CHAPTER 73. Stubb and Flask kill a Right Whale;").
_HEADING_LINE = re.compile(
    r"^\s*(?:chapter|part|book|section|appendix|act|scene)\b[\s\dIVXLC.:-]*", re.IGNORECASE
)
_CONTENTS_SHARE = 0.4
# A quotation collection: each excerpt ends with its attribution ("— Paradise Lost .").
_ATTRIBUTION = re.compile(r"(?:^\s*|[”\"]\s*)[—–]{1,2}\s*[\"“]?[A-Z]", re.MULTILINE)
_MAX_ATTRIBUTIONS = 2
# Distribution terms, licences and colophons: about the file, not of the work.
_LICENCE = re.compile(
    r"Project Gutenberg|\bthis e-?book\b|all rights reserved|terms of (?:use|the licen[cs]e)",
    re.IGNORECASE,
)
# A reference list: numbered entries ("[17] Charles W. Bachman: ...") or catalogue numbers.
_REFERENCE = re.compile(r"^\s*\[\d+\]\s+\S|\bISBN\b", re.MULTILINE)
_MAX_REFERENCES = 1

# A key sentence carries one testable claim. Under ten words it is a label or a fragment
# ("Example 2-1."); over sixty it is several claims, and a question about it tests one at random.
_MIN_KEY_WORDS = 10
_MAX_KEY_WORDS = 60


def join_chunks(texts: Sequence[str]) -> str:
    """Chunk texts in reading order, section labels cut and each chunk's repeat of the one
    before it dropped, so the model never reads a sentence twice."""
    joined = ""
    for raw in texts:
        text = _LEADING_LABEL.sub("", raw, count=1)
        if joined:
            text = text[_overlap(joined, text) :]
            joined += "\n\n" + text.lstrip()
        else:
            joined = text
    return joined


def _overlap(before: str, after: str) -> int:
    longest = min(len(before), len(after), _MAX_OVERLAP_CHARS)
    for size in range(longest, _MIN_OVERLAP_CHARS - 1, -1):
        if before.endswith(after[:size]):
            return size
    return 0


def unfit_reason(passage: str) -> str | None:
    """Why *passage* is not material for a question, or None when it is."""
    lines = [line for line in passage.splitlines() if line.strip()]
    if not lines:
        return "empty"
    if sum(bool(_HEADING_LINE.match(line)) for line in lines) >= _CONTENTS_SHARE * len(lines):
        return "contents"
    if len(_ATTRIBUTION.findall(passage)) > _MAX_ATTRIBUTIONS:
        return "quotations"
    if _LICENCE.search(passage):
        return "licence"
    if len(_REFERENCE.findall(passage)) > _MAX_REFERENCES:
        return "references"
    return None


# A passage opens wherever its first chunk does, often mid-sentence; a fragment states half a claim.
# A question states no fact to test, and a numbered note ("2. In order that ... it is proposed to
# publish them four times a week") is about the work, not of it: chosen twice by length.
_OPENER = re.compile(r"^[\s\u2022*(\"\u201c\u2018-]*[A-Z]")
_CLOSER = re.compile(r"[.!][\"\u201d\u2019)\]]*\s*$")


def _whole(unit: str) -> bool:
    return bool(_OPENER.match(unit) and _CLOSER.search(unit))


def key_candidates(passage: str) -> list[str]:
    """Whole sentences of *passage* a question may test, longest learnable first (#191: length
    after furniture is cut was the whole salience signal)."""
    units = [
        u
        for u in split_units(passage)
        if _MIN_KEY_WORDS <= len(u.split()) <= _MAX_KEY_WORDS and _whole(u)
    ]
    return sorted((u for u in units if _learnable_words(u) > 0), key=lambda u: -_learnable_words(u))


# Candidates far from the section's summary are asides ("the idolatrous dotings of the old Egyptians
# upon broiled ibis", 0.18 below the best); one 0.12 below gave a good question (Connecticut and
# Pennsylvania). Provisional: one case brackets each side.
CENTRAL_MARGIN = 0.15
CANDIDATES = 8


def pick_keys(
    passage: str, count: int, skip: set[str], closeness: Sequence[float] | None = None
) -> list[str]:
    """One key sentence for a single-answer question, the best not already tested; [] when none.
    *closeness* scores the first CANDIDATES against the section summary, when there is one: the
    longest of those near the closest wins."""
    if count != 1:
        raise ValueError("a multi-answer question's keys are list items: use pick_list")
    candidates = [u for u in key_candidates(passage) if u not in skip][:CANDIDATES]
    if closeness is not None and len(closeness) == len(candidates) and candidates:
        floor = max(closeness) - CENTRAL_MARGIN
        candidates = [u for u, c in zip(candidates, closeness, strict=True) if c >= floor]
    return candidates[:1]


# A multi-answer question asks which items of one list are true: sentences picked from anywhere
# in a passage share no subject, and the stem written over them named none (two blind runs).
_ITEM = re.compile(r"^\s*(?:[\u2022*\u25aa\u2013-]|\d{1,2}[.)])\s+(.+)$")
_MIN_ITEM_WORDS = 6
_MIN_ITEMS = 3


def pick_list(passage: str, count: int) -> tuple[str, list[str]] | None:
    """The sentence that introduces a list in *passage*, and *count* of its items, longest
    first and shown in list order; None when the passage has no list of enough items."""
    lines = passage.splitlines()
    for start, line in enumerate(lines):
        if not _ITEM.match(line):
            continue
        items = _items(lines[start:])
        if len(items) < max(_MIN_ITEMS, count + 1):
            continue
        lead = " ".join(lines[:start]).strip()
        lead_in = re.split(r"(?<=[.!?])\s+", lead)[-1] if lead else ""
        if not lead_in.rstrip().endswith((":", "including", "include", "follows")):
            continue
        chosen = sorted(items, key=lambda i: -len(i))[:count]
        return lead_in.strip(), sorted(chosen, key=items.index)
    return None


def _items(lines: Sequence[str]) -> list[str]:
    """A list's items from its first line. A wrapped line opens in lower case ("ing very large
    datasets"); a line that opens in upper case is the paragraph after the list."""
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        match = _ITEM.match(line)
        if match:
            items.append(match.group(1).strip())
        elif stripped and stripped[0].islower() and items:
            items[-1] += " " + stripped
        elif stripped:
            break
    return [i for i in items if len(i.split()) >= _MIN_ITEM_WORDS]
