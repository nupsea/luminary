"""Unit tests for prerequisite_detector.detect_prerequisites.

All tests are pure (no DB, no ML, no I/O).
"""

import pytest

from app.services.prerequisite_detector import detect_prerequisites


def _chunk(text: str) -> dict:
    return {"text": text, "chunk_id": "c1"}


# ---------------------------------------------------------------------------
# Basic detection
# ---------------------------------------------------------------------------


def test_requires_understanding_of_returns_high_confidence():
    chunks = [_chunk("Natural Selection requires understanding of Variation")]
    result = detect_prerequisites(chunks, {"natural selection", "variation"})
    assert len(result) == 1
    dep, pre, conf = result[0]
    assert dep == "natural selection"
    assert pre == "variation"
    assert conf == pytest.approx(0.9)


def test_requires_without_understanding_of():
    chunks = [_chunk("Photosynthesis requires sunlight")]
    result = detect_prerequisites(chunks, {"photosynthesis", "sunlight"})
    assert any(r[0] == "photosynthesis" and r[1] == "sunlight" for r in result)


def test_builds_on_returns_medium_confidence():
    chunks = [_chunk("Calculus builds on Algebra")]
    result = detect_prerequisites(chunks, {"calculus", "algebra"})
    assert len(result) == 1
    dep, pre, conf = result[0]
    assert dep == "calculus"
    assert pre == "algebra"
    assert conf == pytest.approx(0.7)


def test_is_a_subclass_of_returns_high_confidence():
    chunks = [_chunk("Mammal is a subclass of Animal")]
    result = detect_prerequisites(chunks, {"mammal", "animal"})
    assert len(result) == 1
    _, _, conf = result[0]
    assert conf == pytest.approx(0.9)


def test_depends_on_returns_medium_confidence():
    chunks = [_chunk("Gravity depends on Mass")]
    result = detect_prerequisites(chunks, {"gravity", "mass"})
    assert len(result) == 1
    _, _, conf = result[0]
    assert conf == pytest.approx(0.7)


def test_defined_as_a_type_of():
    chunks = [_chunk("A dog is defined as a type of Mammal")]
    result = detect_prerequisites(chunks, {"a dog", "mammal"})
    assert len(result) == 1


def test_first_introduced_as_returns_low_confidence():
    chunks = [_chunk("Gravity was first introduced as Force")]
    result = detect_prerequisites(chunks, {"gravity", "force"})
    assert len(result) == 1
    _, _, conf = result[0]
    assert conf == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Entity guard
# ---------------------------------------------------------------------------


def test_entity_not_in_known_returns_empty():
    """Neither name is in entity_names -> empty result."""
    chunks = [_chunk("Natural Selection requires understanding of Variation")]
    result = detect_prerequisites(chunks, set())
    assert result == []


def test_only_dep_in_known_returns_empty():
    chunks = [_chunk("Natural Selection requires understanding of Variation")]
    result = detect_prerequisites(chunks, {"natural selection"})
    assert result == []


def test_only_prereq_in_known_returns_empty():
    chunks = [_chunk("Natural Selection requires understanding of Variation")]
    result = detect_prerequisites(chunks, {"variation"})
    assert result == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_duplicate_pairs_keep_highest_confidence():
    """Same pair in two chunks with different markers -> highest confidence kept."""
    chunks = [
        _chunk("Calculus requires understanding of Algebra"),  # confidence 0.9
        _chunk("Calculus builds on Algebra"),                  # confidence 0.7
    ]
    result = detect_prerequisites(chunks, {"calculus", "algebra"})
    assert len(result) == 1
    dep, pre, conf = result[0]
    assert dep == "calculus"
    assert pre == "algebra"
    assert conf == pytest.approx(0.9)


def test_empty_chunks_returns_empty():
    result = detect_prerequisites([], {"natural selection", "variation"})
    assert result == []


def test_empty_entity_names_returns_empty():
    chunks = [_chunk("Natural Selection requires understanding of Variation")]
    result = detect_prerequisites(chunks, set())
    assert result == []


def test_self_reference_not_returned():
    """dep == prereq after cleaning -> not returned."""
    chunks = [_chunk("Variation requires understanding of Variation")]
    result = detect_prerequisites(chunks, {"variation"})
    assert result == []


# ---------------------------------------------------------------------------
# Multiple matches in one chunk
# ---------------------------------------------------------------------------


def test_multiple_matches_in_one_chunk():
    text = "Calculus builds on Algebra. Algebra builds on Arithmetic."
    chunks = [_chunk(text)]
    result = detect_prerequisites(chunks, {"calculus", "algebra", "arithmetic"})
    pairs = {(r[0], r[1]) for r in result}
    assert ("calculus", "algebra") in pairs
    assert ("algebra", "arithmetic") in pairs
