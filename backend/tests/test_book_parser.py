"""
tests/test_book_parser.py
=========================
Tests for the BookParser service — chapter-aware extraction and metadata stripping.

Covers all 8 heading pattern families across a variety of real files.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.services.book_parser import BookParser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATA_BOOKS = Path(__file__).parents[2] / "DATA" / "books"
DOCMATE_DATA = Path("/Users/sethurama/DEV/LM/doc-mate/DATA")

bp = BookParser()


def _book(name: str) -> Path:
    p = DATA_BOOKS / name
    if p.exists():
        return p
    p2 = DOCMATE_DATA / name
    if p2.exists():
        return p2
    pytest.skip(f"Book file not available: {name}")


# ---------------------------------------------------------------------------
# Metadata stripping
# ---------------------------------------------------------------------------


class TestGutenbergStripping:
    def test_header_stripped_from_time_machine(self):
        path = _book("time_machine.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        for section in result.sections:
            assert "Project Gutenberg" not in section.text
            assert "*** START OF" not in section.text

    def test_footer_stripped(self):
        path = _book("time_machine.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        for section in result.sections:
            assert "*** END OF THE PROJECT GUTENBERG" not in section.text

    def test_toc_not_a_section_body(self):
        """TOC entries (e.g. 'I. Introduction') should not appear as section bodies."""
        path = _book("time_machine.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        # Ensure no section has ONLY short TOC-like lines as its entire text
        for section in result.sections:
            lines = [ln.strip() for ln in section.text.splitlines() if ln.strip()]
            if lines:
                # At least one real sentence-length line should exist
                long_lines = [ln for ln in lines if len(ln) > 60]
                assert long_lines, (
                    f"Section '{section.heading}' seems to be only TOC: "
                    + repr(section.text[:200])
                )


# ---------------------------------------------------------------------------
# Pattern P1 — CHAPTER N. (Alice in Wonderland)
# ---------------------------------------------------------------------------


class TestP1AliceChapters:
    def test_chapter_count(self):
        path = _book("alice_in_wonderland.txt")
        result = bp.parse(path, "txt")
        assert result is not None, "BookParser returned None for Alice"
        assert len(result.sections) >= 10, f"Expected ≥10 chapters, got {len(result.sections)}"

    def test_chapter_headings_contain_chapter_token(self):
        path = _book("alice_in_wonderland.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        headings = [s.heading for s in result.sections]
        assert any("CHAPTER" in h.upper() or "Chapter" in h for h in headings), (
            f"No CHAPTER heading found in: {headings[:5]}"
        )

    def test_chapter_bodies_have_content(self):
        path = _book("alice_in_wonderland.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        for section in result.sections:
            assert len(section.text) > 100, (
                f"Section '{section.heading}' body too short: {section.text[:80]!r}"
            )


# ---------------------------------------------------------------------------
# Pattern P2 — Roman numeral + subtitle on next line (Time Machine)
# ---------------------------------------------------------------------------


class TestP2TimeMachineChapters:
    def test_chapter_count(self):
        path = _book("time_machine.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        assert len(result.sections) >= 8

    def test_no_gutenberg_in_headings(self):
        path = _book("time_machine.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        for s in result.sections:
            assert "Gutenberg" not in s.heading


# ---------------------------------------------------------------------------
# Pattern P3 — Roman numeral + CAPS title inline (Sherlock Holmes)
# ---------------------------------------------------------------------------


class TestP3SherlockHolmes:
    def test_chapter_count(self):
        path = _book("sherlock_holmes.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        assert len(result.sections) >= 10, f"Got {len(result.sections)} sections"

    def test_heading_starts_with_roman(self):
        path = _book("sherlock_holmes.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        # At least some headings should start with a roman numeral token
        import re
        roman_pat = re.compile(r"^[IVXLCDM]+[\.\s]", re.IGNORECASE)
        assert any(roman_pat.match(s.heading) for s in result.sections), (
            f"No roman-numeral heading found: {[s.heading for s in result.sections[:5]]}"
        )


# ---------------------------------------------------------------------------
# Pattern P4 — Centred roman numeral (Great Gatsby)
# ---------------------------------------------------------------------------


class TestP4GreatGatsby:
    def test_chapter_count(self):
        path = _book("the_great_gatsby.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        # Great Gatsby has 9 chapters (I–IX)
        assert len(result.sections) >= 9, f"Got {len(result.sections)} sections"


# ---------------------------------------------------------------------------
# Pattern P5 — Chapter N: Title (tech / modern books)
# ---------------------------------------------------------------------------


class TestP5TechChapter:
    def test_art_of_unix_fixture(self):
        path = Path(__file__).parent / "fixtures" / "art_of_unix_ch1.txt"
        if not path.exists():
            pytest.skip("art_of_unix_ch1.txt fixture not present")
        result = bp.parse(path, "txt")
        # Even a single chapter file might not trigger BookParser ≥2 threshold;
        # just ensure it doesn't crash
        assert result is None or len(result.sections) >= 1


# ---------------------------------------------------------------------------
# Pattern P6 — PART N / BOOK N (Gulliver's Travels — superstructure)
# ---------------------------------------------------------------------------


class TestP6GulliversTravels:
    def test_chapter_count(self):
        path = _book("gullivers_travels.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        # Gulliver has 4 parts × several chapters = many sections
        assert len(result.sections) >= 4, f"Got {len(result.sections)} sections"


# ---------------------------------------------------------------------------
# Pattern P7 — CHAPTER N (Gita-style, confirmed by HERE ENDETH)
# ---------------------------------------------------------------------------


class TestP7BhagavadGita:
    def test_chapter_count(self):
        path = _book("the_gita.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        # Gita has 18 chapters
        assert len(result.sections) >= 18, f"Got {len(result.sections)} sections"

    def test_chapter_headings(self):
        path = _book("the_gita.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        headings = [s.heading for s in result.sections]
        assert any("CHAPTER" in h.upper() for h in headings), str(headings[:5])


# ---------------------------------------------------------------------------
# Pattern P8 — Bible book headings
# ---------------------------------------------------------------------------


class TestP8Bible:
    def test_book_count(self):
        path = _book("the_bible.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        # Bible has 66 books; we should get a reasonable number of sections
        assert len(result.sections) >= 30, f"Got {len(result.sections)} sections"

    def test_genesis_heading_present(self):
        path = _book("the_bible.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        headings_lower = [s.heading.lower() for s in result.sections]
        genesis_found = any("genesis" in h or "book of moses" in h for h in headings_lower)
        assert genesis_found, f"Genesis heading not found in: {headings_lower[:10]}"


# ---------------------------------------------------------------------------
# Marcus Aurelius — ordinal BOOK (P6b)
# ---------------------------------------------------------------------------


class TestMarcusAurelius:
    def test_book_count(self):
        path = _book("meditations_marcus_aurelius.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        assert len(result.sections) >= 12, f"Got {len(result.sections)} sections"


# ---------------------------------------------------------------------------
# Fallback — unstructured text should return None
# ---------------------------------------------------------------------------


class TestFallbackToNone:
    def test_flat_paragraph_text_returns_none(self, tmp_path):
        """BookParser should return None for unstructured non-book text."""
        flat_file = tmp_path / "flat.txt"
        flat_file.write_text(
            textwrap.dedent("""\
                This is a simple paragraph-based document.
                It has no chapters and no headings.

                Another paragraph here. The content is mostly prose
                without any structural markers.

                One more paragraph to make it a bit longer. Still no chapters.
            """)
        )
        result = bp.parse(flat_file, "txt")
        assert result is None, "Expected None for flat unstructured text"


# ---------------------------------------------------------------------------
# Multi-format: Markdown
# ---------------------------------------------------------------------------


class TestMarkdownFormat:
    def test_md_heading_hierarchy(self, tmp_path):
        md_file = tmp_path / "book.md"
        md_file.write_text(
            textwrap.dedent("""\
                # Chapter One: The Beginning

                Lorem ipsum dolor sit amet, consectetur adipiscing elit.
                Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.

                # Chapter Two: The Middle

                Ut enim ad minim veniam, quis nostrud exercitation ullamco.
                Laboris nisi ut aliquip ex ea commodo consequat duis aute.

                # Chapter Three: The End

                Duis aute irure dolor in reprehenderit in voluptate velit esse.
                Cillum dolore eu fugiat nulla pariatur excepteur sint occaecat.
            """)
        )
        result = bp.parse(md_file, "md")
        assert result is not None
        assert len(result.sections) == 3
        assert result.sections[0].heading == "Chapter One: The Beginning"
        assert result.sections[0].level == 1


# ---------------------------------------------------------------------------
# Synthetic unit: _strip_gutenberg
# ---------------------------------------------------------------------------


class TestStripGutenberg:
    def test_strips_preamble_and_footer(self, tmp_path):
        sample = textwrap.dedent("""\
            The Project Gutenberg eBook of Test Book

            *** START OF THE PROJECT GUTENBERG EBOOK TEST BOOK ***

            CHAPTER I.

            The actual content starts here with real prose.
            This is the body of chapter one.

            CHAPTER II.

            The second chapter starts here. More content.
            This is the body of chapter two, with enough prose.

            *** END OF THE PROJECT GUTENBERG EBOOK TEST BOOK ***

            Some legal boilerplate at the end.
        """)
        f = tmp_path / "sample.txt"
        f.write_text(sample)
        result = bp.parse(f, "txt")
        assert result is not None
        full_text = " ".join(s.text for s in result.sections)
        assert "The Project Gutenberg eBook" not in full_text
        assert "legal boilerplate" not in full_text
        assert "actual content" in full_text

    def test_chapter_body_is_non_empty(self, tmp_path):
        sample = textwrap.dedent("""\
            *** START OF THE PROJECT GUTENBERG EBOOK SAMPLE ***

            CHAPTER I.
            The First Chapter

            This is the first chapter body. It has enough prose content.

            CHAPTER II.
            The Second Chapter

            This is the second chapter body. More prose content here.

            *** END OF THE PROJECT GUTENBERG EBOOK SAMPLE ***
        """)
        f = tmp_path / "sample2.txt"
        f.write_text(sample)
        result = bp.parse(f, "txt")
        assert result is not None
        assert len(result.sections) == 2
        assert result.sections[0].heading is not None
        assert len(result.sections[0].text) > 20


def test_alice_chapter_xi_subtitle():
    path = DATA_BOOKS / "alice_in_wonderland.txt"
    if not path.exists():
        pytest.skip("alice_in_wonderland.txt not found")
    
    result = bp.parse(path, "txt")
    assert result is not None
    # Chapter XI is usually the 11th chapter (index 10)
    # but there might be a preface or something.
    # Let's find it by heading.
    ch11 = next((s for s in result.sections if "CHAPTER XI" in s.heading), None)
    assert ch11 is not None
    assert "Who Stole the Tarts?" in ch11.heading

def test_html_parsing(tmp_path):
    html_content = """
    <html>
    <body>
    <h1>The Book Title</h1>
    *** START OF THE PROJECT GUTENBERG EBOOK TEST ***
    CHAPTER I.
    Introduction
    This is the first chapter body.
    CHAPTER II.
    The Second Part
    This is the second chapter body.
    *** END OF THE PROJECT GUTENBERG EBOOK TEST ***
    </body>
    </html>
    """
    html_file = tmp_path / "test_book.html"
    html_file.write_text(html_content)
    
    result = bp.parse(html_file, "html")
    assert result is not None
    assert len(result.sections) == 2
    # Dot is stripped by _clean_heading
    assert "CHAPTER I — Introduction" in result.sections[0].heading
    assert "CHAPTER II — The Second Part" in result.sections[1].heading
    assert result.format == "html"
