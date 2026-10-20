"""
book_parser.py
==============
Chapter-aware parsing for book-format documents (TXT, PDF, DOCX, MD).

Supports hierarchical section detection (e.g. Parts -> Chapters).
Discovers patterns across a corpus of diverse books:
  P1  CHAPTER N. [optional subtitle on next line]
  P2  Roman numeral alone  +  subtitle on next line
  P3  I. STORY TITLE on one line (Sherlock style)
  P4  Centred roman numeral (leading whitespace ≥4)
  P5  Chapter N: / Chapter N.  arabic/inline
  P6  PART N. / BOOK N. / ordinal BOOK (superstructure)
  P7  CHAPTER N (no dot) + confirmed by HERE ENDETH
  P8  The [Nth] Book of / The Gospel According
  P9  ADVENTURE N. TITLE
  P10 FEDERALIST No. N (a numbered series)
  PL  Letter N (epistolary novels)
  plus Prologue / Epilogue / Afterword beside any of those, and divider lines only without them

Metadata stripping:
  - Gutenberg preamble/footer
  - Table-of-Contents blocks (extremely conservative)
"""

from __future__ import annotations

import logging
import re
from itertools import pairwise
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from markdown_it import MarkdownIt

from app.services import pdf_furniture, pdf_hyphens
from app.services.source_text import read_source_text
from app.services.universal_parser import _drop_bodyless, _is_nav_line
from app.types import ParsedDocument, Section

logger = logging.getLogger(__name__)

# Gutenberg delimiters
_RE_PG_START = re.compile(
    r"\*{3}\s*START OF (?:THE |THIS )?PROJECT GUTENBERG EBOOK[^\n]*\*{3}",
    re.IGNORECASE,
)
_RE_PG_END = re.compile(
    r"\*{3}\s*END OF (?:THE |THIS )?PROJECT GUTENBERG EBOOK[^\n]*\*{3}",
    re.IGNORECASE,
)

# Roman numeral helper (I–MMMCMXCIX)
_ROMAN = (
    r"(?=[IVXLCDM])"
    r"(?:M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))"
)

# Ordinal words for "FIRST BOOK", "SECOND BOOK" etc.
_ORDINALS = (
    r"(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|"
    r"ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|SIXTEENTH|SEVENTEENTH|"
    r"EIGHTEENTH|NINETEENTH|TWENTIETH)"
)

# Number words for "Chapter One"
_WORDS_N = (
    r"(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|THIRTEEN|"
    r"FOURTEEN|FIFTEEN|SIXTEEN|SEVENTEEN|EIGHTEEN|NINETEEN|TWENTY)"
)

