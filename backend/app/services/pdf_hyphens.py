"""Words a typesetter broke at a line end, rejoined at PDF import.

A PDF text layer keeps the break, so "bookques-" and "tions" reach the reader, search and
cards as two fragments. Only U+2010 and the soft hyphen are break marks; a plain "-" at a line end
is as often a real compound ("in-memory") as a break, so it is left alone.
"""

from __future__ import annotations

import re

# A letter must follow: a break before "18" is a word cut off by a stray page or note number.
_LINE_END_BREAK = re.compile(r"(?<=[^\W\d_])([‐­])[ \t]*\n[ \t]*(?=[^\W\d_])")
_PRINTED_COMPOUND = re.compile(r"(\w+)‐(\w+)")
_WORD_BEFORE = re.compile(r"\w+\Z")
_WORD_AFTER = re.compile(r"\w+")
# Longer than any word, so the backward search stays local to the break.
_WORD_WINDOW = 64


def printed_compounds(doc) -> frozenset[tuple[str, str]]:
    """Word pairs the document prints joined by U+2010 mid-line: real compounds, which keep
    their hyphen when a line break falls inside one."""
    pairs: set[tuple[str, str]] = set()
    for page in doc:
        for first, second in _PRINTED_COMPOUND.findall(page.get_text()):
            pairs.add((first.lower(), second.lower()))
    return frozenset(pairs)


def join_breaks(text: str, compounds: frozenset[tuple[str, str]] = frozenset()) -> str:
    def _join(match: re.Match[str]) -> str:
        before = _WORD_BEFORE.search(text, max(0, match.start() - _WORD_WINDOW), match.start())
        after = _WORD_AFTER.match(text, match.end())
        pair = (before.group().lower(), after.group().lower()) if before and after else None
        return match.group(1) if match.group(1) == "‐" and pair in compounds else ""

    return _LINE_END_BREAK.sub(_join, text)
