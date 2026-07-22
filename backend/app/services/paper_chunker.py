"""Research-paper chunking: structure-aware segmentation with a safe fallback.

Papers previously fell through to the generic splitter, which has no sentence
separator and a 300-char budget -- tight enough that splits descended past word
boundaries into characters. This module segments a section into prose, captions
and figure-internal noise before splitting, so captions stay whole and figure
label text never reaches the index.

Pure functions only; the ingestion node owns persistence.
"""

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

PAPER_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

# Academic caption conventions. A caption is kept atomic so retrieval returns the
# whole "Figure 3: ..." statement rather than half of it.
_CAPTION_RE = re.compile(
    r"^\s*(?:figure|fig\.?|table|algorithm|listing|scheme|equation|eq\.?)\s*\d+[.:)]",
    re.I,
)

_REFERENCES_RE = re.compile(
    r"^\s*(?:\d+[.\s]*)?(?:references|bibliography|works\s+cited|literature\s+cited)\s*$",
    re.I,
)

_STRUCTURAL_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.\s]+)?"
    r"(?:abstract|introduction|background|related\s+work|method(?:s|ology)?|"
    r"approach|model|experiment(?:s|al\s+setup)?|result(?:s)?|evaluation|"
    r"discussion|analysis|conclusion(?:s)?|future\s+work|references|"
    r"bibliography|appendix|acknowledg(?:e)?ments?)\b",
    re.I,
)

_NUMBERED_HEADING_RE = re.compile(r"^\s*\d+(?:\.\d+)*[.\s]+\S")

# A "token line" is a line holding at most this many words. Figure axis labels
# and legend entries are emitted one token per line by PDF text layers, so a long
# run of them marks figure internals rather than prose.
_TOKEN_LINE_MAX_WORDS = 2
_TOKEN_LINE_MAX_CHARS = 30
_MIN_NOISE_RUN = 6

# A caption runs until a blank line, but PDF text layers frequently emit none --
# unbounded, a caption would swallow every following page until the next figure.
_MAX_CAPTION_LINES = 8
_MAX_CAPTION_CHARS = 600


def is_references_heading(heading: str) -> bool:
    """True when a section heading denotes a reference list."""
    return bool(_REFERENCES_RE.match(heading or ""))


def looks_like_paper(sections: list[dict]) -> bool:
    """Gate for the structure-aware path.

    Requires several recognisable headings AND at least one anchor heading that
    only papers carry. A document that merely uses numbered headings (many
    manuals do) falls back to generic chunking rather than being force-fitted.
    """
    headings = [(s.get("heading") or "").strip() for s in sections]
    headings = [h for h in headings if h]
    if len(headings) < 3:
        return False

    structural = sum(1 for h in headings if _STRUCTURAL_HEADING_RE.match(h))
    numbered = sum(1 for h in headings if _NUMBERED_HEADING_RE.match(h))
    anchored = any(
        re.match(r"^\s*(?:\d+(?:\.\d+)*[.\s]+)?(?:abstract|references|bibliography)\b", h, re.I)
        or re.match(r"^\s*(?:\d+(?:\.\d+)*[.\s]+)?(?:introduction|conclusion)", h, re.I)
        for h in headings
    )
    return anchored and (structural + numbered) >= 3


def _is_token_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > _TOKEN_LINE_MAX_CHARS:
        return False
    return len(stripped.split()) <= _TOKEN_LINE_MAX_WORDS


def segment_section(text: str) -> list[tuple[str, str]]:
    """Split section text into ('prose'|'caption'|'noise', text) segments.

    Noise runs are the vertical token streams PDF text layers produce for figure
    internals. They are detected by shape rather than by any particular marker,
    so this generalises past one paper's notation.
    """
    lines = text.split("\n")
    segments: list[tuple[str, str]] = []
    buffer: list[str] = []
    kind = "prose"

    def flush() -> None:
        if buffer and "".join(buffer).strip():
            segments.append((kind, "\n".join(buffer)))
        buffer.clear()

    i = 0
    while i < len(lines):
        line = lines[i]

        run_end = i
        while run_end < len(lines) and _is_token_line(lines[run_end]):
            run_end += 1
        if run_end - i >= _MIN_NOISE_RUN:
            flush()
            kind = "noise"
            buffer.extend(lines[i:run_end])
            flush()
            kind = "prose"
            i = run_end
            continue

        if _CAPTION_RE.match(line):
            flush()
            kind = "caption"
            buffer.append(line)
            caption_chars = len(line)
            i += 1
            while (
                i < len(lines)
                and lines[i].strip()
                and not _CAPTION_RE.match(lines[i])
                and len(buffer) < _MAX_CAPTION_LINES
                and caption_chars < _MAX_CAPTION_CHARS
            ):
                buffer.append(lines[i])
                caption_chars += len(lines[i])
                i += 1
            flush()
            kind = "prose"
            continue

        buffer.append(line)
        i += 1

    flush()
    return segments


def unwrap_prose(text: str) -> str:
    """Rejoin PDF line-wrapped prose into real paragraphs.

    A PDF text layer breaks lines at the column edge, so '\\n' lands mid-sentence.
    Because the splitter tries '\\n' before '. ', those wrap points get used as
    split boundaries and chunks start mid-sentence. Unwrapping first restores
    paragraphs, letting the sentence separator do its job. Hyphenated line breaks
    are rejoined without the hyphen.
    """
    lines = text.split("\n")
    out: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            out.append("")
            continue
        if not out or not out[-1]:
            out.append(line)
            continue
        prev = out[-1]
        if prev.endswith("-") and len(prev) > 1 and prev[-2].isalpha():
            out[-1] = prev[:-1] + line.lstrip()
        elif prev.rstrip().endswith((".", "!", "?", ":", ";")):
            out.append(line)
        else:
            out[-1] = prev + " " + line.lstrip()
    return "\n".join(out)


def chunk_paper_section(section_text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Chunk one section: captions atomic, figure internals dropped, prose split.

    A caption longer than chunk_size is still emitted whole -- splitting it would
    strip the "Figure N" anchor from the half that describes the figure.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=PAPER_SEPARATORS,
    )

    out: list[str] = []
    for kind, text in segment_section(section_text):
        if kind == "noise":
            continue
        if kind == "caption":
            out.append(text.strip())
            continue
        for piece in splitter.split_text(unwrap_prose(text)):
            # Splitting on ". " leaves the period leading the next piece.
            cleaned = re.sub(r"^[.\s]+", "", piece)
            if cleaned.strip():
                out.append(cleaned)
    return out