# Pattern families (compiled) with default hierarchy levels.
# level=1 is the highest (Story/Part), level=2 is sub-chapter.
_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    # P1: CHAPTER N. [dot optional] – most explicit
    (
        "P1",
        re.compile(
            rf"^[ \t]*(?:CHAPTER|CHAP\.?)\s+({_ROMAN}|\d+|{_WORDS_N})[\.:]?\s*$",
            re.MULTILINE | re.IGNORECASE,
        ),
        1,
    ),
    # P7: CHAPTER N (no dot, Gita style) – requires HERE ENDETH confirmation
    (
        "P7",
        re.compile(
            rf"^[ \t]*CHAPTER\s+({_ROMAN}|\d+|{_WORDS_N})\s*$",
            re.MULTILINE,
        ),
        1,
    ),
    # P3: I. CAPS TITLE on one line (Sherlock Holmes Stories). Without the dot the title must be
    # capitals: "I FLATTER myself it has been..." opens a Federalist paper (#333).
    (
        "P3",
        re.compile(
            rf"^[ \t]*({_ROMAN})(?:\.[ \t]+([A-Z][A-Za-z0-9 ’',\-:&]{{2,79}})"
            rf"|[ \t]+([A-Z][A-Z0-9 ’',\-:&]{{2,79}}))[ \t]*$",
            re.MULTILINE,
        ),
        1,
    ),
    # P10: a numbered paper in a series, "FEDERALIST No. 10" (#333)
    (
        "P10",
        re.compile(r"^[ \t]*(?:THE[ \t]+)?[A-Z][A-Za-z]+[ \t]+No\.[ \t]*\d+[ \t]*$", re.MULTILINE),
        1,
    ),
    # PL: an epistolary novel's "Letter 1" (Frankenstein, #332)
    (
        "PL",
        re.compile(
            rf"^[ \t]*LETTER[ \t]+({_ROMAN}|\d+|{_WORDS_N})[\.:]?[ \t]*$",
            re.MULTILINE | re.IGNORECASE,
        ),
        1,
    ),
    # P9: ADVENTURE I. CAPS TITLE
    (
        "P9",
        re.compile(
            rf"^[ \t]*ADVENTURE\s+({_ROMAN}|\d+)\.?[ \t]+([A-Z][A-Za-z0-9 ’',\-:&]{{2,79}})[ \t]*$",
            re.MULTILINE | re.IGNORECASE,
        ),
        1,
    ),
    # P6a: PART N. / BOOK N. (superstructure); the title stays on the heading's own line
    (
        "P6a",
        re.compile(
            rf"^(?:PART|BOOK|SECTION|VOLUME)[ \t]+({_ROMAN}|\d+|{_WORDS_N})[\.]?(?:[ \t]+[^\n]+)?$",
            re.MULTILINE | re.IGNORECASE,
        ),
        1,
    ),
    # P6b: ordinal BOOK / ordinal MEDITATION (Marcus Aurelius)
    (
        "P6b",
        re.compile(
            rf"^[ \t]*(?:THE\s+)?{_ORDINALS}\s+(?:BOOK|SECTION|MEDITATION)(?:\s+OF\s+[^\n]+)?$",
            re.MULTILINE | re.IGNORECASE,
        ),
        1,
    ),
    # P8: Bible book headings – match full heading line
    (
        "P8",
        re.compile(
            r"^(?:The\s+(?:First|Second|Third|Fourth|Fifth)\s+Book\s+of\b[^\n]*"
            r"|The\s+Book\s+of\s+\w+[^\n]*"
            r"|The\s+Gospel\s+According\s+to\b[^\n]*"
            r"|The\s+(?:First|Second|Third)\s+Epistle\b[^\n]*"
            r"|The\s+Acts\s+of[^\n]*|The\s+Revelation\b[^\n]*)",
            re.MULTILINE,
        ),
        1,
    ),
    # P2: standalone roman numeral line + subtitle on next non-empty line
    # (Wells / Sherlock Subchapters)
    (
        "P2",
        re.compile(
            rf"^[ \t]*({_ROMAN})\.\s*$",
            re.MULTILINE,
        ),
        2,  # Usually a sub-section when other markers are present
    ),
    # P4: centred roman numeral (≥4 leading spaces, Gatsby-style)
    (
        "P4",
        re.compile(
            rf"^[ \t]{{4,}}({_ROMAN})[ \t]*$",
            re.MULTILINE | re.IGNORECASE,
        ),
        2,
    ),
    # P5: Chapter N: / Chapter N. with inline title (tech books)
    (
        "P5",
        re.compile(
            r"^Chapter\s+(\d+|" + _WORDS_N + r")[\.:\s]\s*(\S.{0,120})$",
            re.MULTILINE | re.IGNORECASE,
        ),
        1,
    ),
]

# A divider is a break, not a label, so it splits only text that has no labelled heading: a
# transcript's sessions, never The Great Gatsby's scene breaks inside its chapters.
_RE_DIVIDER = re.compile(r"^[-=*_]{8,}\s*$", re.MULTILINE)

# A named division sits beside the chapters and takes their level. It counts only alongside
# them: one "Epilogue" line alone is as likely prose as structure.
_RE_NAMED_DIVISION = re.compile(
    r"^[ \t]*(?:PROLOGUE|EPILOGUE|AFTERWORD)\.?[ \t]*$", re.MULTILINE | re.IGNORECASE
)

# Prose is a paragraph of this many words that ends a sentence. It decides whether text before
# the first heading is kept and whether a heading is a contents entry. Frankenstein's title
# lines run to 6 words and the Bible's contents is 70 lines with no full stop; Frankenstein's
# first Letter opens on a 50-word paragraph.
_PROSE_WORDS = 25
_RE_SENTENCE_END = re.compile(r"[a-z][.!?]")

# A contents list is at least this many entries in a row with nothing under them.
_MIN_CONTENTS_RUN = 3

# TOC detection: line that looks like a TOC entry
_RE_TOC_LINE = re.compile(
    rf"^\s*(?:{_ROMAN}|Chapter\s+\d+|CHAPTER\s+{_ROMAN})"
    r"(?:[.:]\s+\S|\s+[A-Z]\S)",
    re.MULTILINE,
)

# HERE ENDETH confirmation (Gita)
_RE_ENDETH = re.compile(r"HERE ENDETH CHAPTER", re.IGNORECASE)

