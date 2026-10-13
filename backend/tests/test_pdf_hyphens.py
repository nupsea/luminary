"""A word the typesetter broke at a line end is one word again after import.

DDIA's text layer carries 2,386 such breaks ("bookques‐ tions"): split words in the reader,
missed keyword hits, card quotes that match nothing. The join runs before page-break offsets
are measured, so each offset must still land on the first word of its page.
"""

import fitz
import pytest

from app.services import pdf_hyphens
from app.services.book_parser import BookParser
from app.services.parser import DocumentParser

_FONT = fitz.Font("helv")  # TextWriter keeps U+2010 and U+00AD in the text layer.
_BODY = "Cloth is made of thread and time, in that order, every day."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("the weav‐\ning loom", "the weaving loom"),
        ("an un­ \n finished web", "an unfinished web"),
        # A plain hyphen at a line end is as often a compound as a break.
        ("an in-\nmemory index", "an in-\nmemory index"),
        # A number after the break is a stray folio or note mark, not the word's end.
        ("the work‐\n18", "the work‐\n18"),
        # A blank line is a paragraph boundary, never a word break.
        ("weav‐\n\ning", "weav‐\n\ning"),
    ],
)
def test_only_a_typeset_break_followed_by_a_letter_joins(text, expected):
    assert pdf_hyphens.join_breaks(text) == expected


def test_a_compound_the_document_prints_mid_line_keeps_its_hyphen():
    assert pdf_hyphens.join_breaks("a well‐\nknown tale", frozenset({("well", "known")})) == (
        "a well‐known tale"
    )


def _write(page, y, text, size=11):
    writer = fitz.TextWriter(page.rect)
    writer.append(fitz.Point(72, y), text, font=_FONT, fontsize=size)
    writer.write_text(page)


def _book(path, *, heading_size=20, toc=False, compound=False):
    """Three sheets; sheet 1 opens with a heading and breaks "weaving" across two lines.
    Every sheet's first body line names its sheet, so a page break can be checked."""
    doc = fitz.open()
    for sheet in (1, 2, 3):
        page = doc.new_page()
        if sheet == 1:
            _write(page, 130, "CHAPTER 1", heading_size)
            _write(page, 180, "Sheet 1 opens. The weav‐")
            _write(page, 194, "ing of cloth is slow.")
        else:
            _write(page, 180, f"Sheet {sheet} opens. {_BODY}")
        if compound:
            _write(page, 208, "A well‐known tale.")
        for line in range(6):
            _write(page, 222 + line * 14, _BODY)
        if sheet == 3:
            _write(page, 320, "CHAPTER 2", heading_size)
            _write(page, 370, _BODY)
    if toc:
        doc.set_toc([[1, "CHAPTER 1", 1], [1, "CHAPTER 2", 3]])
    doc.save(str(path))
    doc.close()
    return path


def _assert_joined_and_pages_land(parsed):
    text = "\n".join(s.text for s in parsed.sections)
    assert "weaving of cloth" in text.replace("\n", " ")
    assert "weav‐" not in text
    for s in parsed.sections:
        for offset in s.page_breaks:
            assert s.text[offset:].startswith("Sheet "), (s.heading, s.text[offset : offset + 30])


def test_the_toc_path_joins_and_keeps_page_breaks(tmp_path):
    parsed = DocumentParser().parse(_book(tmp_path / "t.pdf", toc=True), "pdf")

    assert [s.heading for s in parsed.sections] == ["CHAPTER 1", "CHAPTER 2"]
    assert parsed.sections[0].page_breaks
    _assert_joined_and_pages_land(parsed)


def test_the_font_scan_path_joins_and_keeps_page_breaks(tmp_path):
    parsed = DocumentParser().parse(_book(tmp_path / "f.pdf"), "pdf")

    assert [s.heading for s in parsed.sections if s.heading.startswith("CHAPTER")] == [
        "CHAPTER 1",
        "CHAPTER 2",
    ]
    assert parsed.sections[-2].page_breaks
    _assert_joined_and_pages_land(parsed)


def test_the_book_parser_path_joins(tmp_path):
    parsed = BookParser().parse(_book(tmp_path / "b.pdf", heading_size=11), "pdf")

    assert parsed is not None
    assert [s.heading for s in parsed.sections] == ["CHAPTER 1", "CHAPTER 2"]
    assert [(s.page_start, s.page_end) for s in parsed.sections] == [(1, 3), (3, 3)]
    assert "weaving of cloth" in parsed.raw_text.replace("\n", " ")
    assert "weav‐" not in parsed.raw_text


def test_a_printed_compound_broken_at_a_line_end_keeps_its_hyphen(tmp_path):
    path = _book(tmp_path / "c.pdf", toc=True, compound=True)
    doc = fitz.open(str(path))
    page = doc[1]
    _write(page, 400, "A well‐")
    _write(page, 414, "known tale again.")
    doc.saveIncr()
    doc.close()

    text = "\n".join(s.text for s in DocumentParser().parse(path, "pdf").sections)

    assert "well‐known tale again" in text
    assert "wellknown" not in text
