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
from app.services.parser import DocumentParser

# Helpers

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


# Metadata stripping


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
                assert long_lines, f"Section '{section.heading}' seems to be only TOC: " + repr(
                    section.text[:200]
                )


# Pattern P1 — CHAPTER N. (Alice in Wonderland)


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


# Pattern P2 — Roman numeral + subtitle on next line (Time Machine)


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


# Pattern P3 — Roman numeral + CAPS title inline (Sherlock Holmes)


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


# Pattern P4 — Centred roman numeral (Great Gatsby)


class TestP4GreatGatsby:
    def test_chapter_count(self):
        path = _book("the_great_gatsby.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        # Great Gatsby has 9 chapters (I–IX)
        assert len(result.sections) >= 9, f"Got {len(result.sections)} sections"


# Pattern P5 — Chapter N: Title (tech / modern books)


class TestP5TechChapter:
    def test_art_of_unix_fixture(self):
        path = Path(__file__).parent / "fixtures" / "art_of_unix_ch1.txt"
        if not path.exists():
            pytest.skip("art_of_unix_ch1.txt fixture not present")
        result = bp.parse(path, "txt")
        # Even a single chapter file might not trigger BookParser ≥2 threshold;
        # just ensure it doesn't crash
        assert result is None or len(result.sections) >= 1


# Pattern P6 — PART N / BOOK N (Gulliver's Travels — superstructure)


class TestP6GulliversTravels:
    def test_chapter_count(self):
        path = _book("gullivers_travels.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        # Gulliver has 4 parts × several chapters = many sections
        assert len(result.sections) >= 4, f"Got {len(result.sections)} sections"


# Pattern P7 — CHAPTER N (Gita-style, confirmed by HERE ENDETH)


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


# Pattern P8 — Bible book headings


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


# Marcus Aurelius — ordinal BOOK (P6b)


class TestMarcusAurelius:
    def test_book_count(self):
        path = _book("meditations_marcus_aurelius.txt")
        result = bp.parse(path, "txt")
        assert result is not None
        assert len(result.sections) >= 12, f"Got {len(result.sections)} sections"


# Fallback — unstructured text should return None


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


# Multi-format: Markdown


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


# Synthetic unit: _strip_gutenberg


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


def test_wrapped_prose_is_not_promoted_into_the_heading(tmp_path):
    """A chapter's opening line belongs in the body, not in its heading.

    Gutenberg text wraps at ~70 chars, and the old subtitle test took any line
    under 100 chars that did not end in a full stop -- so Frankenstein's
    chapters were headed "Chapter 1 — I am by birth a Genevese, and my family
    is one of the most", and that line was deleted from the body as well.
    """
    opening = "I am by birth a Genevese, and my family is one of the most"
    text = "\n\n".join(
        f"Chapter {n}\n\n{opening}\ndistinguished of that republic, for many years."
        for n in range(1, 4)
    )
    f = tmp_path / "wrapped.txt"
    f.write_text(text)

    result = bp.parse(f, "txt")
    assert result is not None
    assert [s.heading for s in result.sections] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    for section in result.sections:
        assert section.text.startswith(opening)


def test_short_subtitle_survives_its_question_mark():
    """Terminal punctuation is not a signal: "Who Stole the Tarts?" is a title."""
    from app.services.book_parser import _is_subtitle

    assert _is_subtitle("Who Stole the Tarts?")
    assert _is_subtitle("Down the Rabbit-Hole")
    assert _is_subtitle("A Caucus-Race and a Long Tale")
    # ALL-CAPS argument lines head each book of the Odyssey and run long.
    assert _is_subtitle("THE GODS IN COUNCIL—MINERVA'S VISIT TO ITHACA—THE CHALLENGE")
    assert not _is_subtitle("I am by birth a Genevese, and my family is one of the most")
    assert not _is_subtitle("At three o'clock precisely I was at Baker Street, but Holmes had")


def test_contents_page_twins_are_dropped(tmp_path):
    """A book's own contents page matches the same pattern as its chapters.

    Ten of `time_machine.txt`'s 26 sections were its table of contents, each a
    heading with no body, which the reader drew as an empty chapter.
    """
    text = (
        "Chapter 1\nChapter 2\nChapter 3\n\n"
        "Chapter 1\n\nThe first chapter opens here with real prose to read.\n\n"
        "Chapter 2\n\nThe second chapter continues the story at some length.\n\n"
        "Chapter 3\n\nThe third chapter brings the whole matter to a close.\n"
    )
    f = tmp_path / "twins.txt"
    f.write_text(text)

    result = bp.parse(f, "txt")
    assert result is not None
    assert all(s.text.strip() for s in result.sections)


def test_docbook_nav_line_is_never_a_subtitle(tmp_path):
    """A scraped DocBook page puts its navigation under the chapter heading (#229)."""
    text = "\n".join(
        f"Chapter {n}. {title}\nPrev {prev}\nNext\n"
        f"The chapter on {title.lower()} opens here with real prose to read.\n"
        "Prev\nUp\nNext\nHome\n"
        for n, title, prev in (
            (1, "Philosophy", "Part I. Context"),
            (2, "History", "Chapter 1. Philosophy"),
            (3, "Contrasts", "Chapter 2. History"),
        )
    )
    f = tmp_path / "docbook.txt"
    f.write_text(text)

    result = bp.parse(f, "txt")
    assert result is not None
    assert [s.heading for s in result.sections] == [
        "Chapter 1. Philosophy",
        "Chapter 2. History",
        "Chapter 3. Contrasts",
    ]


def test_nav_line_shapes():
    from app.services.universal_parser import _is_nav_line

    for nav in ("Prev", "Up", "Next", "Home", "Prev Part I. Context", "Next Chapter 2. History"):
        assert _is_nav_line(nav), nav
    for title in ("Next Steps", "Up the Line", "Homeward Bound", "Previews of Coming Attractions"):
        assert not _is_nav_line(title), title


# Reading order and heading shapes (#332, #333)

_PROSE = (
    "This paragraph is ordinary narrative prose, long enough to read as a real paragraph of the "
    "book rather than a title line, and it ends the way sentences end, with a full stop."
)


def _parse_text(tmp_path, text: str):
    f = tmp_path / "book.txt"
    f.write_text(text)
    result = bp.parse(f, "txt")
    assert result is not None
    return result.sections


def _in_reading_order(sections, text: str) -> bool:
    flat = " ".join(text.split())
    starts = [flat.find(" ".join(s.text.split())[:60]) for s in sections]
    return -1 not in starts and starts == sorted(starts)


def test_a_contents_list_does_not_claim_the_text_after_it(tmp_path):
    """Frankenstein's last contents entry ("Chapter 24") took the opening Letters, and the
    duplicate merge appended them after the real Chapter 24 (#332)."""
    text = (
        "A Novel\n\n CONTENTS\n\n Chapter 1\n Chapter 2\n Chapter 3\n Chapter 4\n\n\n"
        f"An unheaded opening. {_PROSE}\n\n"
        + "".join(f"Chapter {n}\n\nChapter {n} begins. {_PROSE}\n\n" for n in range(1, 5))
    )
    sections = _parse_text(tmp_path, text)

    assert [s.heading for s in sections] == ["", "Chapter 1", "Chapter 2", "Chapter 3", "Chapter 4"]
    assert sections[0].text.startswith("A Novel")
    assert "unheaded opening" in sections[0].text
    assert "unheaded opening" not in sections[-1].text


def test_text_before_the_first_heading_is_kept_only_when_it_is_prose(tmp_path):
    chapters = "".join(f"CHAPTER {n}.\n\nChapter {n} begins. {_PROSE}\n\n" for n in ("I", "II"))

    title_only = _parse_text(tmp_path, "A Novel\n\nby Someone\n\n" + chapters)
    with_prologue = _parse_text(tmp_path, f"A Novel\n\n{_PROSE}\n\n" + chapters)

    assert [s.heading for s in title_only] == ["CHAPTER I", "CHAPTER II"]
    assert [s.heading for s in with_prologue] == ["", "CHAPTER I", "CHAPTER II"]


def test_a_numbering_that_restarts_keeps_every_chapter_in_place(tmp_path):
    """Gulliver's Parts each restart at CHAPTER I; merging twins by name collapsed four Parts
    into 12 chapters out of order (#332)."""
    text = "".join(
        ("" if c != "I" else f"PART {p}.\n\n")
        + f"CHAPTER {c}.\n\nPart {p} chapter {c}. {_PROSE}\n\n"
        for p in ("I", "II")
        for c in ("I", "II", "III")
    )
    sections = _parse_text(tmp_path, text)

    assert [s.heading for s in sections] == ["CHAPTER I", "CHAPTER II", "CHAPTER III"] * 2
    assert _in_reading_order(sections, text)


def test_a_divider_beside_chapters_is_a_scene_break(tmp_path):
    """The Great Gatsby's dividers sit inside its chapters; as headings, all 25 merged into one
    157k-character section (#332)."""
    rule = "-" * 72
    text = "".join(
        f"\n    {n}\n\n{n} opens. {_PROSE}\n\n{rule}\n\nAfter the break. {_PROSE}\n\n"
        for n in ("I", "II", "III")
    )
    sections = _parse_text(tmp_path, text)

    assert [s.heading for s in sections] == ["I", "II", "III"]
    assert all("After the break" in s.text for s in sections)


def test_an_epilogue_beside_chapters_is_its_own_section(tmp_path):
    text = (
        "".join(f"CHAPTER {n}.\n\nChapter {n}. {_PROSE}\n\n" for n in ("I", "II"))
        + f"EPILOGUE\n\nAfterwards. {_PROSE}\n"
    )
    sections = _parse_text(tmp_path, text)

    assert [(s.heading, s.level) for s in sections][-1] == ("EPILOGUE", 1)
    assert "Afterwards" not in sections[1].text


def test_numbered_papers_are_sections_and_prose_lines_are_not(tmp_path):
    """The Federalist Papers parsed to 8 sections headed by prose (#333): "I FLATTER myself"
    read as a roman numeral, a wrapped "Louis\\nXIV." as a heading, numbered paragraphs as
    titles."""
    text = "".join(
        f"FEDERALIST No. {n}\n\nA Subject\n\n"
        "I FLATTER myself it has been clearly shown in my last number that the\n"
        "argument holds, and it continues on this wrapped line of prose here.\n\n"
        "I. The qualifications proposed for senators, as distinguished from\n"
        "those of representatives, consist in a more advanced age and so on.\n\n"
        "the most persevering and implacable of the opponents of Louis\nXIV.\n\n"
        f"{_PROSE}\n\n"
        for n in range(1, 5)
    )
    sections = _parse_text(tmp_path, text)

    assert [s.heading for s in sections] == [f"FEDERALIST No. {n} — A Subject" for n in range(1, 5)]


def test_a_sentence_is_never_a_heading(tmp_path):
    """Meditations: "part one to another." and "the first book of his _Meditations_, and
    shows" open on lower case; numbered paragraphs run on to the next line."""
    text = "".join(
        f"THE {o} BOOK\n\nI. Of my grandfather Verus I have learned to be gentle and meek, and to\n"
        "refrain from all anger and passion, which is the way of a good man.\n\n"
        "the first book of his _Meditations_, and shows how he could retire within\n"
        f"himself.\n\n{_PROSE}\n\npart one to another.\n\n{_PROSE}\n\n"
        for o in ("FIRST", "SECOND")
    )
    sections = _parse_text(tmp_path, text)

    assert [s.heading for s in sections] == ["THE FIRST BOOK", "THE SECOND BOOK"]


def test_frankenstein_opens_on_its_letters():
    """#332 on the real file: the Letters were stored after Chapter 24, under its name."""
    path = _book("frankenstein.txt")
    sections = bp.parse(path, "txt").sections

    assert [s.heading.split(" — ")[0] for s in sections[:5]] == [
        "Letter 1",
        "Letter 2",
        "Letter 3",
        "Letter 4",
        "Chapter 1",
    ]
    assert "St. Petersburgh" in sections[0].text
    assert "St. Petersburgh" not in sections[-1].text
    assert _in_reading_order(sections, path.read_text(encoding="utf-8"))


_HAUNTED_PALACE = [
    "In the greenest of our valleys,\nBy good angels tenanted,\nOnce a fair and stately palace",
    "Banners yellow, glorious, golden,\nOn its roof did float and flow;\n(This, all this, was",
    "Wanderers in that happy valley\nThrough two luminous windows saw\nSpirits moving musically",
    "And all with pearl and ruby glowing\nWas the fair palace door,\nThrough which came flowing",
    "But evil things, in robes of sorrow,\nAssailed the monarch's high estate;\n(Ah, let us mourn",
    "And travellers now within that valley,\nThrough the red-litten windows, see\nVast forms",
]


@pytest.mark.parametrize("indent", ["", "     "])
def test_a_numbered_poem_inside_a_story_is_not_its_chapters(tmp_path, indent):
    """Usher's "Haunted Palace" stanzas, I. to VI., were stored as the story's six sections,
    the opening under "I — In the greenest of our valleys," (#357)."""
    prose = "\n\n".join(f"Paragraph {i}. {_PROSE}" for i in range(110))
    poem = "\n\n".join(
        f"{indent}{n}.\n\n" + "\n".join(indent + line for line in stanza.splitlines())
        for n, stanza in zip(("I", "II", "III", "IV", "V", "VI"), _HAUNTED_PALACE, strict=True)
    )
    f = tmp_path / "usher.txt"
    f.write_text(f"{prose}\n\n{poem}\n\n{prose[:7000]}\n")

    sections = DocumentParser().parse(f, "txt").sections

    assert {s.heading for s in sections} == {""}
    assert "In the greenest of our valleys" in "\n".join(s.text for s in sections)


def test_speaker_label_is_not_a_subtitle(tmp_path):
    """A dialogue's first speaker name runs straight into the speech; a subtitle is set apart.

    The Gita was headed "CHAPTER V — Arjuna." for a chapter Krishna speaks, and cards
    credited Krishna's words to Arjuna.
    """
    speech = "Yet, Krishna! at the one time thou dost laud\nSurcease of works, and service too."
    text = "\n\n".join(
        f"CHAPTER {n}\n\n  {speaker}\n  {speech}"
        for n, speaker in (("I", "Dhritirashtra:"), ("II", "Arjuna."), ("III", "Krishna.[FN#l6]"))
    )
    f = tmp_path / "dialogue.txt"
    f.write_text(text)

    result = bp.parse(f, "txt")
    assert result is not None
    assert [s.heading for s in result.sections] == ["CHAPTER I", "CHAPTER II", "CHAPTER III"]
    assert result.sections[1].text.startswith("Arjuna.")


def test_full_stop_subtitle_set_apart_survives(tmp_path):
    text = "\n\n".join(
        f"CHAPTER {n}\n\n{title}\n\nCall me Ishmael, and some years ago I went to sea."
        for n, title in (("1", "Loomings."), ("2", "The Carpet-Bag."), ("3", "The Spouter-Inn."))
    )
    f = tmp_path / "subtitled.txt"
    f.write_text(text)

    result = bp.parse(f, "txt")
    assert result is not None
    assert [s.heading for s in result.sections] == [
        "CHAPTER 1 — Loomings.",
        "CHAPTER 2 — The Carpet-Bag.",
        "CHAPTER 3 — The Spouter-Inn.",
    ]
