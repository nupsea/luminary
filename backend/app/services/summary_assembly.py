"""Building summary inputs and outputs from stored text. Pure: no I/O, no LLM."""

import re

from app.models import ChunkModel, SectionSummaryModel
from app.services.section_summarizer import FAST_PATH_MIN_UNITS, _is_metadata_section

# Rough token estimate used throughout; matches the chunker's own heuristic.
CHARS_PER_TOKEN = 4

# Max tokens per map call — stays within the generation window with room for output
MAP_BATCH_TOKENS = 3_000

# Slow path only, where no section summaries exist and `detailed` must be
# generated. Per-section output is the one mode that splits without changing
# meaning -- a synthesis would lose the cross-section view; this does not. Every
# batch is summarised and none is dropped, so the bound is on how long one call
# runs, never on how much of the document is covered.
DETAILED_BATCH_TOKENS = 1_500

# Publisher furniture: carries nothing a summary of the work should repeat.
_BOILERPLATE_HEADINGS = frozenset(
    {
        "praise",
        "praise for the book",
        "acknowledgments",
        "acknowledgements",
        "how to contact us",
        "conventions used in this book",
        "table of contents",
        "about the author",
        "about the authors",
        "colophon",
        "dedication",
        "copyright",
        "index",
        "using code examples",
    }
)
_BOILERPLATE_PREFIXES = ("praise for", "conventions used", "how to contact", "about the author")

# Authored prose, so the detailed summary keeps it; the key points skip it
# because it describes the book rather than saying what the book says.
_FRONT_MATTER_HEADINGS = frozenset(
    {
        "foreword",
        "preface",
        "prerequisites",
        "what this book is about",
        "who this book is for",
        "who this book is not for",
        "navigating this book",
        "note",
        "tip",
        "warning",
        "caution",
        "important",
    }
)

_RE_CHAPTER_HEADING = re.compile(
    r"^(?:chapter|part|appendix)\s+(?:\d+|[ivxlc]+|[a-z])\b", re.IGNORECASE
)
_RE_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_TAKEAWAY_TARGET_CHARS = 180


def _is_boilerplate_heading(heading: str) -> bool:
    h = heading.strip().lower()
    if not h:
        return False
    return h in _BOILERPLATE_HEADINGS or h.startswith(_BOILERPLATE_PREFIXES)


def _is_minor_heading(heading: str) -> bool:
    """Front matter, admonitions and figure captions: kept in full, not a key topic."""
    h = heading.strip().lower()
    return h in _FRONT_MATTER_HEADINGS or bool(re.match(r"^figure\s+\d+[-.]\d+", h))


def without_boilerplate(rows: list[SectionSummaryModel]) -> list[SectionSummaryModel]:
    """Drop publisher furniture, and the letter dividers of an index.

    A lone letter is an index divider only after an "Index" heading: elsewhere it
    is a chapter numeral, and "I" opens The Adventures of Sherlock Holmes.
    """
    kept: list[SectionSummaryModel] = []
    in_index = False
    for r in rows:
        heading = (r.heading or "").strip()
        if heading.lower() == "index":
            in_index = True
        elif not (in_index and len(heading) == 1 and heading.isalpha()):
            in_index = False
        if in_index or _is_boilerplate_heading(heading):
            continue
        if not (r.content or "").strip() or _is_metadata_section(r.heading, r.content):
            continue
        kept.append(r)
    return kept


def leading_sentences(content: str) -> str:
    """The first whole sentences of a section summary, up to about two.

    Cut only at a sentence boundary: a clipped sentence reads as a claim the
    summary never made.
    """
    result: list[str] = []
    total = 0
    for raw in _RE_SENTENCE_END.split(content.strip()):
        sentence = raw.strip()
        if not sentence:
            continue
        result.append(sentence)
        total += len(sentence)
        if total >= _TAKEAWAY_TARGET_CHARS or len(result) >= 2:
            break
    return " ".join(result)


