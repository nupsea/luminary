"""Tests for cross-domain golden dataset activation (S223)."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_cross_domain_data_fixtures_exist():
    assert (REPO_ROOT / "DATA/papers/art_of_unix.txt").exists()
    assert (REPO_ROOT / "DATA/conversations/engineering_sync.txt").exists()
    assert (REPO_ROOT / "DATA/notes/ml_notes.txt").exists()
    assert (REPO_ROOT / "DATA/code/embedder.py").exists()


def test_cross_domain_goldens_reference_existing_source_files():
    for dataset in ("paper", "conversation", "notes", "code"):
        path = REPO_ROOT / "evals" / "golden" / f"{dataset}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        assert rows
        for row in rows:
            assert (REPO_ROOT / row["source_file"]).exists(), row["source_file"]