# Metadata signals
_METADATA_SIGNALS = frozenset(
    [
        "contents",
        "table of contents",
        "index",
        "preface",
        "foreword",
        "acknowledgements",
        "acknowledgments",
        "copyright",
        "dedication",
        "about the author",
        "bibliography",
        "references",
        "appendix",
        "produced by",
        "project gutenberg",
        "end of the project gutenberg",
    ]
)

_MIN_CHAPTERS = 2


def _is_metadata(heading: str) -> bool:
    return heading.lower().strip() in _METADATA_SIGNALS


def _is_body_block(block: tuple, page_height: float, running: frozenset[str]) -> bool:
    # (x0, y0, x1, y1, text, block_no, block_type); type 0 is text.
    if len(block) <= 6 or block[6] != 0 or not str(block[4]).strip():
        return False
    return not pdf_furniture.is_running(str(block[4]), block[1], block[3], page_height, running)


def _page_text_with_paragraphs(
    page,
    running: frozenset[str] = frozenset(),
    compounds: frozenset[tuple[str, str]] = frozenset(),
) -> str:
    """Page text with a blank line between paragraphs, without its running heads, and with
    words broken at a line end rejoined.

    A PDF text layer is hard-wrapped, so flat extraction yields no paragraph
    boundary and the reader renders a whole chapter as one block. PyMuPDF's
    blocks carry the layout's own grouping; joining them on a blank line
    recovers it. Falls back to flat text when a page exposes no blocks.
    """
    try:
        blocks = page.get_text("blocks")
    except Exception:
        return page.get_text()
    if not blocks:
        return page.get_text()
    height = float(page.rect.height) or 1.0
    ordered = sorted(
        (b for b in blocks if _is_body_block(b, height, running)),
        key=lambda b: (round(b[1], 1), round(b[0], 1)),
    )
    if not ordered:
        return page.get_text()
    texts = [pdf_hyphens.join_breaks(str(b[4]).strip(), compounds) for b in ordered]
    return "\n\n".join(pdf_hyphens.join_block_breaks(texts, compounds))


# A chapter's first body line is a subtitle only when it reads as a title. Word
# count is the discriminator: hard-wrapped prose runs far longer than a title.
# Terminal punctuation is not a signal -- a subtitle may end in "?". ALL-CAPS
# argument lines are exempt from the count.
_SUBTITLE_MAX_WORDS = 7
_SUBTITLE_MAX_CHARS = 100


def _is_subtitle(line: str) -> bool:
    if line.isupper():
        return True
    if len(line) > _SUBTITLE_MAX_CHARS:
        return False
    return len(line.split()) <= _SUBTITLE_MAX_WORDS


def _clean_heading(heading: str) -> str:
    h = re.sub(r"\s+", " ", heading).strip()
    h = re.sub(r"\.\s*$", "", h).strip()
    return h


_RE_BASE_HEADING = re.compile(
    r"((?:chapter|chap\.?|part|book|section|volume"
    r"|adventure)\s+(?:\w+))",
    re.IGNORECASE,
)


def _base_heading(heading: str) -> str:
    """Extract canonical heading key for dedup.

    E.g. 'chapter 6' from both 'CHAPTER 6' and 'Chapter 6: Partitioning'.
    """
    h = heading.split("\u2014", maxsplit=1)[0].strip()
    m = _RE_BASE_HEADING.match(h)
    if m:
        return m.group(1).lower()
    return h.lower()


def _match(m: re.Match[str], pid: str, level: int | None) -> dict:
    return {
        "start": m.start(),
        "end": m.end(),
        "pid": pid,
        "level": level,
        "raw_heading": m.group(0).strip(),
    }


_INLINE_TITLE_PATTERNS = frozenset({"P3", "P6a", "P6b", "P9"})
_BARE_NUMERAL_PATTERNS = frozenset({"P2", "P4"})


