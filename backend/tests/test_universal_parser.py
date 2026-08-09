"""
tests/test_universal_parser.py
==============================
Tests for the UniversalParser signature-driven discovery and segmentation.
"""

import textwrap
from pathlib import Path

from app.services.universal_parser import UniversalParser

up = UniversalParser()


def test_parse_book_chapters(tmp_path):
    text = textwrap.dedent("""\
        The Prologue
        
        CHAPTER I.
        THE STARTING POINT
        
        This is the first chapter body. It has some text.
        
        CHAPTER II.
        THE SECOND LEG
        
        This is the second chapter body. It also has text.
    """)
    f = tmp_path / "book.txt"
    f.write_text(text)

    result = up.parse(f, "txt")
    assert result is not None
    assert len(result.sections) == 2
    assert "CHAPTER I" in result.sections[0].heading
    assert "CHAPTER II" in result.sections[1].heading


def test_parse_tech_paper(tmp_path):
    text = textwrap.dedent("""\
        1.1 Introduction
        This paper discusses universal parsing.
        
        1.2 Related Work
        Other people have tried this.
        
        2.1 Methodology
        We use signature discovery.
        
        2.2 Results
        It works very well.
    """)
    f = tmp_path / "paper.txt"
    f.write_text(text)

    result = up.parse(f, "txt")
    assert result is not None
    assert len(result.sections) == 4
    assert result.sections[0].heading == "1.1 Introduction"
    assert result.sections[2].heading == "2.1 Methodology"


def test_parse_movie_script(tmp_path):
    text = textwrap.dedent("""\
        FADE IN:
        
        INT. COFFEE SHOP - DAY
        
        ALICE and BOB sit at a table.
        
        ALICE
        Did you see the new parser?
        
        EXT. STREET - LATER
        
        Bob walks down the street alone.
    """)
    f = tmp_path / "script.txt"
    f.write_text(text)

    result = up.parse(f, "txt")
    assert result is not None
    # Scene headers should be detected
    scene_headings = [s.heading for s in result.sections]
    assert any("INT. COFFEE SHOP" in h for h in scene_headings)
    assert any("EXT. STREET" in h for h in scene_headings)


def test_parse_conversation(tmp_path):
    # A long conversation should be grouped
    lines = []
    for i in range(100):
        speaker = "Alice" if i % 2 == 0 else "Bob"
        lines.append(f"{speaker}: This is message {i}.")

    text = "\n".join(lines)
    f = tmp_path / "chat.txt"
    f.write_text(text)

    result = up.parse(f, "txt")
    assert result is not None
    # 100 messages / 30 = 4 sections (3*30 + 10)
    assert len(result.sections) == 4
    # A transcript has no authored section titles. The label this used to
    # synthesise ("Transcript Part 2: Carol") named whichever speaker opened the
    # group, and the reader drew it as a heading over their turn (I-30).
    assert all(s.heading == "" for s in result.sections)
    assert "message 0" in result.sections[0].text
    assert "message 99" in result.sections[-1].text
    assert result.structure_type == "chat"


def test_parse_real_conversation_fixture():
    fixture_path = (
        Path(__file__).parents[1] / "tests" / "fixtures" / "full" / "conversation_sample.txt"
    )
    if not fixture_path.exists():
        import pytest

        pytest.skip("conversation_sample.txt not found")

    result = up.parse(fixture_path, "txt")
    assert result is not None
    # ~47-turn transcript: must be grouped, NOT split into one
    # "Speaker: utterance" heading per line. The ungrouped path stranded each
    # utterance in a heading and left the body "(Empty Section)", losing ~98%
    # of the content -- regression guard for that bug.
    assert len(result.sections) <= 3
    assert all(s.heading == "" for s in result.sections)
    assert not any("(Empty Section)" in s.text for s in result.sections)
    # utterances live in section BODIES now, so the content is retrievable
    assert any("Alice:" in s.text for s in result.sections)
    assert any("Bob:" in s.text for s in result.sections)
    # substantially all of the source survives into section text
    src_len = len(fixture_path.read_text())
    assert sum(len(s.text) for s in result.sections) >= 0.9 * src_len


def test_no_signature_returns_none(tmp_path):
    text = "This is just some random text.\nIt has no structure.\nNo chapters here."
    f = tmp_path / "flat.txt"
    f.write_text(text)

    result = up.parse(f, "txt")
    assert result is None


