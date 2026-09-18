"""A parent section must not store its children's text as well as its own (#97).

Each TOC entry used to end at the next entry at the same or higher level, so a
level-1 chapter's page range spanned every one of its level-2 children. Measured
on one library's eight TOC-bearing PDFs, 3,271 pages were held by more than one
section; on a 1,017-section manual the top section held 5,063,040 characters.
"""

import fitz
import pytest

from app.services.parser import DocumentParser

# One unmistakable token per page, so containment needs no fuzzy matching.
PAGES = [
    "CHAPTERONEOPENING the chapter's own introductory prose.",
    "SECTIONELEVEN the first subsection's body text.",
    "SECTIONTWELVE the second subsection's body text.",
    "CHAPTERTWOOPENING the second chapter's own prose.",
    "SECTIONTWENTYONE the last subsection's body text.",
]
TOKENS = [p.split()[0] for p in PAGES]

NESTED_TOC = [
    [1, "Chapter One", 1],
    [2, "Section 1.1", 2],
    [2, "Section 1.2", 3],
    [1, "Chapter Two", 4],
    [2, "Section 2.1", 5],
]


def _pdf(path, toc):
    doc = fitz.open()
    for body in PAGES:
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 100), body, fontsize=11)
    doc.set_toc(toc)
    doc.save(str(path))
    doc.close()
    return path


def _pdf_with_blocks(path, page_blocks, toc):
    """Like `_pdf`, but each page can hold several distinct text blocks.

    `insert_text` at different y-coordinates produces separate PyMuPDF
    blocks, the way two headings printed on one physical page really do.
    """
    doc = fitz.open()
    for blocks in page_blocks:
        page = doc.new_page()
        y = 100
        for block in blocks:
            page.insert_text(fitz.Point(72, y), block, fontsize=11)
            y += 40
    doc.set_toc(toc)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def nested(tmp_path):
    return DocumentParser().parse(_pdf(tmp_path / "nested.pdf", NESTED_TOC), "pdf")


def test_no_page_is_stored_in_two_sections(nested):
    for token in TOKENS:
        holders = [s.heading for s in nested.sections if token in s.text]
        assert len(holders) == 1, f"{token} stored in {len(holders)}: {holders}"


def test_every_page_is_still_stored_somewhere(nested):
    """The fix must remove duplication without losing text.

    This is the half that makes the change safe: narrowing a parent's range
    could silently drop a page that no other section covers.
    """
    for token in TOKENS:
        assert any(token in s.text for s in nested.sections), f"{token} lost"


def test_a_chapter_holds_its_own_prose_and_not_its_children(nested):
    chapter = next(s for s in nested.sections if s.heading == "Chapter One")
    assert "CHAPTERONEOPENING" in chapter.text
    assert "SECTIONELEVEN" not in chapter.text
    assert "SECTIONTWELVE" not in chapter.text


def test_page_end_is_never_before_page_start(nested):
    """A parent owning no whole page still sits on one.

    An end before the start is a range no client can read, and `page_end`
    reaches the API and the section rows.
    """
    for s in nested.sections:
        assert s.page_end >= s.page_start, f"{s.heading}: {s.page_start}..{s.page_end}"


def test_a_flat_toc_is_unchanged(tmp_path):
    """No nesting means no parents, which is why some documents never showed this."""
    flat = [[1, f"Part {i + 1}", i + 1] for i in range(len(PAGES))]
    parsed = DocumentParser().parse(_pdf(tmp_path / "flat.pdf", flat), "pdf")

    for token in TOKENS:
        holders = [s.heading for s in parsed.sections if token in s.text]
        assert len(holders) == 1, f"{token} stored in {len(holders)}: {holders}"


def test_a_parent_sharing_its_childs_first_page_does_not_copy_it(tmp_path):
    """A parent whose child opens on the same page owns no page, so it stays empty.

    Widening its range to that page stored the page twice: on a 2,441-section
    manual 579 such parents added 1.28M duplicated characters to the index.
    """
    same_page = [
        [1, "Chapter One", 1],
        [2, "Section 1.1", 1],
        [2, "Section 1.2", 3],
        [1, "Chapter Two", 4],
        [2, "Section 2.1", 5],
    ]
    parsed = DocumentParser().parse(_pdf(tmp_path / "same_page.pdf", same_page), "pdf")

    for token in TOKENS:
        holders = [s.heading for s in parsed.sections if token in s.text]
        assert len(holders) == 1, f"{token} stored in {len(holders)}: {holders}"


def test_same_page_siblings_are_attributed_to_their_own_heading(tmp_path):
    """Unrelated headings sharing a page must each keep their own prose (regression).

    The two tests above only check that a token is stored exactly once, not
    which section holds it -- so the previous fix passed them while making
    every non-last sibling on a shared page empty and dumping the whole
    page's text onto the last one instead. On "Attention Is All You Need"
    that emptied 12 of 22 sections and made a citation for "Regularization"
    (page 7) actually quote "Optimizer" or "Training", four headings
    earlier on the same page. A citation must land under the heading its
    own text is actually filed under, not merely under some heading.
    """
    page_one = [
        "Section One",
        "Section one's own body text ONETOKEN.",
        "Section Two",
        "Section two's own body text TWOTOKEN.",
        "Section Three",
        "Section three's own body text THREETOKEN.",
    ]
    page_two = ["Section Four", "Section four's own body text FOURTOKEN."]
    toc = [
        [1, "Section One", 1],
        [1, "Section Two", 1],
        [1, "Section Three", 1],
        [1, "Section Four", 2],
    ]
    parsed = DocumentParser().parse(
        _pdf_with_blocks(tmp_path / "siblings.pdf", [page_one, page_two], toc), "pdf"
    )

    by_heading = {s.heading: s for s in parsed.sections}
    assert set(by_heading) == {"Section One", "Section Two", "Section Three", "Section Four"}

    for heading, own_token, other_tokens in [
        ("Section One", "ONETOKEN", ["TWOTOKEN", "THREETOKEN", "FOURTOKEN"]),
        ("Section Two", "TWOTOKEN", ["ONETOKEN", "THREETOKEN", "FOURTOKEN"]),
        ("Section Three", "THREETOKEN", ["ONETOKEN", "TWOTOKEN", "FOURTOKEN"]),
        ("Section Four", "FOURTOKEN", ["ONETOKEN", "TWOTOKEN", "THREETOKEN"]),
    ]:
        section = by_heading[heading]
        assert own_token in section.text, f"{heading} lost its own prose: {section.text!r}"
        for other in other_tokens:
            assert other not in section.text, f"{heading} absorbed {other}: {section.text!r}"
