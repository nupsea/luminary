import logging
import re
from pathlib import Path

import chardet
import fitz  # PyMuPDF
from docx import Document as DocxDocument
from markdown_it import MarkdownIt

from app.types import ParsedDocument, Section

logger = logging.getLogger(__name__)


class DocumentParser:
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
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _parse_pdf(self, file_path: Path) -> ParsedDocument:
        doc = fitz.open(str(file_path))
        sections: list[Section] = []
        raw_parts: list[str] = []
        current_heading = "Introduction"
        current_level = 1
        current_page_start = 0
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

        flush_section("_end", 0, len(doc))

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

    def _parse_docx(self, file_path: Path) -> ParsedDocument:
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

    def _parse_txt(self, file_path: Path) -> ParsedDocument:
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

    def _parse_md(self, file_path: Path) -> ParsedDocument:
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