def test_parse_book_gatsby_style(tmp_path):
    # Gatsby uses centered Roman numerals (represented here by leading spaces)
    text = textwrap.dedent("""\
        The Great Gatsby
        
                I
        
        In my younger and more vulnerable years...
        
                II
        
        About half-way between West Egg and New York...
        
                III
        
        There was music from my neighbor's house...
    """)
    f = tmp_path / "gatsby.txt"
    f.write_text(text)

    result = up.parse(f, "txt")
    assert result is not None
    assert len(result.sections) == 3
    assert "I" in result.sections[0].heading
    assert "II" in result.sections[1].heading


def test_parse_book_ordinals_and_separators(tmp_path):
    text = textwrap.dedent("""\
        The Narrative
        
        CHAPTER FIRST
        The story begins.
        
        Section: 2
        The story continues with separators.
        
        BOOK - III
        The third part.
    """)
    f = tmp_path / "ordinals.txt"
    f.write_text(text)

    result = up.parse(f, "txt")
    assert result is not None
    assert len(result.sections) == 3
    assert "CHAPTER FIRST" in result.sections[0].heading
    assert "Section: 2" in result.sections[1].heading
    assert "BOOK - III" in result.sections[2].heading


# Phase 2: a heading is a label the source authored, never invented text (I-30).


def test_short_transcript_groups_rather_than_stranding_turns(tmp_path):
    """Turn count is not a reason to fall back into the heading-per-line loop.

    Four turns used to produce four sections whose heading was the utterance
    and whose body was the literal string "(Empty Section)".
    """
    text = (
        "Alice: Can we ship the reader fix this week?\n"
        "Bob: The schema change landed, so yes.\n"
        "Carol: I will re-ingest the corpus tonight.\n"
        "Alice: Good, let us review on Friday.\n"
    )
    f = tmp_path / "short_chat.txt"
    f.write_text(text)

    sig = up._discover_signature(text)
    sections = up._segment(text, sig)

    assert len(sections) == 1
    assert sections[0].heading == ""
    for utterance in ("Can we ship", "schema change landed", "re-ingest the corpus"):
        assert utterance in sections[0].text


def test_placeholder_text_never_reaches_a_section_body(tmp_path):
    """Empty twins are dropped, not filled with "(Empty Section)".

    A document's own contents page matches the same signature as its chapter
    openings, so every chapter is found twice -- once with nothing under it.
    """
    text = (
        "CHAPTER I\nCHAPTER II\nCHAPTER III\n\n"  # contents page
        "CHAPTER I\nThe first chapter opens here with real prose.\n\n"
        "CHAPTER II\nThe second chapter continues the story at length.\n\n"
        "CHAPTER III\nThe third chapter brings matters to a close.\n"
    )
    f = tmp_path / "twins.txt"
    f.write_text(text)

    sig = up._discover_signature(text)
    sections = up._segment(text, sig)

    assert [s.heading for s in sections] == ["CHAPTER I", "CHAPTER II", "CHAPTER III"]
    assert all(s.text.strip() for s in sections)
    joined = " ".join(s.text for s in sections)
    assert "(Empty Section)" not in joined
    assert "(End of Document)" not in joined


def test_bodyless_document_keeps_its_sections(tmp_path):
    """Dropping empties must not empty the document -- a deck of bare headings
    is still worth navigating."""
    from app.services.universal_parser import _drop_bodyless
    from app.types import Section

    only_headings = [
        Section(heading="CHAPTER I", level=1, text="", page_start=0, page_end=0),
        Section(heading="CHAPTER II", level=1, text="", page_start=0, page_end=0),
    ]
    assert _drop_bodyless(only_headings) == only_headings


def test_marker_recognises_numbered_chapter_openings():
    """Terminal punctuation alone does not make a line prose: "BOOK I." is a
    marker, a nine-word sentence ending in "?" is not."""
    from app.services.universal_parser import _is_marker

    assert _is_marker("BOOK I.")
    assert _is_marker("CHAPTER IV.")
    assert _is_marker("3.2 Consistency and Consensus")
    assert _is_marker("Abstract")
    assert not _is_marker("Alice: Can we ship the reader fix this week?")
    assert not _is_marker("Bob: The schema change landed, so yes.")
    assert not _is_marker("x" * 200)


def test_structure_type_is_surfaced_for_each_layout(tmp_path):
    script = tmp_path / "s.txt"
    script.write_text(
        "\n\n".join(
            f"INT. LOCATION {i} - DAY\n\nA character crosses the room and speaks at length."
            for i in range(6)
        )
    )
    assert up.parse(script, "txt").structure_type == "script"

    paper = tmp_path / "p.txt"
    paper.write_text(
        "\n\n".join(
            f"{i}.1 Section Title\n\nBody prose for this subsection runs on for a while."
            for i in range(1, 7)
        )
    )
    assert up.parse(paper, "txt").structure_type == "paper"
