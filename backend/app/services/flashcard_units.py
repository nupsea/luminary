"""Sentence units for unit-first flashcards: which sentences get a card, and what a card quotes.

Code picks the sentences and the model only phrases a question about each; the model was measured
unable to choose what is worth asking on its own (#191). Pure module: no I/O, no LLM calls.
"""

from __future__ import annotations

import re
import unicodedata

# A footnote number after a word's full stop ("the model.2 For") still ends the sentence; a
# digit before the dot ("GPT-3.5 Turbo") does not.
_SENT_END = re.compile(
    r"(?:(?<=[.!?\"'”’)\]])|(?<=[a-z”’)][.!?]\d)|(?<=[a-z”’)][.!?]\d\d))"
    r"\s+(?=[\"'“‘(\[]?[A-Z0-9])"
)
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

# A play's speaker line, alone on its line. Colons and inner dots are excluded ("NOTES:", "N.E."
# and "ELSE:" were the library's false hits); heading words and numerals rule out "CHAPTER II.".
_SPEAKER_LINE = re.compile(r"^[A-Z][A-Z' -]{1,30}\.$")
_HEADING_WORD = re.compile(
    r"\b(?:ACT|SCENE|CHAPTER|BOOK|PART|SECTION|CANTO|VOLUME|NOTES?|CONTENTS|PREFACE|FOOTNOTES"
    r"|INTRODUCTION|EPILOGUE|PROLOGUE|APPENDIX|FINIS|END|[IVXLC]+)\b"
)
# A chunk's section label ("[CHAPTER II — Sanjaya.]") read inside a sentence was taken for its
# speaker, so the model never sees it there; the stored quote keeps it.
_LEADING_LABEL = re.compile(r"^\s*\[[^\]]*\]\s*")

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
# Share of an answer's content words its best sentence must carry; below it the answer was written
# from elsewhere. Bracketed by test_the_coverage_floor_sits_between_its_two_graded_cases.
MIN_ANSWER_COVERAGE = 0.5


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


def _speaker_lines(text: str) -> set[str]:
    """A play's speaker lines ("LAERTES."), when *text* has at least two different speakers.

    A line that finishes an unfinished one is the end of a sentence, not a speaker: the manual's
    "Input byte from imm8 I/O port address into\\nAL.".
    """
    lines = [line.strip() for line in text.splitlines()]
    found = {
        line
        for prev, line in zip(["", *lines], lines, strict=False)
        if _SPEAKER_LINE.match(line) and not _HEADING_WORD.search(line) and not prev[-1:].islower()
    }
    return found if len(found) >= 2 else set()


def _paragraphs(text: str) -> list[tuple[bool, list[str], str | None]]:
    """(is_prose, lines, speaker) per paragraph; a prose/code switch also starts a new one."""
    speaker_lines = _speaker_lines(text)
    speaker: str | None = None
    runs: list[tuple[bool, list[str], str | None]] = []
    for line in text.splitlines():
        stripped = line.strip()
        # A blank line ends a paragraph, and so does the "[...]" that joins separate excerpts.
        # Chunks are joined by a blank line and may open mid-speech, so it ends the speech too.
        if stripped in ("", "[...]"):
            speaker = None
            runs.append((True, [], speaker))
            continue
        if stripped in speaker_lines:
            speaker = stripped.rstrip(".").title()
            runs.append((True, [], speaker))
            continue
        prose = _is_prose(line)
        kept = stripped if prose else line
        if runs and runs[-1][0] == prose and runs[-1][1]:
            runs[-1][1].append(kept)
        else:
            runs.append((prose, [kept], speaker))
    return [run for run in runs if run[1]]


def split_speeches(text: str) -> list[tuple[str, str | None]]:
    """(unit, speaker) for each unit of *text*; the speaker is None outside a play's speeches."""
    pairs: list[tuple[str, str | None]] = []
    for prose, lines, speaker in _paragraphs(text):
        if prose:
            sentences = [s.strip() for s in _SENT_END.split(" ".join(lines)) if s.strip()]
            pairs.extend((u, speaker) for u in _merge_short(sentences))
        else:
            step = _CODE_LINES_PER_UNIT
            pairs.extend(
                ("\n".join(lines[i : i + step]), speaker) for i in range(0, len(lines), step)
            )
    return pairs


def split_units(text: str) -> list[str]:
    """Verbatim slices of *text*: prose split at sentence ends, code grouped a few lines at a time.

    Hard-wrapped prose lines are joined first, so a sentence broken across lines stays one unit.
    Short pieces merge within their paragraph only, so a section label never joins the previous
    chunk's last sentence, and a speaker line never joins the previous speech.
    """
    return [unit for unit, _speaker in split_speeches(text)]


def listed_sentence(unit: str, speaker: str | None) -> str:
    """How a chosen unit is shown to the model: section label cut, speaker named."""
    body = _LEADING_LABEL.sub("", unit, count=1) or unit
    return f"{speaker} says: {body}" if speaker else body


_NAME = re.compile(r"\b[A-Z][\w'’-]+")
_POSSESSIVE = re.compile(r"['’]s?$")
# Capitalised for grammar, not because they name anything.
_NOT_NAMES = frozenset(("I", "According"))


def names_not_in(question: str, text: str) -> list[str]:
    """Capitalised words of *question*, after its first, that *text* never contains.

    A card naming someone the passage never mentions guessed who acted ("Arachne" for Penelope's
    maid). A wrong name the passage does mention passes.
    """
    question = unicodedata.normalize("NFKC", question)
    scope = unicodedata.normalize("NFKC", text).lower()
    return [
        word
        for m in _NAME.finditer(question)
        if m.start() > 0
        and (word := _POSSESSIVE.sub("", m.group())) not in _NOT_NAMES
        and word.lower() not in scope
    ]


# A sentence that opens with its example illustrates the sentence before it; asked on its own,
# the card tests the illustration ("GPT-4 breaks the phrase into nine tokens") (#230).
_EXAMPLE_OPENER = re.compile(
    r"^\W*(?:(?:for example|for instance|as an example)\b|e\.g\.)", re.IGNORECASE
)


def _learnable_words(unit: str) -> int:
    if _CITATION.search(unit) or _EXAMPLE_OPENER.match(_LEADING_LABEL.sub("", unit, count=1)):
        return 0
    body = _FURNITURE_SPAN.sub(" ", unit)
    alpha = sum(c.isalpha() for c in body) / max(1, len(body))
    return len(_WORD.findall(body.lower())) if alpha > _PROSE_ALPHA_SHARE else 0


def choose_units(units: list[str], count: int, skip: set[str] | None = None) -> list[str]:
    """The *count* longest prose units, in passage order.

    Length after furniture is cut was the whole salience signal measured in #191; a trained
    ranker did no better.
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

    The model's own sentence number is not trusted: it often names the wrong sentence, which
    would store a quote that does not support the card.
    """
    words = _content(answer)
    if not words or not units:
        return "", 0.0
    unit = max(units, key=lambda u: len(words & _content(u)))
    return unit, len(words & _content(unit)) / len(words)
