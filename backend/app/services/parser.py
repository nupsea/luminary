import html
import logging
import re
from pathlib import Path

import chardet
import fitz  # PyMuPDF
from docx import Document as DocxDocument
from markdown_it import MarkdownIt

from app.services.book_parser import BookParser
from app.services.universal_parser import UniversalParser
from app.types import ParsedDocument, Section

# HTML tag stripper for EPUB content
_RE_HTML_TAGS = re.compile(r"<[^>]+>")
_RE_WHITESPACE = re.compile(r"\s+")

# Kindle clippings separator
_KINDLE_SEP = "=========="
# Highlight/note header: "- Your Highlight on page X | Added on Date"
_RE_KINDLE_HEADER = re.compile(
    r"^-\s+Your\s+(Highlight|Note|Bookmark)\s+.*\|\s+Added\s+on\s+(.+)$",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

# Shared instances (stateless)
_book_parser = BookParser()
_universal_parser = UniversalParser()


class DocumentParser:
    """
    General document parser.

    Uses a tiered approach:
    1. UniversalParser (signature discovery for books, scripts, papers, chat)
    2. BookParser (legacy regex families for classic books)
    3. Heuristic fallbacks (font-size, paragraph splits)
    """

    def parse(self, file_path: Path, format: str) -> ParsedDocument:
        fmt = format.lower()
        if fmt == "pdf":
            return self._parse_pdf(file_path)
        elif fmt == "docx":
            return self._parse_docx(file_path)
        elif fmt == "txt":
            return self._parse_txt(file_path)
        elif fmt in ("md", "markdown"):
            return self._parse_md(file_path)
        elif fmt == "epub":
            return self._parse_epub(file_path)
        else:
            raise ValueError(f"Unsupported format: {format}")

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------

    def _parse_pdf(self, file_path: Path) -> ParsedDocument:
        # Try BookParser first (legacy regex families for classic books)
        result = _book_parser.parse(file_path, "pdf")
        if result is not None:
            return result

        # Skip UniversalParser for PDFs -- the font-size heuristic below
        # leverages actual font metrics from the PDF structure and produces
        # better section boundaries than regex-based signature discovery.
        # UniversalParser is designed for plain text where font info is absent.
        doc = fitz.open(str(file_path))
        sections: list[Section] = []
        raw_parts: list[str] = []
        current_heading = "Introduction"
        current_level = 1
        current_page_start = 1  # 1-based to match pdfjs page numbering
        current_texts: list[str] = []

        all_font_sizes: list[float] = []
        for page in doc:
            for block in page.get_text("dict")["blocks"]:  # type: ignore[arg-type]
                if block.get("type") == 0:
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            all_font_sizes.append(span["size"])

        body_avg = sum(all_font_sizes) / len(all_font_sizes) if all_font_sizes else 12.0
        heading_threshold = body_avg * 1.2

        def flush_section(next_heading: str, next_level: int, next_page: int) -> None:
            nonlocal current_heading, current_level, current_page_start, current_texts
            text = "\n".join(current_texts).strip()
            if text:
                sections.append(
                    Section(
                        heading=current_heading,
                        level=current_level,
                        text=text,
                        page_start=current_page_start,
                        page_end=next_page - 1,
                    )
                )
            current_heading = next_heading
            current_level = next_level
            current_page_start = next_page
            current_texts = []

        for page_num, page in enumerate(doc):
            page_dict = page.get_text("dict")
            for block in page_dict["blocks"]:  # type: ignore[arg-type]
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    max_size = max(s["size"] for s in spans)
                    line_text = " ".join(s["text"] for s in spans).strip()
                    if not line_text:
                        continue
                    if max_size >= heading_threshold and len(line_text) < 120:
                        flush_section(line_text, 1, page_num + 1)
                    else:
                        current_texts.append(line_text)
                        raw_parts.append(line_text)

        flush_section("_end", 0, len(doc) + 1)  # +1 so last section page_end = len(doc) (1-based)

        raw_text = "\n".join(raw_parts)
        word_count = len(raw_text.split())
        title = file_path.stem
        return ParsedDocument(
            title=title,
            format="pdf",
            pages=len(doc),
            word_count=word_count,
            sections=sections,
            raw_text=raw_text,
        )

    # ------------------------------------------------------------------
    # DOCX
    # ------------------------------------------------------------------

    def _parse_docx(self, file_path: Path) -> ParsedDocument:
        # Try UniversalParser first
        result = _universal_parser.parse(file_path, "docx")
        if result is not None:
            return result

        # Try BookParser next
        result = _book_parser.parse(file_path, "docx")
        if result is not None:
            return result

        # Fallback: Word heading styles only
        doc = DocxDocument(str(file_path))
        sections: list[Section] = []
        raw_parts: list[str] = []
        current_heading = "Introduction"
        current_level = 1
        current_texts: list[str] = []
        section_order = 0

        def flush_section(next_heading: str, next_level: int) -> None:
            nonlocal current_heading, current_level, current_texts, section_order
            text = "\n".join(current_texts).strip()
            if text:
                sections.append(
                    Section(
                        heading=current_heading,
                        level=current_level,
                        text=text,
                        page_start=0,
                        page_end=0,
                    )
                )
                section_order += 1
            current_heading = next_heading
            current_level = next_level
            current_texts = []

        for para in doc.paragraphs:
            style_name = para.style.name if para.style else ""
            text = para.text.strip()
            if not text:
                continue
            if re.match(r"Heading\s+([1-3])", style_name):
                match = re.match(r"Heading\s+(\d+)", style_name)
                level = int(match.group(1)) if match else 1
                flush_section(text, level)
            else:
                current_texts.append(text)
                raw_parts.append(text)

        flush_section("_end", 0)

        raw_text = "\n".join(raw_parts)
        word_count = len(raw_text.split())
        title = file_path.stem
        return ParsedDocument(
            title=title,
            format="docx",
            pages=0,
            word_count=word_count,
            sections=sections,
            raw_text=raw_text,
        )

    # ------------------------------------------------------------------
    # TXT
    # ------------------------------------------------------------------

    def _parse_txt(self, file_path: Path) -> ParsedDocument:
        # Try BookParser first (legacy regex families for classic books)
        result = _book_parser.parse(file_path, "txt")
        if result is not None:
            return result

        # Try UniversalParser next (signature discovery)
        result = _universal_parser.parse(file_path, "txt")
        if result is not None:
            return result

        # Fallback: paragraph-split (for unstructured text files)
        raw_bytes = file_path.read_bytes()
        detected = chardet.detect(raw_bytes)
        encoding = detected.get("encoding") or "utf-8"
        text = raw_bytes.decode(encoding, errors="replace")
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        sections = [
            Section(
                heading=f"Section {i + 1}",
                level=1,
                text=para,
                page_start=0,
                page_end=0,
            )
            for i, para in enumerate(paragraphs)
        ]
        word_count = len(text.split())
        title = file_path.stem
        return ParsedDocument(
            title=title,
            format="txt",
            pages=0,
            word_count=word_count,
            sections=sections,
            raw_text=text,
        )

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------

    def _parse_md(self, file_path: Path) -> ParsedDocument:
        # Try UniversalParser first
        result = _universal_parser.parse(file_path, "md")
        if result is not None:
            return result

        # Try BookParser first (markdown-it token-based with min-chapter guard)
        result = _book_parser.parse(file_path, "md")
        if result is not None:
            return result

        # Fallback: same markdown-it logic without the chapter minimum guard
        text = file_path.read_text(encoding="utf-8")
        md = MarkdownIt()
        tokens = md.parse(text)

        sections: list[Section] = []
        current_heading = "Introduction"
        current_level = 1
        current_texts: list[str] = []
        in_heading = False
        pending_heading = ""
        pending_level = 1

        def flush_section(next_heading: str, next_level: int) -> None:
            nonlocal current_heading, current_level, current_texts
            body = "\n".join(current_texts).strip()
            if body:
                sections.append(
                    Section(
                        heading=current_heading,
                        level=current_level,
                        text=body,
                        page_start=0,
                        page_end=0,
                    )
                )
            current_heading = next_heading
            current_level = next_level
            current_texts = []

        for token in tokens:
            if token.type == "heading_open":
                in_heading = True
                pending_level = int(token.tag[1]) if token.tag else 1
            elif token.type == "inline" and in_heading:
                pending_heading = token.content
            elif token.type == "heading_close":
                in_heading = False
                flush_section(pending_heading, pending_level)
            elif token.type == "inline":
                current_texts.append(token.content)

        flush_section("_end", 0)

        word_count = len(text.split())
        title = file_path.stem
        return ParsedDocument(
            title=title,
            format="md",
            pages=0,
            word_count=word_count,
            sections=sections,
            raw_text=text,
        )

    # ------------------------------------------------------------------
    # EPUB
    # ------------------------------------------------------------------

    def _parse_epub(self, file_path: Path) -> ParsedDocument:
        """Extract chapters from an EPUB file using ebooklib."""
        import ebooklib  # noqa: PLC0415
        from ebooklib import epub  # noqa: PLC0415

        book = epub.read_epub(str(file_path), options={"ignore_ncx": True})

        # Derive title from metadata or filename
        title_meta = book.get_metadata("DC", "title")
        title = title_meta[0][0] if title_meta else file_path.stem.replace("_", " ").title()

        sections: list[Section] = []
        raw_parts: list[str] = []

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            item_name = item.get_name()
            # Skip navigation/toc documents
            if any(k in item_name.lower() for k in ("nav", "toc", "ncx")):
                continue

            raw_html = item.get_content().decode("utf-8", errors="replace")
            # Extract heading from first h1/h2/h3 tag
            heading_match = re.search(
                r"<h[1-3][^>]*>(.*?)</h[1-3]>", raw_html, re.IGNORECASE | re.DOTALL
            )
            if heading_match:
                heading_text = _RE_HTML_TAGS.sub("", heading_match.group(1))
                heading_text = html.unescape(heading_text).strip()
            else:
                # Use the item name as a fallback heading
                heading_text = Path(item_name).stem.replace("_", " ").replace("-", " ").title()

            # Strip all HTML tags from body
            plain = _RE_HTML_TAGS.sub(" ", raw_html)
            plain = html.unescape(plain)
            plain = _RE_WHITESPACE.sub(" ", plain).strip()

            if not plain or len(plain) < 50:
                continue

            sections.append(
                Section(
                    heading=heading_text,
                    level=1,
                    text=plain,
                    page_start=0,
                    page_end=0,
                )
            )
            raw_parts.append(plain)

        if not sections:
            # Fallback: treat entire content as one section
            logger.warning("_parse_epub: no usable chapters found in %s", file_path)
            full_text = " ".join(raw_parts) if raw_parts else ""
            sections = [
                Section(
                    heading="Content",
                    level=1,
                    text=full_text or "(empty)",
                    page_start=0,
                    page_end=0,
                )
            ]

        raw_text = "\n\n".join(raw_parts)
        word_count = len(raw_text.split())
        logger.info(
            "_parse_epub: %d sections, %d words from %s",
            len(sections),
            word_count,
            file_path,
        )
        return ParsedDocument(
            title=title,
            format="epub",
            pages=0,
            word_count=word_count,
            sections=sections,
            raw_text=raw_text,
        )

    # ------------------------------------------------------------------
    # Kindle My Clippings.txt
    # ------------------------------------------------------------------

    @staticmethod
    def parse_kindle_clippings(text: str) -> list[ParsedDocument]:
        """Parse a Kindle My Clippings.txt file into one ParsedDocument per book.

        Returns a list of ParsedDocument objects, one per book title found.
        Each section in the document is one highlight (with date as heading).
        """
        # Split on the separator line (lines starting with ==========)
        entries = re.split(r"^==========[ \t]*$", text, flags=re.MULTILINE)

        # Group highlights by book title (first non-empty line of each entry)
        books: dict[str, list[Section]] = {}
        book_order: list[str] = []

        for entry in entries:
            lines = [ln.strip() for ln in entry.strip().splitlines() if ln.strip()]
            if len(lines) < 2:
                continue

            book_title = lines[0]
            # Strip any author in parentheses: "Title (Author Name)" -> "Title"
            book_title_clean = re.sub(r"\s*\([^)]*\)\s*$", "", book_title).strip()
            if not book_title_clean:
                continue

            # Find the metadata header line (contains "Your Highlight" or "Your Note")
            metadata_line = ""
            content_lines: list[str] = []
            header_found = False
            for line in lines[1:]:
                m = _RE_KINDLE_HEADER.match(line)
                if m and not header_found:
                    metadata_line = line
                    header_found = True
                elif header_found:
                    content_lines.append(line)

            if not content_lines:
                continue

            highlight_text = " ".join(content_lines).strip()
            if not highlight_text:
                continue

            # Use "Added on <date>" as the section heading
            date_str = ""
            date_match = re.search(r"Added on (.+)$", metadata_line)
            if date_match:
                date_str = date_match.group(1).strip()

            heading = f"Highlight ({date_str})" if date_str else "Highlight"

            if book_title_clean not in books:
                books[book_title_clean] = []
                book_order.append(book_title_clean)

            books[book_title_clean].append(
                Section(heading=heading, level=1, text=highlight_text, page_start=0, page_end=0)
            )

        documents: list[ParsedDocument] = []
        for book_title in book_order:
            sections = books[book_title]
            raw_text = "\n\n".join(s.text for s in sections)
            word_count = len(raw_text.split())
            documents.append(
                ParsedDocument(
                    title=book_title,
                    format="txt",
                    pages=0,
                    word_count=word_count,
                    sections=sections,
                    raw_text=raw_text,
                )
            )

        logger.info("parse_kindle_clippings: found %d books", len(documents))
        return documents
