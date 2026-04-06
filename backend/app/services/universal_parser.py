"""
universal_parser.py
===================
Generic, signature-driven parser for books, tech papers, scripts, and chats.
Discovers document structure by identifying repeating, monotonic sequences.
Optimised for low-resource environments (laptops).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import chardet

from app.types import ParsedDocument, Section

logger = logging.getLogger(__name__)

# Metadata/Boilerplate constants
_RE_PG_START = re.compile(
    r"\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^*]* \*\*\*", re.IGNORECASE
)
_RE_PG_END = re.compile(
    r"\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^*]* \*\*\*", re.IGNORECASE
)

# Headers that often look like chat names but are just document metadata
_METADATA_HEADERS = {
    "title", "author", "release date", "language", "credits", "produced by",
    "updated", "character", "scene", "location", "time", "date", "table of contents",
}

# Regex for chat_standard false positives: academic paper labels like
# "Figure 1", "Table 2", "Encoder", "Decoder", "Algorithm 1", etc.
_RE_NON_SPEAKER = re.compile(
    r"^(?:figure|table|fig|tab|algorithm|equation|listing|"
    r"encoder|decoder|appendix|lemma|theorem|corollary|proof|"
    r"definition|proposition|example|remark|note|step)\b",
    re.IGNORECASE,
)

@dataclass
class Signature:
    id: str
    pattern: re.Pattern[str]
    doc_type: str  # 'book', 'paper', 'script', 'chat'
    score: float = 0.0
    matches: list[re.Match[str]] = None

    def __post_init__(self):
        if self.matches is None:
            self.matches = []

class UniversalParser:
    """
    Universal parser that discovers structural 'signatures' in any document.
    """

    def __init__(self):
        # Universal Candidate Signatures
        self.candidates = [
            # 1. Tech/Academic: 1.1, 1.2.3, 2.1
            Signature(
                "num_hierarchical",
                re.compile(r"^[ \t]*(\d+\.\d+(?:\.\d+)?)[ \t]+([A-Z\d].*)$", re.M),
                "paper",
            ),
            # 2. Simple List/Section: 1. Introduction, 2. Methods
            Signature(
                "num_simple",
                re.compile(r"^[ \t]*(\d+)\.[ \t]+([A-Z].*)$", re.M),
                "paper",
            ),
            # 3. Explicit Book: CHAPTER I, Chapter - 1, CHAP: IV, CHAPTER FIRST
            Signature(
                "book_explicit",
                re.compile(
                    r"^[ \t]*(?:CHAPTER|CHAP\.?|SECTION|BOOK)\s*[:\-]?\s*"
                    r"([IVXLCDM]+|\d+|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|"
                    r"FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)"
                    r"\b.*$",
                    re.M | re.I,
                ),
                "book",
            ),
            # 4. Traditional Roman: I., II., III. (Left-aligned)
            Signature(
                "book_roman_dotted",
                re.compile(r"^[ \t]*([IVXLCDM]+\.)\s*$", re.M),
                "book",
            ),
            # 5. Centered Roman (Gatsby style): "    I", "    IX"
            # Require at least 2 spaces to be considered 'centered'
            Signature(
                "book_roman_centered",
                re.compile(r"^[ \t]{2,}([IVXLCDM]+)[ \t]*$", re.M | re.I),
                "book",
            ),
            # 6. Movie Scripts: INT. KITCHEN, EXT. PORCH
            Signature(
                "script_scene",
                re.compile(r"^[ \t]*(?:INT\.|EXT\.|INT/EXT\.?)\s+[A-Z].*$", re.M),
                "script",
            ),
            # 7. Conversations: Name: Speaker
            Signature(
                "chat_standard",
                re.compile(r"^[ \t]*([A-Z][\w\s]{1,20}):\s+(.*)$", re.M),
                "chat",
            ),
            # 8. Tech Paper Headers: Abstract, References, Introduction
            Signature(
                "paper_headers",
                re.compile(
                    r"^[ \t]*(?:Abstract|Introduction|Methods|Results|Discussion|"
                    r"Conclusion|References)\s*$",
                    re.M | re.I,
                ),
                "paper",
            ),
            # 9. Markdown: # Header, ## Header
            Signature(
                "markdown_header",
                re.compile(r"^#{1,6}\s+(.+)$", re.M),
                "paper",  # Use 'paper' doc_type as a generic structure
            ),
        ]

    def parse(self, file_path: Path, fmt: str = "txt") -> ParsedDocument | None:
        try:
            raw_text = self._read_text(file_path)
            if not raw_text:
                return None

            # 0. Strip boilerplate (Gutenberg, etc.) for better discovery
            clean_text, start_offset, end_offset = self._strip_boilerplate(raw_text)

            # 1. Discovery Phase: Find the 'beat' of the document
            best_sig = self._discover_signature(clean_text)

            # Minimum score threshold to prevent accidental segmentation
            # Lowered for short test files, but still robust for books
            if not best_sig or best_sig.score < 0.3:
                logger.debug("UniversalParser: No signature for %s (best=%.2f)", 
                             file_path, best_sig.score if best_sig else 0.0)
                return None

            logger.info("UniversalParser: detected %s (%s, score=%.2f, matches=%d)", 
                        best_sig.doc_type, best_sig.id, best_sig.score, len(best_sig.matches))

            # 2. Segmentation Phase: split the text using the discovered signature
            sections = self._segment(clean_text, best_sig)
            
            if not sections:
                return None

            return ParsedDocument(
                title=file_path.stem.replace("_", " ").title(),
                format=fmt,
                pages=0,
                word_count=len(clean_text.split()),
                sections=sections,
                raw_text=clean_text,
            )
        except Exception:
            logger.exception("UniversalParser failed for %s", file_path)
            return None

    def _read_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self._read_pdf_text(file_path)
        raw_bytes = file_path.read_bytes()
        detected = chardet.detect(raw_bytes)
        encoding = detected.get("encoding") or "utf-8"
        return raw_bytes.decode(encoding, errors="replace").replace("\r\n", "\n")

    @staticmethod
    def _read_pdf_text(file_path: Path) -> str:
        """Extract text from PDF using PyMuPDF instead of raw byte reading."""
        import fitz  # noqa: PLC0415

        doc = fitz.open(str(file_path))
        return "\n".join(page.get_text() for page in doc)

    def _strip_boilerplate(self, text: str) -> tuple[str, int, int]:
        """Returns (clean_text, start_offset, end_offset)."""
        start_offset = 0
        end_offset = len(text)

        m_start = _RE_PG_START.search(text)
        if m_start:
            start_offset = m_start.end()

        m_end = _RE_PG_END.search(text)
        if m_end:
            end_offset = m_end.start()

        return text[start_offset:end_offset], start_offset, end_offset

    def _discover_signature(self, text: str) -> Signature | None:
        """Adaptive discovery: probes first 50k, falls back to full text if weak."""
        # Skip the very beginning which might have TOC
        probe_start = 0
        if len(text) > 15000:
            probe_start = 5000
        
        probe_len = 60000
        probe_text = text[probe_start : probe_start + probe_len]
        
        best = self._probe(probe_text)
        # If we have a very strong hit in the probe window, use it.
        # Strong hit = monotonic sequence or many markers.
        if best and best.score >= 2.0:
            return best
        
        # Otherwise scan the whole doc to be sure
        full_best = self._probe(text)
        return full_best if not best or (full_best and full_best.score > best.score) else best

    def _probe(self, probe_text: str) -> Signature | None:
        """Statistical analysis of candidate patterns in a text block."""
        scored_sigs = []
        
        for sig in self.candidates:
            matches = list(sig.pattern.finditer(probe_text))
            if not matches:
                continue

            # Filter out matches that look like metadata
            valid_matches = []
            for m in matches:
                # If it's a "Name: ..." pattern, check if "Name" is a metadata header
                # or an academic paper label (Figure, Table, Encoder, etc.)
                if sig.id == "chat_standard":
                    name = m.group(1).strip()
                    if name.lower() in _METADATA_HEADERS:
                        continue
                    if _RE_NON_SPEAKER.match(name):
                        continue
                valid_matches.append(m)
            
            if not valid_matches:
                continue

            # Base Score: match frequency (normalized: 5 matches = 1.0 base score)
            score = len(valid_matches) / 5.0
            
            # Refinement: Regularity of spacing between markers
            if len(valid_matches) > 2:
                intervals = [
                    valid_matches[i].start() - valid_matches[i - 1].start() 
                    for i in range(1, len(valid_matches))
                ]
                avg_interval = sum(intervals) / len(intervals)
                if avg_interval > 0:
                    variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
                    std_dev_rel = (variance**0.5) / avg_interval
                    
                    if std_dev_rel < 0.2:  # Extremely regular
                        score *= 2.0
                    elif std_dev_rel < 0.4:  # Very regular
                        score *= 1.5
                    elif std_dev_rel > 1.2:  # Irregular
                        score *= 0.5

            # Special Case: Numbering monotonicity (does 1 follow 2?)
            if sig.id.startswith("num_") or sig.id.startswith("book_roman"):
                if self._is_monotonic(valid_matches):
                    score *= 2.5  # Heavy boost for monotonicity
                else:
                    score *= 0.2  # Penalize if it looks like numbers but doesn't count
            
            # Special Case: Chat (typically high frequency)
            if sig.doc_type == "chat":
                if len(valid_matches) > 15:
                    score *= 1.5
                elif len(valid_matches) < 6:
                    score *= 0.1

            # Special Case: Script Scene Headers
            if sig.id == "script_scene":
                score *= 1.5

            new_sig = Signature(sig.id, sig.pattern, sig.doc_type, score, valid_matches)
            scored_sigs.append(new_sig)

        if not scored_sigs:
            return None
            
        return max(scored_sigs, key=lambda s: s.score)

    def _is_monotonic(self, matches: list[re.Match[str]]) -> bool:
        """Check if numeric markers are increasing."""
        vals = []
        for m in matches:
            v_str = m.group(1).strip(".")
            # Case 1: Simple numbers (1, 1.1)
            if v_str.replace(".", "").isdigit():
                parts = v_str.split(".")
                try:
                    vals.append(int(parts[0]))
                except ValueError:
                    continue
            # Case 2: Roman numerals (I, II)
            elif re.match(r"^[IVXLCDM]+$", v_str, re.I):
                vals.append(self._roman_to_int(v_str))
            # Case 3: Ordinal words (ONE, TWO)
            elif v_str.upper() in _WORD_TO_INT:
                vals.append(_WORD_TO_INT[v_str.upper()])
        
        if len(vals) < 2:
            return False
        
        # Check for sequence breaks. Allow some noise (Gutenberg TOC often repeats numerals)
        # but the main body should be monotonic.
        increases = 0
        for i in range(1, len(vals)):
            if vals[i] > vals[i-1]:
                increases += 1
            elif vals[i] == vals[i-1]:
                # Equality might happen in TOCs, but we prefer strict increases
                pass
        
        return (increases / (len(vals) - 1)) > 0.7 if len(vals) > 1 else False

    def _roman_to_int(self, s: str) -> int:
        d = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        res, prev = 0, 0
        for c in reversed(s.upper()):
            curr = d.get(c, 0)
            if curr >= prev:
                res += curr
            else:
                res -= curr
            prev = curr
        return res

    def _segment(self, text: str, sig: Signature) -> list[Section]:
        """Split the text into sections based on the winning signature."""
        sections = []
        # Re-run finditer on the FULL clean text to get all matches
        matches = list(sig.pattern.finditer(text))
        
        # Re-filter matches if it's chat to avoid metadata
        if sig.id == "chat_standard":
            matches = [m for m in matches if m.group(1).lower().strip() not in _METADATA_HEADERS]

        if not matches:
            return []

        # If it's a high-frequency chat, group turns into chunks
        if sig.doc_type == "chat" and len(matches) > 50:
            return self._segment_chat_grouped(text, matches)
        
        for i, m in enumerate(matches):
            if sig.id == "markdown_header":
                heading = m.group(1).strip()
            else:
                heading = m.group(0).strip()
            start_pos = m.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body_chunk = text[start_pos:end_pos]

            # Adaptive Subtitle Detection (Gatsby/Classics)
            if sig.doc_type == "book":
                lines = body_chunk.strip("\n").splitlines()
                subtitle = ""
                body_start_line = 0
                for li, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped:
                        # subtitle: short, no end period, not another heading
                        # and check for Title Case or ALL CAPS (subtitles are rarely sentence-case)
                        words = stripped.split()
                        skip_words = {
                            "a", "an", "the", "and", "but", "or", "for",
                            "in", "on", "at", "to", "by"
                        }
                        is_title_case = all(
                            w[0].isupper() or w.lower() in skip_words
                            for w in words if w
                        )

                        if (
                            len(stripped) < 80
                            and stripped[-1] not in "."
                            and not sig.pattern.match(line)
                            and len(words) <= 12
                            and (is_title_case or stripped.isupper())
                        ):
                            subtitle = stripped
                            body_start_line = li + 1
                        break
                if subtitle:
                    heading = f"{heading} — {subtitle}"
                body = "\n".join(lines[body_start_line:]).strip()
            else:
                body = body_chunk.strip()

            if not body and i < len(matches) - 1:
                body = "(Empty Section)"

            sections.append(
                Section(
                    heading=heading,
                    level=1,
                    text=body or "(End of Document)",
                    page_start=0,
                    page_end=0,
                )
            )
            
        return sections

    def _segment_chat_grouped(self, text: str, matches: list[re.Match[str]]) -> list[Section]:
        """Group chat messages into sections to avoid fragmentation."""
        sections = []
        chunk_size = 30
        for i in range(0, len(matches), chunk_size):
            m_start = matches[i]
            m_end_idx = min(i + chunk_size, len(matches))
            
            next_m = matches[m_end_idx] if m_end_idx < len(matches) else None
            end_pos = next_m.start() if next_m else len(text)
            
            heading = f"Transcript Part {(i//chunk_size)+1}: {m_start.group(1)}"
            body = text[m_start.start():end_pos].strip()
            
            sections.append(Section(heading=heading, level=1, text=body, page_start=0, page_end=0))
        return sections

_WORD_TO_INT = {
    "ONE": 1,
    "TWO": 2,
    "THREE": 3,
    "FOUR": 4,
    "FIVE": 5,
    "SIX": 6,
    "SEVEN": 7,
    "EIGHT": 8,
    "NINE": 9,
    "TEN": 10,
    "FIRST": 1,
    "SECOND": 2,
    "THIRD": 3,
    "FOURTH": 4,
    "FIFTH": 5,
    "SIXTH": 6,
    "SEVENTH": 7,
    "EIGHTH": 8,
    "NINTH": 9,
    "TENTH": 10,
}
