"""A no-TOC PDF must not turn its page numbers into section headings (#96).

The fallback scan promotes any large short line to a heading. A book that sets
its chapter-opening folio in display type therefore produced sections titled
`27` and `265` on a real library.
"""

import fitz
import pytest

from app.services.parser import DocumentParser, _is_folio


class TestIsFolio:
    """The bound is three digits, and both bracketing cases are real.

    `265` is a page number on the book that reported this; `1984` is a year, and
    a legitimate heading in any book that has one.
    """

    @pytest.mark.parametrize("text", ["27", "265", "9", "265.", "  27  "])
    def test_a_bare_number_is_a_folio(self, text: str) -> None:
        assert _is_folio(text) is True

    @pytest.mark.parametrize(
        "text",
        ["1984", "Chapter 5", "1. Introduction", "27 Ronin", "", "IV"],
    )
    def test_anything_else_is_not(self, text: str) -> None:
        assert _is_folio(text) is False


def _pdf_with_display_folio(path):
    """One page, no TOC: a big folio, a big heading, and body text.

    The folio is set larger than the heading, which is what makes it the
    document's top font size and so a level-1 heading to the old scan.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(72, 60), "27", fontsize=28)
    page.insert_text(fitz.Point(72, 120), "The Nature of Bread", fontsize=22)
    for i in range(12):
        page.insert_text(
            fitz.Point(72, 170 + i * 14),
            "Bread is made of flour and water and time, in that order.",
            fontsize=11,
        )
    doc.save(str(path))
    doc.close()
    return path


def test_a_display_folio_does_not_become_a_heading(tmp_path):
    pdf = _pdf_with_display_folio(tmp_path / "folio.pdf")

    parsed = DocumentParser().parse(pdf, "pdf")

    headings = [s.heading for s in parsed.sections]
    assert "27" not in headings, f"page number became a section heading: {headings}"
    assert any("Nature of Bread" in h for h in headings), (
        f"the real heading was lost: {headings}"
    )


def test_the_folio_text_is_still_present(tmp_path):
    """Rejecting it as a heading must not drop it from the document.

    The reported defect is a wrong heading, not lost text, and the fix must not
    turn one into the other.
    """
    pdf = _pdf_with_display_folio(tmp_path / "folio.pdf")

    parsed = DocumentParser().parse(pdf, "pdf")

    assert "27" in parsed.raw_text
