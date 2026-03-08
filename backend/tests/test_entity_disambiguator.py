"""Unit tests for entity_disambiguator.

Tests are pure Python — no DB, no fixtures, no async.
"""

from app.services.entity_disambiguator import (
    _HONORIFICS,
    canonicalize_batch,
    find_canonical,
)


def test_honorific_stripped_resolves_to_existing():
    """'Mr. Holmes' strips to 'holmes', which is a substring of 'sherlock holmes'."""
    existing = ["sherlock holmes"]
    result = find_canonical("mr. holmes", "PERSON", existing)
    # Rule B: "holmes" in "sherlock holmes" -> longer wins -> "sherlock holmes"
    assert result == "sherlock holmes"


def test_direct_substring():
    """'holmes' is a direct substring of 'sherlock holmes'; longer name wins."""
    existing = ["sherlock holmes"]
    result = find_canonical("holmes", "PERSON", existing)
    assert result == "sherlock holmes"


def test_sr_not_in_honorifics():
    """'sr' must NOT be in _HONORIFICS; 'Sr. Holmes' must NOT resolve to 'Sherlock Holmes'."""
    assert "sr" not in _HONORIFICS

    existing = ["sherlock holmes"]
    result = find_canonical("sr. holmes", "PERSON", existing)
    # "sr" is not stripped -> stripped form is "sr. holmes"
    # Rule A: "sr. holmes" != "sherlock holmes" — no match
    # Rule B: "sr. holmes" not a substring of "sherlock holmes" — no match
    # Rule C: tokens {"sr.", "holmes"} & {"sherlock", "holmes"} = {"holmes"} -> 1 < 2 — no match
    assert result == "sr. holmes"


def test_canonicalize_batch_deduplicates_variants():
    """All three variants of Holmes collapse to 'sherlock holmes'."""
    entities = [
        ("sherlock holmes", "PERSON"),
        ("holmes", "PERSON"),
        ("mr. holmes", "PERSON"),
    ]
    triples = canonicalize_batch(entities, {})
    canonical_names = [t[0] for t in triples]
    assert all(name == "sherlock holmes" for name in canonical_names)


def test_entity_type_boundary():
    """Entities of different types must never merge, even if names are identical."""
    entities = [
        ("london", "PLACE"),
        ("london", "PERSON"),
    ]
    triples = canonicalize_batch(entities, {})
    assert triples[0][0] == "london"
    assert triples[0][1] == "PLACE"
    assert triples[1][0] == "london"
    assert triples[1][1] == "PERSON"
