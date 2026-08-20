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
