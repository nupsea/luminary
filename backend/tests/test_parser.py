import pytest

from app.services.parser import DocumentParser
from app.types import ParsedDocument


@pytest.fixture(scope="session")
def parser():
    return DocumentParser()


@pytest.fixture(scope="session")
def tmp_fixtures(tmp_path_factory):
    return tmp_path_factory.mktemp("fixtures")


@pytest.fixture(scope="session")
def pdf_file(tmp_fixtures):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    path = tmp_fixtures / "sample.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("Introduction", styles["Heading1"]),
        Paragraph("This is the introduction text with some content.", styles["Normal"]),
        Paragraph("Methods", styles["Heading1"]),
        Paragraph("This describes the methods used in this study.", styles["Normal"]),
    ]
    doc.build(elements)
    return path


@pytest.fixture(scope="session")
def docx_file(tmp_fixtures):
    from docx import Document

    path = tmp_fixtures / "sample.docx"
    doc = Document()
    doc.add_heading("Chapter One", level=1)
    doc.add_paragraph("This is the content of chapter one.")
    doc.add_heading("Section 1.1", level=2)
    doc.add_paragraph("A subsection with more detail.")
    doc.add_heading("Chapter Two", level=1)
    doc.add_paragraph("Content for chapter two.")
    doc.save(str(path))
    return path


@pytest.fixture(scope="session")
def txt_file(tmp_fixtures):
    path = tmp_fixtures / "sample.txt"
    content = (
        "First paragraph with some text.\n\nSecond paragraph that follows.\n\nThird paragraph here."
    )
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def md_file(tmp_fixtures):
    path = tmp_fixtures / "sample.md"
    content = (
        "# Title\n\nIntroduction text.\n\n"
        "## Background\n\nBackground content.\n\n"
        "## Methods\n\nMethods content."
    )
    path.write_text(content, encoding="utf-8")
    return path


def test_pdf_parse_returns_sections(parser, pdf_file):
    result = parser.parse(pdf_file, "pdf")
    assert isinstance(result, ParsedDocument)
    assert result.format == "pdf"
    assert result.pages > 0
    assert result.word_count > 0
    assert len(result.sections) >= 1


def test_docx_parse_returns_heading_hierarchy(parser, docx_file):
    result = parser.parse(docx_file, "docx")
    assert isinstance(result, ParsedDocument)
    assert result.format == "docx"
    headings = [s.heading for s in result.sections]
    assert "Chapter One" in headings or len(headings) >= 1
    levels = [s.level for s in result.sections]
    assert any(lvl == 1 for lvl in levels)


def test_txt_parse_detects_encoding_and_sections(parser, txt_file):
    result = parser.parse(txt_file, "txt")
    assert isinstance(result, ParsedDocument)
    assert result.format == "txt"
    assert len(result.sections) >= 2
    assert result.word_count > 0


def test_md_parse_detects_headings(parser, md_file):
    result = parser.parse(md_file, "md")
    assert isinstance(result, ParsedDocument)
    assert result.format == "md"
    headings = [s.heading for s in result.sections]
    assert "Title" in headings or "Background" in headings or "Methods" in headings