def split_for_detail(text: str, budget_tokens: int = DETAILED_BATCH_TOKENS) -> list[str]:
    """Split on blank lines into batches of at most `budget_tokens`.

    Splits between paragraphs so a section is summarised as a whole. A single
    paragraph over the budget is its own batch rather than being cut: the point
    of batching is to bound one call, never to drop text.
    """
    batches: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for para in text.split("\n\n"):
        if not para.strip():
            continue
        tokens = len(para) // CHARS_PER_TOKEN
        if current and current_tokens + tokens > budget_tokens:
            batches.append("\n\n".join(current))
            current = []
            current_tokens = 0
        current.append(para)
        current_tokens += tokens
    if current:
        batches.append("\n\n".join(current))
    return batches


def chunk_into_batches(chunks: list[ChunkModel]) -> list[list[ChunkModel]]:
    """Split chunks into token-capped batches for map-reduce."""
    batches: list[list[ChunkModel]] = []
    current: list[ChunkModel] = []
    current_tokens = 0
    for chunk in chunks:
        t = chunk.token_count or len(chunk.text) // CHARS_PER_TOKEN
        if current and current_tokens + t > MAP_BATCH_TOKENS:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(chunk)
        current_tokens += t
    if current:
        batches.append(current)
    return batches


def section_summary_input(rows: list[SectionSummaryModel]) -> str | None:
    """Section summaries as one markdown input, or None if too few units exist.

    With >= FAST_PATH_MIN_UNITS units this is the direct input to every
    summarization mode (fast path), bypassing chunk map-reduce.
    """
    qualifying = [row for row in rows if not _is_metadata_section(row.heading, row.content)]
    if len(qualifying) < FAST_PATH_MIN_UNITS:
        return None
    return "\n\n".join(f"## {row.heading}\n{row.content}" for row in qualifying)


def _chapter_groups(
    rows: list[SectionSummaryModel],
) -> list[tuple[str | None, list[SectionSummaryModel]]]:
    """Rows grouped under each chapter heading. Rows before the first chapter stay
    their own group, so front matter and a preface are not lost."""
    groups: list[tuple[str | None, list[SectionSummaryModel]]] = []
    for r in rows:
        heading = (r.heading or "").strip()
        if _RE_CHAPTER_HEADING.match(heading):
            groups.append((heading, [r]))
        elif groups:
            groups[-1][1].append(r)
        else:
            groups.append((None, [r]))
    return groups


def _detailed(groups: list[tuple[str | None, list[SectionSummaryModel]]]) -> str:
    lines: list[str] = []
    for chapter_heading, members in groups:
        for i, r in enumerate(members):
            heading = (r.heading or "").strip()
            if chapter_heading is not None and i == 0:
                lines.append(f"## {heading}")
            elif heading:
                level = "###" if chapter_heading is not None else "##"
                lines.append(f"{level} {heading}")
            lines.append(r.content.strip())
            lines.append("")
    return "\n".join(lines).strip()


def _executive(chapters: list[tuple[str, list[SectionSummaryModel]]]) -> str:
    lines = ["### Key Takeaways by Chapter", ""]
    for chapter_heading, members in chapters:
        takeaway = leading_sentences(members[0].content)
        topics = [
            (m.heading or "").strip()
            for m in members[1:]
            if (m.heading or "").strip() and not _is_minor_heading(m.heading)
        ]
        topics_suffix = f" *Topics: {', '.join(topics)}.*" if topics else ""
        lines.append(f"- **{chapter_heading}**: {takeaway}{topics_suffix}")
    return "\n".join(lines).strip()


def assemble_summary(rows: list[SectionSummaryModel], mode: str) -> str | None:
    """Assemble a summary from section summaries, without an LLM call.

    detailed: every qualifying section summary in document order, whole,
    grouped under its chapter. Only publisher boilerplate is left out.

    executive: one entry per chapter, led by that chapter's opening
    summary. Returns None when the document has no chapter headings, since
    an extract of the first few sections would pass for key points of the
    whole work; the caller then synthesises with the LLM.

    No heading is invented (I-30): a section the source left unlabelled is
    rendered without one.
    """
    # Same floor as section_summary_input, so the two never disagree about
    # whether a document has usable section summaries.
    rows = without_boilerplate(rows)
    if len(rows) < FAST_PATH_MIN_UNITS:
        return None
    groups = _chapter_groups(rows)
    if mode == "detailed":
        return _detailed(groups)
    chapters = [(h, members) for h, members in groups if h is not None]
    if mode == "executive" and chapters:
        return _executive(chapters)
    return None
