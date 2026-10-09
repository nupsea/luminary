"""A document's chapters: the units chapter practice writes cards for and offers at their end.

Heading levels cannot decide this: in the dev library *AI Engineering* is 448 sections all at
level 2 with its chapters only in the heading text ("Chapter 1. Introduction ..."), and
*thinkpython2* is 240 level-2 sections with no chapter marks at all. So chapters come from
the heading text first, and from the document's size when the headings carry no marks.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from sqlalchemy.ext.asyncio import AsyncSession

_ROMAN = "IVXLC"
_NUMERAL = rf"\d{{1,3}}|[{_ROMAN}]{{1,7}}"
# "Chapter 3. Storage", "CHAPTER IX", "Appendix B. Analysis of Algorithms".
_CHAPTER_MARK = re.compile(rf"^\W*(?:chapter|appendix)\s+(?:{_NUMERAL}|[A-Z])\b", re.I)
# "Part II. Distributed Data", "Book 3".
_PART_MARK = re.compile(rf"^\W*(?:part|book)\s+(?:{_NUMERAL})\b", re.I)
# "IX The Morlocks", "I. THE DISTRESS OF ARJUNA", "4 — Time Travelling"; not "1.1 Processors".
_NUMBERED = re.compile(rf"^\W*({_NUMERAL})(?:\.|\s+[—–-]|\s)\s*[A-Za-z]")
# Ends the chapter it appears in and is never practised.
_BACK_MATTER = re.compile(
    r"^\W*(?:index|colophon|about the authors?|bibliography|references|works cited)\W*$", re.I
)
# Headings that say where a window is, not what it is about; never a window's title.
_GENERIC_HEADING = re.compile(
    r"^\W*(?:summary|exercises?|problems|glossary|debugging|notes?|discussion|further reading"
    r"|references|introduction|overview)\W*$",
    re.I,
)
# Pages about the book, not of it (#252). "Introduction" is absent: in a technical book it is
# often chapter 1.
_FRONT_MATTER = re.compile(
    r"^\W*(?:title page|half title|copyright|dedication|preface|foreword"
    r"|acknowledge?ments?|contributors?(?: list)?|(?:table of )?contents|about this book"
    r"|praise for|conventions used|using code examples|how to contact us|who this book is for"
    r"|o.reilly online learning)\b",
    re.I,
)

# One "Chapter 5" heading in an article is a cross-reference, not a structure.
MIN_MARKED_CHAPTERS = 2
# Numbered headings must also count up: SysDesign's listicles ("9 best practices",
# "10 Good Coding Principles", "15 Open-Source Projects") are numbered but not chapters,
# while The Time Machine's "I"..."XVI" and the Gita's "I."..."XVIII." are.
MIN_NUMBERED_CHAPTERS = 3
MIN_ASCENDING_SHARE = 0.8
# Under this many characters the whole document is one chapter: ml_notes (9k) and the chexnet
# paper (32k) have numbered headings over 1-2k sections, too small to practise one at a time;
# the shortest book in the dev library is 110k.
WHOLE_DOCUMENT_CHARS = 40_000
# Unmarked documents are cut into windows of about this size at section boundaries, near a
# marked chapter's median in the dev library (Moby-Dick's 7k, AI Engineering's 113k).
WINDOW_CHARS = 30_000
# A page label is shown only when the pages could hold the text: thinkpython2's windows run
# about 1.5k characters a page, while Hegel's chunks carry their section's first page, so a
# 76k-character window would read "Pages 9-9".
MAX_CHARS_PER_PAGE = 10_000
# Front matter is looked for only this far in: thinkpython2's preface and contributor list end
# about 9% into the book, while acknowledgements that close a book sit past 90%.
FRONT_MATTER_SHARE = 0.15


@dataclass(frozen=True)
class SectionExtent:
    id: str
    heading: str
    first_chunk: int
    chars: int
    page_start: int = 0
    page_end: int = 0


@dataclass
class Chapter:
    """Identified by its first section, which is stable across re-detection."""

    id: str
    title: str
    order: int
    section_ids: list[str] = field(default_factory=list)
    chars: int = 0
    page_start: int = 0
    page_end: int = 0


def _numeral(token: str) -> int:
    if token.isdigit():
        return int(token)
    values = dict(zip(_ROMAN, (1, 5, 10, 50, 100), strict=True))
    total = 0
    for a, b in zip(token, token[1:] + " ", strict=True):
        v = values[a]
        total += -v if b in values and values[b] > v else v
    return total


def _counts_up(sections: Sequence[SectionExtent], found: list[int]) -> bool:
    numbers = [_numeral(_NUMBERED.match(sections[i].heading).group(1)) for i in found]  # type: ignore[union-attr]
    steps = list(pairwise(numbers))
    return sum(b > a for a, b in steps) >= MIN_ASCENDING_SHARE * len(steps)


def _matching(sections: Sequence[SectionExtent], mark: re.Pattern[str]) -> list[int]:
    return [i for i, s in enumerate(sections) if mark.match(s.heading)]


def _boundaries(sections: Sequence[SectionExtent]) -> list[int] | None:
    """Indexes of sections that open a chapter, or None when headings carry no chapter marks."""
    chapters = _matching(sections, _CHAPTER_MARK)
    parts = _matching(sections, _PART_MARK)
    if len(chapters) >= MIN_MARKED_CHAPTERS:
        # A part's opening pages are their own unit, not the tail of the chapter before.
        return sorted(set(chapters) | {i for i in parts if i > chapters[0]})
    if len(parts) >= MIN_MARKED_CHAPTERS:
        return parts
    numbered = _matching(sections, _NUMBERED)
    if len(numbered) >= MIN_NUMBERED_CHAPTERS and _counts_up(sections, numbered):
        return numbered
    return None


def _windows(sections: Sequence[SectionExtent]) -> list[int]:
    starts = [0]
    size = 0
    for i, s in enumerate(sections):
        if size >= WINDOW_CHARS:
            starts.append(i)
            size = 0
        size += s.chars
    return starts


def _window_title(members: Sequence[SectionExtent], page_start: int, page_end: int) -> str:
    """Where a window is (its pages), else its first heading that names a topic."""
    chars = sum(s.chars for s in members)
    if page_start and page_end and (page_end - page_start + 1) * MAX_CHARS_PER_PAGE >= chars:
        return f"Pages {page_start}-{page_end}"
    named = next((s for s in members if not _GENERIC_HEADING.match(s.heading)), members[0])
    return named.heading.strip()


def _without_back_matter(members: list[SectionExtent]) -> list[SectionExtent]:
    for k, s in enumerate(members):
        if k and _BACK_MATTER.match(s.heading):
            return members[:k]
    return members


def _front_matter_end(ordered: Sequence[SectionExtent]) -> int:
    """Index of the first section past the opening front matter, 0 when there is none.

    A preface's own subsections ("The strange history of this book") carry no front-matter
    name, so the cut runs through the last named front-matter section near the start. An
    untitled opening is cut only with named front matter after it: alone, it is as often a
    paper's abstract as a title page.
    """
    if ordered[0].heading.strip() and not _FRONT_MATTER.match(ordered[0].heading):
        return 0
    limit = FRONT_MATTER_SHARE * sum(s.chars for s in ordered)
    end, seen = 0, 0
    for i, s in enumerate(ordered):
        if seen >= limit:
            break
        if _FRONT_MATTER.match(s.heading):
            end = i + 1
        seen += s.chars
    return end if end < len(ordered) else 0


def _starts(ordered: Sequence[SectionExtent]) -> tuple[list[int], bool]:
    """Indexes opening each chapter, and whether they came from heading marks.

    A marked book already starts at its first mark; an unmarked one starts past its front matter.
    """
    big = sum(s.chars for s in ordered) >= WHOLE_DOCUMENT_CHARS
    marked = _boundaries(ordered) if big else None
    if marked is not None:
        return marked, True
    front = _front_matter_end(ordered)
    if not big:
        return [front], False
    return [front + i for i in _windows(ordered[front:])], False


def _chapter(members: list[SectionExtent], order: int, title: str | None) -> Chapter:
    page_start = min((s.page_start for s in members if s.page_start), default=0)
    page_end = max((s.page_end for s in members), default=0)
    return Chapter(
        id=members[0].id,
        title=title or _window_title(members, page_start, page_end),
        order=order,
        section_ids=[s.id for s in members],
        chars=sum(s.chars for s in members),
        page_start=page_start,
        page_end=page_end,
    )


def detect_chapters(sections: Sequence[SectionExtent], document_title: str) -> list[Chapter]:
    """Chapters in reading order, never opening on front matter."""
    ordered = sorted((s for s in sections if s.chars > 0), key=lambda s: s.first_chunk)
    if not ordered:
        return []
    starts, marked = _starts(ordered)
    ends = [*starts[1:], len(ordered)]
    chapters = []
    for n, (start, end) in enumerate(zip(starts, ends, strict=True)):
        members = _without_back_matter(list(ordered[start:end]))
        if marked:
            title: str | None = members[0].heading.strip()
        else:
            title = document_title if len(starts) == 1 else None
        chapters.append(_chapter(members, n, title))
    return chapters


async def chapters_for_document(
    document_id: str, document_title: str, session: AsyncSession
) -> list[Chapter]:
    from app.repos.document_repo import DocumentRepo  # noqa: PLC0415

    repo = DocumentRepo(session)
    extents = await repo.section_extents(document_id)
    sections = [
        SectionExtent(s.id, s.heading, *extents[s.id])
        for s in await repo.sections_for_document(document_id)
        if s.id in extents
    ]
    return detect_chapters(sections, document_title)
