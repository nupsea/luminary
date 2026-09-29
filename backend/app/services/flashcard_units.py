"""Sentence units for unit-first flashcards: which sentences get a card, and what a card quotes.

Code picks the sentences and the model only phrases a question about each; the model was measured
unable to choose what is worth asking on its own (#191). Pure module: no I/O, no LLM calls.
"""

from __future__ import annotations

import re

_SENT_END = re.compile(r"(?<=[.!?\"'”’)\]])\s+(?=[\"'“‘(\[]?[A-Z0-9])")
_CODE_LINE = re.compile(
    r"^\s*(def|class|import|from|return|if|elif|else|for|while|try|except|with)\b.*:\s*$"
    r"|^\s*(import|return)\b|\s[-+*/]?=\s|==|=>|->|;\s*$|[{}]\s*$|\)\s*:?\s*$|^\s*@\w"
)
# Shorter pieces join their neighbour; the same floor as the quote check (_MIN_EXCERPT_CHARS).
_MIN_UNIT_CHARS = 12
_CODE_LINES_PER_UNIT = 6
# A line is prose when letters make up most of it; code and tables fall below.
_PROSE_ALPHA_SHARE = 0.6

# Breadcrumbs, headings and rules are cut out before a sentence's length counts, so a heading
# never wins on length but a story sentence sharing a unit with one still does. A leading
# bracket is a section label; an unclosed one is a breadcrumb split across units
# ("[AI-Ready Data vs.").
_FURNITURE_SPAN = re.compile(
    r"\[[^\]]*>[^\]]*\]|^\s*\[[^\]]*\]|^\s*\[[^\]]*$|[-=]{5,}"
    r"|#{1,6}\s+\*\*[^*]*\*\*|#{1,6}\s[^#\n]*?\?|#{1,6}\s[^#\n.!?]*$"
)
# A bibliography entry that survived the chunk-level filter in _fetch_chunks. Matches none of
# the 497 hand-labelled #191 units, so no sentence worth learning is lost to it.
_CITATION = re.compile(
    r"\barXiv\b|\bpreprint\b|©|All rights reserved|\bIn\s+(?:Proceedings|Advances\s+in)\b"
    r"|\bpages?\s+\d+\s*[–-]\s*\d+|\bpp\.\s*\d+|\d+\s*\(\d+\)\s*:\s*\d+"
)

_WORD = re.compile(r"[a-z0-9]+")
# The list the coverage floor below was measured with; a different list moves the floor.
_STOP = frozenset(
    (
        "the",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "as",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "how",
        "does",
        "do",
        "did",
        "has",
        "have",
        "had",
        "not",
        "no",
        "into",
        "than",
        "then",
        "there",
        "their",
        "they",
        "them",
        "he",
        "she",
        "his",
        "her",
        "him",
        "a",
        "an",
        "can",
        "could",
        "would",
        "should",
        "will",
        "may",
        "might",
        "i",
        "you",
        "we",
        "our",
        "your",
        "my",
        "me",
        "us",
    )
)
# Share of an answer's content words its best sentence must carry. Brackets, on the hand-graded
# #191 unit cards: 0.29 "The passage does not explicitly state what these bounds are" (bad),
# 0.33 "The database rejects them rather than merely filtering out reads" (good).
MIN_ANSWER_COVERAGE = 0.3


def _is_prose(line: str) -> bool:
    letters = " ".join(re.findall(r"[A-Za-z]+", line))
    return not _CODE_LINE.search(line) and len(letters) >= _PROSE_ALPHA_SHARE * len(line.strip())


def _merge_short(pieces: list[str]) -> list[str]:
    """Pieces under the floor join the one before, or the one after when they come first."""
    merged: list[str] = []
    for piece in pieces:
        short_first = len(merged) == 1 and len(merged[0]) < _MIN_UNIT_CHARS
        if merged and (len(piece) < _MIN_UNIT_CHARS or short_first):
            merged[-1] += " " + piece
        else:
            merged.append(piece)
    return merged


def _paragraphs(text: str) -> list[tuple[bool, list[str]]]:
    """(is_prose, lines) per paragraph; a prose/code switch also starts a new one."""
    runs: list[tuple[bool, list[str]]] = []
    for line in text.splitlines():
        stripped = line.strip()
        # A blank line ends a paragraph, and so does the "[...]" that joins separate excerpts.
        if stripped in ("", "[...]"):
            runs.append((True, []))
            continue
        prose = _is_prose(line)
        kept = stripped if prose else line
        if runs and runs[-1][0] == prose and runs[-1][1]:
            runs[-1][1].append(kept)
        else:
            runs.append((prose, [kept]))
    return [run for run in runs if run[1]]


def split_units(text: str) -> list[str]:
    """Verbatim slices of *text*: prose split at sentence ends, code grouped a few lines at a time.

    Hard-wrapped prose lines are joined first, so a sentence broken across lines stays one unit.
    Short pieces merge within their paragraph only, so a section label never joins the previous
    chunk's last sentence.
    """
    units: list[str] = []
    for prose, lines in _paragraphs(text):
        if prose:
            sentences = [s.strip() for s in _SENT_END.split(" ".join(lines)) if s.strip()]
            units.extend(_merge_short(sentences))
        else:
            step = _CODE_LINES_PER_UNIT
            units.extend("\n".join(lines[i : i + step]) for i in range(0, len(lines), step))
    return units


def _learnable_words(unit: str) -> int:
    if _CITATION.search(unit):
        return 0
    body = _FURNITURE_SPAN.sub(" ", unit)
    alpha = sum(c.isalpha() for c in body) / max(1, len(body))
    return len(_WORD.findall(body.lower())) if alpha > _PROSE_ALPHA_SHARE else 0


def choose_units(units: list[str], count: int, skip: set[str] | None = None) -> list[str]:
    """The *count* longest prose units, in passage order.

    Length after furniture is cut was the whole salience signal on 497 hand-labelled units:
    0.70 of top-3 picks worth learning, against 0.52 for passage order and 0.68 for a trained
    ranker (#191).
    """
    skip = skip or set()
    ranked = sorted(
        (i for i, u in enumerate(units) if u not in skip and _learnable_words(u) > 0),
        key=lambda i: -_learnable_words(units[i]),
    )
    return [units[i] for i in sorted(ranked[:count])]


def _content(text: str) -> set[str]:
    return {w[:5] for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def best_unit(answer: str, units: list[str]) -> tuple[str, float]:
    """The unit that carries most of *answer*, and the share of the answer it carries.

    The model's own sentence number is not trusted: it named the wrong sentence for 31 of 149
    graded cards, which would have stored a quote that does not support the card.
    """
    words = _content(answer)
    if not words or not units:
        return "", 0.0
    unit = max(units, key=lambda u: len(words & _content(u)))
    return unit, len(words & _content(unit)) / len(words)
