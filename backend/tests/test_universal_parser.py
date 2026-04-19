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
    assert "Transcript Part 1" in result.sections[0].heading
    assert "message 0" in result.sections[0].text
    assert "message 99" in result.sections[-1].text


def test_parse_real_conversation_fixture():
    fixture_path = (
        Path(__file__).parents[1] / "tests" / "fixtures" / "full" / "conversation_sample.txt"
    )
    if not fixture_path.exists():
        import pytest

        pytest.skip("conversation_sample.txt not found")

    result = up.parse(fixture_path, "txt")
    assert result is not None
    # Check for speaker detection in headings (UniversalParser chat mode)
    # The fixture is short (< 50 matches), so it won't be grouped.
    # Actually, it's about 40 turns. Let's see.
    assert len(result.sections) > 10
    assert any("Alice:" in s.heading for s in result.sections)
    assert any("Bob:" in s.heading for s in result.sections)


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