def _is_heading_line(text: str, m: re.Match[str], pid: str) -> bool:
    """Whether a pattern match is a heading rather than a line of prose.

    A heading opens on a capital: "part one to another." and "the first book of his
    _Meditations_, and shows" are sentences. A heading with a mixed-case title on its own line
    is its own paragraph, followed by a blank line: "I. A SCANDAL IN BOHEMIA" is, while a
    numbered paragraph runs on ("I. Of my grandfather Verus I have learned to be gentle and
    meek, and to", Meditations; "I. The qualifications proposed for senators", #333). It must
    also read as a title, since unwrapped text puts a whole paragraph on one line.
    """
    line = m.group(0).strip()
    if not line[:1].isupper():
        return False
    if pid in _BARE_NUMERAL_PATTERNS:
        # A hard wrap can leave a sentence's last word alone: "opponents of Louis\nXIV." (#333).
        before = text[max(0, m.start() - 80) : m.start()]
        at_start = m.start() == len(before) and not before.strip()
        return at_start or re.search(r"\n[ \t\f]*\n\Z", before) is not None
    if pid not in _INLINE_TITLE_PATTERNS or line.upper() == line:
        return True
    alone = re.match(r"[ \t]*(?:\n[ \t]*\n|\n?\Z)", text[m.end() :]) is not None
    return alone and _is_subtitle(line)


def _has_prose(text: str) -> bool:
    return any(
        len(p.split()) >= _PROSE_WORDS and _RE_SENTENCE_END.search(p)
        for p in re.split(r"\n\s*\n", text)
    )


def _without_contents_runs(text: str, matches: list[dict]) -> list[dict]:
    """Drop a contents list's entries, the last one included (#332).

    An entry matches a chapter pattern, recurs later as the chapter itself, and has no prose
    under it. The last entry's "body" is whatever follows the list, so Frankenstein's opening
    Letters became a twin of Chapter 24. It is the entry right after the run, recurring later
    and not already in the list: a real "CHAPTER I" after a list that names it is the chapter.
    """
    keys = [
        re.sub(r"^the\s+", "", _base_heading(_clean_heading(m["raw_heading"]))) for m in matches
    ]
    bodies = [text[a["end"] : b["start"]] for a, b in pairwise(matches)] + [
        text[matches[-1]["end"] :]
    ]
    entry = [keys[i] in keys[i + 1 :] and not _has_prose(bodies[i]) for i in range(len(matches))]
    entry.append(False)
    kept: list[dict] = []
    i = 0
    while i < len(matches):
        j = i
        while entry[j]:
            j += 1
        if j - i >= _MIN_CONTENTS_RUN:
            last = j < len(matches) and keys[j] in keys[j + 1 :] and keys[j] not in keys[i:j]
            i = j + 1 if last else j
            continue
        kept += matches[i : j + 1]
        i = j + 1
    return kept


def _merge_duplicate_sections(sections: list[Section]) -> list[Section]:
    """Merge consecutive sections that share a base heading: a PDF's running head
    ("Chapter 1: Title" on every page) opens one per page.

    Only neighbours merge. A twin further on is a different section: Gulliver's four Parts each
    restart at "CHAPTER I", and Sherlock's stories each restart their parts at "I". Merging
    those by name moved whole chapters out of reading order (#332).
    """
    if not sections:
        return sections
    merged: list[Section] = [sections[0]]
    for s in sections[1:]:
        prev = merged[-1]
        if _base_heading(s.heading) == _base_heading(prev.heading):
            prev.text = prev.text + "\n\n" + s.text
            prev.page_end = max(prev.page_end, s.page_end)
        else:
            merged.append(s)
    return merged


