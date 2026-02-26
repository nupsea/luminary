"""Corpus fixture tests — verifies all three canonical books and manifest schema.

These tests confirm that:
  - Each book file exists at its expected path relative to the repo root.
  - Each file meets the minimum word count defined in manifest.json (no truncation).
  - manifest.json is valid JSON and each entry contains all required fields.

Tests run without network access; all files must already be present
(use ``scripts/corpus/setup_books.sh`` to populate them first).
"""

import json
from pathlib import Path

import pytest

# Navigate from backend/tests/ → repo root
REPO_ROOT = Path(__file__).parent.parent.parent
BOOKS_DIR = REPO_ROOT / "DATA" / "books"
MANIFEST_PATH = BOOKS_DIR / "manifest.json"

REQUIRED_MANIFEST_FIELDS = {
    "name",
    "filepath",
    "gutenberg_id",
    "word_count_min",
    "ingest_time_budget_seconds",
    "thresholds",
    "known_entities",
    "known_keywords",
    "known_co_occurrences",
    "semantic_queries",
}

REQUIRED_THRESHOLD_FIELDS = {
    "chunk_count_min",
    "fts_count_min",
    "vector_count_min",
    "entity_count_min",
    "edge_count_min",
}


# ── manifest ──────────────────────────────────────────────────────────────────

def test_manifest_parses_and_has_required_fields() -> None:
    """manifest.json must parse and each entry must have all required fields."""
    assert MANIFEST_PATH.exists(), f"manifest.json not found at {MANIFEST_PATH}"
    entries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(entries, list), "manifest.json must be a JSON array"
    assert len(entries) == 3, f"Expected 3 books, got {len(entries)}"

    for entry in entries:
        missing = REQUIRED_MANIFEST_FIELDS - set(entry.keys())
        assert not missing, (
            f"Book '{entry.get('name', '?')}' is missing fields: {missing}"
        )
        missing_thresh = REQUIRED_THRESHOLD_FIELDS - set(entry["thresholds"].keys())
        assert not missing_thresh, (
            f"Book '{entry['name']}' thresholds missing: {missing_thresh}"
        )
        assert isinstance(entry["known_entities"], list) and entry["known_entities"], (
            f"Book '{entry['name']}' must have non-empty known_entities"
        )
        assert isinstance(entry["known_keywords"], list) and entry["known_keywords"], (
            f"Book '{entry['name']}' must have non-empty known_keywords"
        )
        assert isinstance(entry["known_co_occurrences"], list), (
            f"Book '{entry['name']}' known_co_occurrences must be a list"
        )
        queries = entry["semantic_queries"]
        assert isinstance(queries, list) and len(queries) >= 2, (
            f"Book '{entry['name']}' must have at least 2 semantic_queries"
        )
        for sq in queries:
            assert "query" in sq and "expected_keyword" in sq, (
                f"Book '{entry['name']}' semantic_query missing query/expected_keyword: {sq}"
            )
        assert isinstance(entry["ingest_time_budget_seconds"], int), (
            f"Book '{entry['name']}' ingest_time_budget_seconds must be int"
        )


# ── per-book word count tests ─────────────────────────────────────────────────

def _load_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _word_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").split())


@pytest.mark.parametrize("book_name,expected_min", [
    ("The Time Machine", 30000),
    ("Alice in Wonderland", 25000),
    ("The Odyssey", 100000),
])
def test_book_word_count(book_name: str, expected_min: int) -> None:
    """Each book file must exist and meet its minimum word count."""
    manifest = _load_manifest()
    entry = next((e for e in manifest if e["name"] == book_name), None)
    assert entry is not None, f"No manifest entry for '{book_name}'"

    filepath = REPO_ROOT / entry["filepath"]
    assert filepath.exists(), (
        f"Book file not found: {filepath}\n"
        f"Run: ./scripts/corpus/setup_books.sh"
    )

    count = _word_count(filepath)
    assert count >= expected_min, (
        f"'{book_name}' has {count} words, minimum is {expected_min}. "
        f"File may be truncated. Run: ./scripts/corpus/setup_books.sh"
    )
