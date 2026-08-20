"""A citation's page is the page its own text is on, not its chapter's first.

Measured on a real library before this existed: every section of every PDF
reported exactly one page across 25,000 chunks, one of them 2,329 chunks all
claiming p167. A citation into a long chapter therefore pointed as much as a
hundred pages from the sentence it quoted -- precise, and wrong, which is worse
than absent.
"""

import pytest

from app.services.parser import _block_start_offsets
from app.types import Section


class TestBlockOffsets:
    def test_offsets_account_for_the_blank_line_between_blocks(self):
        blocks = ["one", "two", "three"]
        # "one\n\ntwo\n\nthree": 0, 3+2=5, 5+3+2=10
        assert _block_start_offsets(blocks) == [0, 5, 10]

    def test_no_blocks_yields_no_offsets(self):
        assert _block_start_offsets([]) == []


class TestSectionCarriesPageBreaks:
    def test_a_section_defaults_to_no_page_breaks(self):
        """Non-PDF sections have no pages, and must not fabricate one."""
        section = Section(heading="h", level=1, text="body", page_start=0, page_end=0)
        assert section.page_breaks == []


class TestPerChunkPage:
    """The arithmetic the chunker applies, exercised on its own.

    The chunker itself needs a database session and a parsed document; the rule
    that was wrong is this sum, so it is tested where it can be read.
    """

    @staticmethod
    def _page_for(position: int, page_start: int, page_breaks: list[int]) -> int:
        return page_start + sum(1 for offset in page_breaks if offset <= position)

    @pytest.mark.parametrize(
        ("position", "expected"),
        [
            (0, 324),  # before any break: the section's own first page
            (99, 324),  # still on it
            (100, 325),  # exactly at a break belongs to the new page
            (5000, 336),  # deep into a long chapter
        ],
    )
    def test_position_selects_the_page_it_falls_on(self, position, expected):
        # A chapter opening on p324 whose text runs to p336, which is the case
        # that was reported: the citation said 324, the sentence was on 336.
        page_breaks = [100 * i for i in range(1, 13)]
        assert self._page_for(position, 324, page_breaks) == expected

    def test_a_section_with_no_breaks_reports_its_own_page(self):
        """One-page sections are the case the old behaviour got right."""
        assert self._page_for(500, 12, []) == 12


class TestPrintedLabel:
    """A sheet's position is not the number printed on it."""

    @staticmethod
    def _label(labels, page):
        from app.workflows.ingestion_nodes.chunk import _printed_label_for

        return _printed_label_for(labels, page)

    def test_the_printed_number_is_returned_when_one_exists(self):
        # Measured on a 613-page book: sheet 41 is printed "19", sheet 6 "iv".
        assert self._label({41: "19", 6: "iv"}, 41) == "19"
        assert self._label({41: "19", 6: "iv"}, 6) == "iv"

    def test_string_keys_survive_the_pipeline_state(self):
        """State is JSON on one path, so integer keys come back as strings."""
        assert self._label({"41": "19"}, 41) == "19"

    def test_a_document_without_labels_reports_none(self):
        """Three of four books in one library define no labels at all.

        None is what makes the citation fall back to the sheet number, which is
        the right answer there -- not an empty string rendered as a page.
        """
        assert self._label({}, 41) is None
        assert self._label({41: "19"}, 99) is None

    def test_a_chunk_with_no_page_has_no_label(self):
        assert self._label({41: "19"}, None) is None


class TestSectionPageCursor:
    """The shared rule, after three paths each got it wrong separately."""

    @staticmethod
    def _cursor(text, start, breaks):
        from app.workflows.ingestion_nodes.chunk import _SectionPageCursor

        return _SectionPageCursor(text, start, breaks)

    def test_each_chunk_reports_the_page_its_own_text_falls_on(self):
        text = "aaaa" + "bbbb" + "cccc"
        cursor = self._cursor(text, 324, [4, 8])
        assert cursor.page_for("aaaa") == 324
        assert cursor.page_for("bbbb") == 325
        assert cursor.page_for("cccc") == 326

    def test_a_section_on_one_page_reports_that_page(self):
        cursor = self._cursor("some text", 12, [])
        assert cursor.page_for("some") == 12
        assert cursor.page_for("text") == 12

    def test_a_non_pdf_section_has_no_page_at_all(self):
        """None, never 1: a text file has no page for a citation to name."""
        cursor = self._cursor("some text", None, [])
        assert cursor.page_for("some") is None

    def test_text_that_cannot_be_located_falls_back_to_the_section_page(self):
        """Some paths rewrite chunk text; a wrong page is worse than a coarse one."""
        cursor = self._cursor("aaaabbbb", 100, [4])
        assert cursor.page_for("this text is not in the section") == 100

    def test_pages_never_go_backwards_across_a_section(self):
        """Chunks are emitted in order, so their pages must not decrease.

        The cursor advances to each match rather than past it, because chunks
        overlap -- the next one starts inside the last. Identical text therefore
        resolves to the same position, which is why this asserts monotonicity
        rather than a strict increase.
        """
        text = "aaaa" + "bbbb" + "aaaa" + "cccc"
        cursor = self._cursor(text, 50, [4, 8, 12])
        pages = [cursor.page_for(part) for part in ("aaaa", "bbbb", "aaaa", "cccc")]
        assert pages == sorted(pages), pages
        assert pages[0] == 50 and pages[-1] == 53


class _StubPage:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_text(self) -> str:
        return self._text


class _StubDoc:
    """Enough of a PyMuPDF document for the header scan."""

    def __init__(self, pages: list[str]) -> None:
        self._pages = [_StubPage(p) for p in pages]
        self.page_count = len(pages)

    def __getitem__(self, index):
        return self._pages[index]


class TestPrintedNumbersFromText:
    """Books without PDF labels still print the number on the page."""

    @staticmethod
    def _scan(pages):
        from app.services.parser import _printed_numbers_from_text

        return _printed_numbers_from_text(_StubDoc(pages))

    def test_a_document_printing_its_own_sheet_numbers_yields_no_labels(self):
        """The label is only worth storing where it differs from the sheet.

        Same rule the declared-label reader and the reader footer both apply:
        a second number identical to the first is noise.
        """
        pages = [f"{n}\nA Title\nbody text here" for n in range(1, 21)]
        assert self._scan(pages) == {}

    def test_a_running_header_number_is_recovered(self):
        # Measured shape: sheet 340 of one volume opens with the line "336",
        # a constant four sheets of front matter ahead of the printed number.
        pages = ["cover", "title", "contents", "preface"] + [
            f"{n}\nHegel's Philosophy of Mind\nbody text here" for n in range(1, 17)
        ]
        found = self._scan(pages)
        assert found[10] == "6"
        assert found[20] == "16"

    def test_an_offset_between_sheet_and_printed_number_is_honoured(self):
        # Four sheets of front matter, then the body prints 1, 2, 3...
        pages = ["cover", "title", "contents", "preface"] + [
            f"{n}\nChapter text" for n in range(1, 17)
        ]
        found = self._scan(pages)
        assert found[5] == "1"
        assert found[20] == "16"

    def test_numbers_that_agree_on_nothing_yield_no_labels(self):
        """A bare number is not proof: it could be a figure label or a year.

        Agreement on one offset is what makes the reading trustworthy, so a
        document without it must name sheets rather than invent pages.
        """
        pages = ["12\nfigure", "99\nfigure", "3\nfigure", "451\nfigure"] * 5
        assert self._scan(pages) == {}

    def test_a_document_with_no_numbers_yields_no_labels(self):
        assert self._scan(["just prose"] * 10) == {}