class BookParser:
    """Chapter-aware parser for book-format documents."""

    def parse(self, file_path: Path, fmt: str) -> ParsedDocument | None:
        fmt = fmt.lower()
        try:
            if fmt == "txt":
                return self._parse_txt(file_path)
            if fmt == "pdf":
                return self._parse_pdf(file_path)
            if fmt in ("docx", "doc"):
                return self._parse_docx(file_path)
            if fmt in ("md", "markdown"):
                return self._parse_md(file_path)
            if fmt in ("html", "htm"):
                return self._parse_html(file_path)
        except Exception:
            logger.exception("BookParser failed for %s", file_path)
        return None

    def _parse_txt(self, file_path: Path) -> ParsedDocument | None:
        raw_text = read_source_text(file_path)
        clean_text, raw_no_meta = self._strip_gutenberg(raw_text)
        sections = self._segment_chapters(clean_text)
        if sections is None:
            return None
        return ParsedDocument(
            title=file_path.stem.replace("_", " ").title(),
            format="txt",
            pages=0,
            word_count=len(raw_no_meta.split()),
            sections=sections,
            raw_text=raw_no_meta,
            structure_type="book",
        )

    def _parse_pdf(self, file_path: Path) -> ParsedDocument | None:
        doc = fitz.open(str(file_path))
        if len(doc) == 0:
            return None
        running = pdf_furniture.running_signatures(doc)
        compounds = pdf_hyphens.printed_compounds(doc)
        page_texts = pdf_hyphens.join_block_breaks(
            [_page_text_with_paragraphs(page, running, compounds) for page in doc], compounds
        )
        # Pages are assigned by searching each heading in the page text as printed, so a
        # section's page, and every citation from it, does not move with the stripping.
        printed_pages = [_page_text_with_paragraphs(page, compounds=compounds) for page in doc]
        total_pages = len(doc)
        # Join pages with \f (form feed) so we can map chunks back to physical
        # page numbers even after Gutenberg/metadata stripping alters string offsets.
        # The \n after it starts a line: chapter patterns anchor on ^, and a chapter
        # opening its page, no longer under a running head, must still match. The
        # chunker drops the \f, so without it a page's last word fused with the next.
        all_text = "\f\n".join(page_texts)
        clean_text, _ = self._strip_gutenberg(all_text)
        sections = self._segment_chapters(clean_text)
        if not sections:
            return None

        # Assign page_start by searching the section heading in per-page texts.
        # Use the base heading (before any "—" subtitle) since it matches the
        # raw chapter heading text found in the PDF page content.
        # Enforce monotonically increasing pages to skip TOC matches on early pages.
        min_page = 1
        for section in sections:
            base = section.heading.split("—")[0].strip()
            for page_num, pt in enumerate(printed_pages, start=1):
                if page_num >= min_page and base in pt:
                    section.page_start = page_num
                    min_page = page_num
                    break

        # Set page_end = start of the next section (or last page for the final section)
        for i in range(len(sections) - 1):
            if sections[i].page_start > 0 and sections[i + 1].page_start > 0:
                sections[i].page_end = sections[i + 1].page_start
            elif sections[i].page_start > 0:
                sections[i].page_end = total_pages
        if sections and sections[-1].page_start > 0:
            sections[-1].page_end = total_pages

        return ParsedDocument(
            title=file_path.stem.replace("_", " ").title(),
            format="pdf",
            pages=total_pages,
            word_count=len(all_text.split()),
            sections=sections,
            raw_text=all_text,
            structure_type="book",
        )

    def _parse_docx(self, file_path: Path) -> ParsedDocument | None:
        doc = DocxDocument(str(file_path))
        raw_parts = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n".join(raw_parts)
        sections = self._segment_chapters(full_text)
        if not sections:
            return None
        return ParsedDocument(
            title=file_path.stem.replace("_", " ").title(),
            format="docx",
            pages=0,
            word_count=len(full_text.split()),
            sections=sections,
            raw_text=full_text,
            structure_type="book",
        )

    def _parse_md(self, file_path: Path) -> ParsedDocument | None:
        raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        md = MarkdownIt()
        tokens = md.parse(raw_text)

        sections: list[Section] = []
        current_heading = "Introduction"
        current_level = 1
        current_texts: list[str] = []
        in_heading = False
        pending_heading = ""
        pending_level = 1

        def flush(next_heading: str, next_level: int) -> None:
            nonlocal current_heading, current_level, current_texts
            body = "\n".join(current_texts).strip()
            if body and not _is_metadata(current_heading):
                sections.append(
                    Section(
                        heading=current_heading,
                        level=current_level,
                        text=body,
                        page_start=0,
                        page_end=0,
                    )
                )
            current_heading, current_level, current_texts = next_heading, next_level, []

        for token in tokens:
            if token.type == "heading_open":
                in_heading = True
                pending_level = int(token.tag[1]) if token.tag else 1
            elif token.type == "inline" and in_heading:
                pending_heading = token.content
            elif token.type == "heading_close":
                in_heading = False
                flush(pending_heading, pending_level)
            elif token.type == "inline":
                current_texts.append(token.content)

        flush("_end", 0)
        if len(sections) < _MIN_CHAPTERS:
            return None

        return ParsedDocument(
            title=file_path.stem.replace("_", " ").title(),
            format="md",
            pages=0,
            word_count=len(raw_text.split()),
            sections=sections,
            raw_text=raw_text,
            structure_type="book",
        )

    def _parse_html(self, file_path: Path) -> ParsedDocument | None:
        raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"<[^>]+>", " ", raw_text)
        sections = self._segment_chapters(text)
        if not sections:
            return None
        return ParsedDocument(
            title=file_path.stem.replace("_", " ").title(),
            format="html",
            pages=0,
            word_count=len(text.split()),
            sections=sections,
            raw_text=text,
            structure_type="book",
        )

    def _strip_gutenberg(self, text: str) -> tuple[str, str]:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        m_start = _RE_PG_START.search(text)
        if m_start:
            text = text[m_start.end() :]
        m_end = _RE_PG_END.search(text)
        if m_end:
            text = text[: m_end.start()]
        raw_clean = text

        # New conservative TOC stripper: only active if "Contents" is found near start.
        if re.search(
            r"^\s*(?:Contents|TABLE OF CONTENTS)\s*$",
            text[:5000],
            re.IGNORECASE | re.MULTILINE,
        ):
            text = self._strip_toc_block(text)

        return text, raw_clean

    def _strip_toc_block(self, text: str) -> str:
        """Remove TOC block. Stops at the first significant gap to preserve body headers."""
        cutoff = min(len(text) // 10, 3000)  # Smaller window for TOC
        head = text[:cutoff]
        lines = head.splitlines()
        toc_start = toc_end = -1
        run = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                if run >= 3:
                    break
                run = 0
                continue
            if _RE_TOC_LINE.match(line):
                if toc_start == -1:
                    toc_start = i
                run += 1
                toc_end = i
            else:
                if run >= 3:
                    break
                toc_start = toc_end = -1
                run = 0
        if toc_start != -1 and toc_end - toc_start >= 3:
            # Verify we aren't stripping the start of the body
            # If the block contains more than 50% of the head, don't strip
            if (toc_end - toc_start) > len(lines) * 0.8:
                return text
            text = (
                "\n".join(lines[:toc_start])
                + "\n"
                + "\n".join(lines[toc_end + 1 :])
                + text[cutoff:]
            )
        return text

    def _segment_chapters(self, text: str) -> list[Section] | None:
        """Segment text into hierarchical sections using multiple active patterns."""
        all_matches = []
        for pid, pat, level in _PATTERNS:
            if pid == "P7" and not _RE_ENDETH.search(text):
                continue
            found = [m for m in pat.finditer(text) if _is_heading_line(text, m, pid)]
            if len(found) >= _MIN_CHAPTERS:
                all_matches += [_match(m, pid, level) for m in found]
        if all_matches:
            all_matches += [_match(m, "ND", None) for m in _RE_NAMED_DIVISION.finditer(text)]
        else:
            all_matches = [_match(m, "HR", 1) for m in _RE_DIVIDER.finditer(text)]
            if len(all_matches) < _MIN_CHAPTERS:
                return None
        all_matches.sort(key=lambda x: x["start"])

        filtered = [all_matches[0]]
        for m in all_matches[1:]:
            last = filtered[-1]
            if m["start"] < last["end"]:
                if (m["level"] or 99) < (last["level"] or 99):
                    filtered[-1] = m
                continue
            filtered.append(m)
        filtered = _without_contents_runs(text, filtered)
        if not filtered:
            return None
        for i, m in enumerate(filtered):
            if m["level"] is None:
                near = [f["level"] for f in [*filtered[i::-1], *filtered[i:]] if f["level"]]
                m["level"] = near[0] if near else 1

        sections: list[Section] = []
        front = text[: filtered[0]["start"]].strip()
        if _has_prose(front):
            # I-30: the source gave this text no heading, so it carries none.
            sections.append(
                Section(
                    heading="", level=filtered[0]["level"], text=front, page_start=0, page_end=0
                )
            )
        for i, m in enumerate(filtered):
            body_start = m["end"]
            body_end = filtered[i + 1]["start"] if i + 1 < len(filtered) else len(text)
            body_chunk = text[body_start:body_end].lstrip("\n")
            lines = body_chunk.splitlines()
            subtitle = ""
            body_offset = 0
            for li, line in enumerate(lines[:3]):
                stripped = line.strip()
                if stripped:
                    if _is_subtitle(stripped) and not _is_nav_line(stripped):
                        subtitle = stripped
                        body_offset = li + 1
                    break
            heading = _clean_heading(m["raw_heading"])
            if subtitle and subtitle.upper() != subtitle:
                heading = f"{heading} — {subtitle}"
            elif subtitle:
                heading = f"{heading} {subtitle}"
            if _is_metadata(heading):
                continue
            sections.append(
                Section(
                    heading=heading,
                    level=m["level"],
                    text="\n".join(lines[body_offset:]).strip(),
                    page_start=0,
                    page_end=0,
                )
            )
        # Before the chapter-count guard so it counts real chapters: a
        # contents page matches the same pattern and yields empty twins (I-30).
        sections = _drop_bodyless(sections)
        if not sections or len(sections) < _MIN_CHAPTERS:
            return None
        return _merge_duplicate_sections(sections)
