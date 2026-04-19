"""Unit tests for app.services.tech_section_parser — pure functions only.

All tests are synchronous (no DB, no I/O).
"""

from app.services.tech_section_parser import (
    assign_parent_headings_dicts,
    classify_section_level,
    detect_admonition,
    is_objective_candidate,
)

# ---------------------------------------------------------------------------
# AC1: Numbered hierarchy levels and parent chain
# ---------------------------------------------------------------------------


def test_classify_section_level_part():
    assert classify_section_level("Part I Introduction") == 1
    assert classify_section_level("Part 1 Basics") == 1


def test_classify_section_level_chapter():
    assert classify_section_level("Chapter 1 Getting Started") == 2
    assert classify_section_level("chapter 12 Advanced Topics") == 2


def test_classify_section_level_nm():
    assert classify_section_level("1.1 Overview") == 3
    assert classify_section_level("2.3 Advanced Patterns") == 3


def test_classify_section_level_nmp():
    assert classify_section_level("1.1.1 Detail") == 4
    assert classify_section_level("3.2.1 Sub-sub-section") == 4


def test_classify_section_level_default():
    # Headings that match no pattern → level 2
    assert classify_section_level("Introduction") == 2
    assert classify_section_level("") == 2


def test_numbered_hierarchy_levels_and_parent_chain():
    sections = [
        {"heading": "Part I Introduction", "text": "Part text"},
        {"heading": "Chapter 1 Getting Started", "text": "Chapter text"},
        {"heading": "1.1 Overview", "text": "Section text"},
        {"heading": "1.1.1 Detail", "text": "Subsection text"},
    ]
    result = assign_parent_headings_dicts(sections)

    assert result[0]["level"] == 1
    assert result[1]["level"] == 2
    assert result[2]["level"] == 3
    assert result[3]["level"] == 4

    assert result[0]["parent_heading"] is None
    assert result[1]["parent_heading"] == "Part I Introduction"
    assert result[2]["parent_heading"] == "Chapter 1 Getting Started"
    assert result[3]["parent_heading"] == "1.1 Overview"


def test_assign_parent_headings_dicts_no_part():
    """When there is no Part, chapter parent_heading is None."""
    sections = [
        {"heading": "Chapter 1 Basics", "text": "..."},
        {"heading": "1.1 Intro", "text": "..."},
    ]
    result = assign_parent_headings_dicts(sections)
    assert result[0]["parent_heading"] is None
    assert result[1]["parent_heading"] == "Chapter 1 Basics"


def test_assign_parent_headings_dicts_resets_deeper_on_new_part():
    """A new Part resets Chapter and below parent references."""
    sections = [
        {"heading": "Part I", "text": ""},
        {"heading": "Chapter 1 A", "text": ""},
        {"heading": "1.1 A", "text": ""},
        {"heading": "Part II", "text": ""},
        {"heading": "Chapter 2 B", "text": ""},
    ]
    result = assign_parent_headings_dicts(sections)
    assert result[4]["parent_heading"] == "Part II"


# ---------------------------------------------------------------------------
# AC2 + AC3: Admonition detection
# ---------------------------------------------------------------------------


def test_detect_admonition_note_upper():
    assert detect_admonition("NOTE: Always use type hints.") == "note"


def test_detect_admonition_note_lower():
    assert detect_admonition("note: this is important") == "note"


def test_detect_admonition_warning_upper():
    assert detect_admonition("WARNING: Do not call this from an async context.") == "warning"


def test_detect_admonition_warning_lower():
    assert detect_admonition("warning: be careful here") == "warning"


def test_detect_admonition_tip():
    assert detect_admonition("TIP: You can also use a list comprehension.") == "tip"


def test_detect_admonition_caution():
    assert detect_admonition("CAUTION: This is irreversible.") == "caution"


def test_detect_admonition_important():
    assert detect_admonition("IMPORTANT: Read the license.") == "important"


def test_detect_admonition_markdown_blockquote():
    assert detect_admonition("> **Note**\nThis is a note.") == "note"
    assert detect_admonition("> **Warning**\nBe careful.") == "warning"


def test_detect_admonition_none_for_plain_text():
    assert detect_admonition("This is just a regular paragraph.") is None


def test_detect_admonition_ignores_deep_content():
    """Admonition marker beyond 500 chars should not match."""
    prefix = "x" * 600
    text = prefix + "\nNOTE: this should not match"
    assert detect_admonition(text) is None


# ---------------------------------------------------------------------------
# AC4: Objective candidate detection
# ---------------------------------------------------------------------------


def test_objective_candidate_true_by_end_of():
    text = "By the end of this chapter you will understand closures and decorators."
    assert is_objective_candidate(text) is True


def test_objective_candidate_true_you_will():
    text = "In this section, you will learn how to configure the settings."
    assert is_objective_candidate(text) is True


def test_objective_candidate_true_learning_objectives():
    text = "Learning objectives:\n- Understand the basics\n- Apply the concepts"
    assert is_objective_candidate(text) is True


def test_objective_candidate_false():
    text = "This section covers the theory of computation and formal languages."
    assert is_objective_candidate(text) is False


def test_objective_candidate_checks_only_first_300_chars():
    """Phrase beyond 300 chars should not make it a candidate."""
    prefix = "a" * 400
    text = prefix + " by the end of this chapter you will understand"
    assert is_objective_candidate(text) is False
