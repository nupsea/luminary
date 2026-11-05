"""A PDF with no headings is one untitled section per page, so its chapters are page windows
(#491): as one section the size of the book it became one chapter labelled with its first page,
under a heading the source never had."""

from __future__ import annotations

import fitz

from app.services.chapters import SectionExtent, detect_chapters
from app.services.parser import DocumentParser

_LINE = "The traveller watched the sun sweep across the sky and the stars wheel overhead."


def _flat_book(path, pages: int):
    """One font size throughout: nothing a parser could take for a heading."""
    doc = fitz.open()
    for sheet in range(1, pages + 1):
        page = doc.new_page()
        for line in range(48):
            page.insert_text(fitz.Point(54, 60 + line * 15), f"{_LINE} {sheet}.{line}", fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


def test_each_page_of_a_headingless_pdf_is_its_own_untitled_section(tmp_path):
    parsed = DocumentParser().parse(_flat_book(tmp_path / "flat.pdf", 6), "pdf")

    assert [(s.heading, s.page_start, s.page_end) for s in parsed.sections] == [
        ("", n, n) for n in range(1, 7)
    ]
    assert all(
        f" {n}.0" in s.text and f" {n}.47" in s.text for n, s in enumerate(parsed.sections, 1)
    )


def test_a_headingless_book_is_windowed_by_page_ranges(tmp_path):
    parsed = DocumentParser().parse(_flat_book(tmp_path / "flat.pdf", 24), "pdf")
    extents = [
        SectionExtent(str(i), s.heading, i, len(s.text), s.page_start, s.page_end)
        for i, s in enumerate(parsed.sections)
    ]

    chapters = detect_chapters(extents, "flat")

    assert len(chapters) > 1
    assert all(c.title.startswith("Pages ") for c in chapters)
    assert chapters[0].page_start == 1 and chapters[-1].page_end == 24


def test_a_one_page_headingless_pdf_keeps_its_one_section(tmp_path):
    parsed = DocumentParser().parse(_flat_book(tmp_path / "one.pdf", 1), "pdf")

    assert len(parsed.sections) == 1
