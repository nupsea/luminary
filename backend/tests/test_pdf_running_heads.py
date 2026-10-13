"""A PDF's running heads and page numbers are not prose, and stripping them moves nothing else.

Ingested without them, a book's text read "two families of 69 storage engines": a page
number mid-sentence, where a quote check cannot match and the reader shows a paragraph
"74 | Chapter 3: Storage and Retrieval". The twin test is the guard for citations and the
reader: the same book with and without furniture must parse to the same sections, pages,
page breaks and text.
"""

import fitz
import pytest

from app.services import pdf_furniture
from app.services.book_parser import BookParser
from app.services.parser import DocumentParser

_PAGES = 5
_BODY = "Bread is made of flour and water and time, in that order, every day."


def _book(path, *, furniture: bool, heading: str = "The Nature of Bread"):
    """No TOC. A heading on sheet 1, body on every sheet, and (if furniture) a running head
    at the top and the printed number, sheet + 100, at the foot of every sheet."""
    doc = fitz.open()
    for sheet in range(1, _PAGES + 1):
        page = doc.new_page()  # A4: 842pt tall, so the margin band is 84pt
        if furniture:
            page.insert_text(fitz.Point(72, 40), f"{sheet + 100} | Chapter 3: Bread", fontsize=9)
            page.insert_text(fitz.Point(290, 820), str(sheet + 100), fontsize=9)
        if sheet == 1:
            page.insert_text(fitz.Point(72, 130), heading, fontsize=20)
        for line in range(10):
            page.insert_text(
                fitz.Point(72, 180 + line * 14), f"{_BODY} Sheet {sheet}.", fontsize=11
            )
        # Recurs on every sheet, but in the body: content, not furniture.
        page.insert_text(fitz.Point(72, 400), "Exercise: knead it.", fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def _shape(parsed):
    return [
        (s.heading, s.level, s.page_start, s.page_end, s.page_breaks, s.text)
        for s in parsed.sections
    ]


def test_a_running_head_and_page_number_are_stripped(tmp_path):
    parsed = DocumentParser().parse(_book(tmp_path / "f.pdf", furniture=True), "pdf")

    assert "Chapter 3: Bread" not in parsed.raw_text
    assert "| " not in parsed.raw_text
    assert not any(str(n) in parsed.raw_text for n in range(101, 101 + _PAGES))
    assert parsed.raw_text.count("Exercise: knead it.") == _PAGES


def test_stripping_moves_no_section_page_or_offset(tmp_path):
    """Sections, page ranges and page breaks are what citations and the reader are built
    from; with the furniture gone they must equal the book that never had any."""
    with_furniture = DocumentParser().parse(_book(tmp_path / "f.pdf", furniture=True), "pdf")
    without = DocumentParser().parse(_book(tmp_path / "n.pdf", furniture=False), "pdf")

    assert _shape(with_furniture) == _shape(without)


def test_citations_still_name_the_printed_page(tmp_path):
    """Printed numbers are read from the page as printed, before any stripping."""
    parsed = DocumentParser().parse(_book(tmp_path / "f.pdf", furniture=True), "pdf")

    assert parsed.page_labels == {s: str(s + 100) for s in range(1, _PAGES + 1)}


def test_a_heading_set_in_the_margin_is_kept(tmp_path):
    """A chapter title at the top of its page appears once; only recurring lines go."""
    doc = fitz.open()
    for sheet in range(1, _PAGES + 1):
        page = doc.new_page()
        if sheet == 1:
            page.insert_text(fitz.Point(72, 40), "Printed once", fontsize=9)
        page.insert_text(fitz.Point(72, 400), f"{_BODY} Sheet {sheet}.", fontsize=11)
    path = tmp_path / "once.pdf"
    doc.save(str(path))
    doc.close()

    assert "Printed once" in DocumentParser().parse(path, "pdf").raw_text


@pytest.mark.parametrize(
    ("pages_seen", "running"),
    [(pdf_furniture.MIN_RUNNING_PAGES - 1, False), (pdf_furniture.MIN_RUNNING_PAGES, True)],
)
def test_furniture_must_recur(tmp_path, pages_seen, running):
    doc = fitz.open()
    for sheet in range(1, _PAGES + 1):
        page = doc.new_page()
        if sheet <= pages_seen:
            page.insert_text(fitz.Point(72, 40), f"{sheet} | Bread", fontsize=9)
        page.insert_text(fitz.Point(72, 400), _BODY, fontsize=11)

    assert ("#|bread" in pdf_furniture.running_signatures(doc)) is running


def test_the_book_parser_path_strips_furniture_and_keeps_its_pages(tmp_path):
    """The last-resort path for flat-font PDFs: chapters found by their text."""

    def flat_book(path, furniture):
        doc = fitz.open()
        for sheet in range(1, _PAGES + 1):
            page = doc.new_page()
            if furniture:
                page.insert_text(fitz.Point(72, 40), f"{sheet + 100} | Bread", fontsize=11)
            if sheet in (1, 4):
                page.insert_text(fitz.Point(72, 130), f"CHAPTER {sheet}", fontsize=11)
            for line in range(10):
                page.insert_text(fitz.Point(72, 180 + line * 14), _BODY, fontsize=11)
        doc.save(str(path))
        doc.close()
        return path

    with_furniture = BookParser().parse(flat_book(tmp_path / "f.pdf", True), "pdf")
    without = BookParser().parse(flat_book(tmp_path / "n.pdf", False), "pdf")

    assert with_furniture is not None and without is not None
    # CHAPTER 4 opens its page; with the running head gone, nothing precedes it there.
    assert [s.heading for s in with_furniture.sections] == ["CHAPTER 1", "CHAPTER 4"]
    assert "| Bread" not in with_furniture.raw_text
    assert [(s.heading, s.page_start, s.page_end) for s in with_furniture.sections] == [
        (s.heading, s.page_start, s.page_end) for s in without.sections
    ]
    assert [s.text for s in with_furniture.sections] == [s.text for s in without.sections]
