"""Unit tests for ensure_ingested() in evals/run_eval.py.

Verifies that when GET /documents already returns a matching document,
ensure_ingested() skips re-ingest and returns the cached document_id.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# run_eval.py lives in evals/, not the backend package; add repo root to path.
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))

import run_eval  # noqa: E402 -- must come after sys.path manipulation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_documents_response(doc_id: str, title: str, stage: str = "complete") -> MagicMock:
    """Return a fake httpx.Response for GET /documents."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "items": [{"id": doc_id, "title": title, "stage": stage}],
        "total": 1,
        "page": 1,
        "page_size": 100,
    }
    return mock_resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ensure_ingested_skips_reingest_when_document_exists(tmp_path, monkeypatch):
    """ensure_ingested() must not call ingest_document() when the document already exists."""
    monkeypatch.setattr(run_eval, "MANIFEST_PATH", tmp_path / "manifest.json")

    fake_doc_id = "doc-already-exists"
    documents_resp = _make_documents_response(fake_doc_id, "time_machine")

    ingest_called = []

    def fake_ingest(backend_url: str, source_file: str) -> str | None:
        ingest_called.append(source_file)
        return "doc-new-id"

    with patch("run_eval.ingest_document", side_effect=fake_ingest):
        with patch("httpx.get", return_value=documents_resp):
            manifest: dict = {}
            result = run_eval.ensure_ingested(
                "http://localhost:8000",
                "DATA/books/time_machine.txt",
                manifest,
            )

    assert result == fake_doc_id, "should return the existing document_id"
    assert ingest_called == [], "ingest_document must NOT be called when document exists"
    assert manifest["DATA/books/time_machine.txt"] == fake_doc_id, "manifest must be updated"
    # manifest.json must be persisted
    assert (tmp_path / "manifest.json").exists(), "manifest.json must be written"
    saved = json.loads((tmp_path / "manifest.json").read_text())
    assert saved["DATA/books/time_machine.txt"] == fake_doc_id


def test_ensure_ingested_calls_ingest_when_document_missing(tmp_path, monkeypatch):
    """ensure_ingested() must call ingest_document() when no matching document exists."""
    monkeypatch.setattr(run_eval, "MANIFEST_PATH", tmp_path / "manifest.json")

    # GET /documents returns an empty list
    empty_resp = MagicMock()
    empty_resp.raise_for_status.return_value = None
    empty_resp.json.return_value = {"items": [], "total": 0, "page": 1, "page_size": 100}

    new_doc_id = "doc-freshly-ingested"

    with patch("run_eval.ingest_document", return_value=new_doc_id) as mock_ingest:
        with patch("httpx.get", return_value=empty_resp):
            manifest: dict = {}
            result = run_eval.ensure_ingested(
                "http://localhost:8000",
                "DATA/books/time_machine.txt",
                manifest,
            )

    assert result == new_doc_id
    mock_ingest.assert_called_once_with("http://localhost:8000", "DATA/books/time_machine.txt")
    assert manifest["DATA/books/time_machine.txt"] == new_doc_id


def test_ensure_ingested_uses_manifest_cache_when_alive(tmp_path, monkeypatch):
    """ensure_ingested() must return manifest value when the cached doc_id is alive.

    S212 baseline fix: cached manifest entries are now validated via
    is_document_alive() (a single GET /documents/{id}/status). When the
    document is still present, the cached value is returned without
    re-ingesting and without calling /documents or /ingest.
    """
    monkeypatch.setattr(run_eval, "MANIFEST_PATH", tmp_path / "manifest.json")

    cached_id = "doc-from-cache"
    manifest = {"DATA/books/time_machine.txt": cached_id}

    with patch("run_eval.is_document_alive", return_value=True) as mock_alive:
        with patch("run_eval.lookup_document_by_filename") as mock_lookup:
            with patch("run_eval.ingest_document") as mock_ingest:
                result = run_eval.ensure_ingested(
                    "http://localhost:8000",
                    "DATA/books/time_machine.txt",
                    manifest,
                )

    assert result == cached_id
    mock_alive.assert_called_once_with("http://localhost:8000", cached_id)
    mock_lookup.assert_not_called()
    mock_ingest.assert_not_called()


def test_ensure_ingested_drops_stale_cache_and_falls_through(tmp_path, monkeypatch):
    """ensure_ingested() must drop a stale cached doc_id and re-resolve.

    S212 baseline fix: when the cached doc_id returns 404 on
    /documents/{id}/status, drop it from the manifest and fall through
    to lookup/ingest so the next call can resolve a live document.
    """
    monkeypatch.setattr(run_eval, "MANIFEST_PATH", tmp_path / "manifest.json")

    stale_id = "doc-stale"
    fresh_id = "doc-fresh"
    manifest = {"DATA/books/time_machine.txt": stale_id}

    with patch("run_eval.is_document_alive", return_value=False):
        with patch("run_eval.lookup_document_by_filename", return_value=fresh_id):
            with patch("run_eval.ingest_document") as mock_ingest:
                result = run_eval.ensure_ingested(
                    "http://localhost:8000",
                    "DATA/books/time_machine.txt",
                    manifest,
                )

    assert result == fresh_id
    assert manifest["DATA/books/time_machine.txt"] == fresh_id
    mock_ingest.assert_not_called()


def test_ensure_ingested_skips_incomplete_stage(tmp_path, monkeypatch):
    """ensure_ingested() must not use a document whose stage != 'complete'."""
    monkeypatch.setattr(run_eval, "MANIFEST_PATH", tmp_path / "manifest.json")

    # Document exists but is still processing
    processing_resp = _make_documents_response("doc-processing", "time_machine", stage="embed")

    new_doc_id = "doc-new-after-ingest"

    with patch("run_eval.ingest_document", return_value=new_doc_id) as mock_ingest:
        with patch("httpx.get", return_value=processing_resp):
            manifest: dict = {}
            result = run_eval.ensure_ingested(
                "http://localhost:8000",
                "DATA/books/time_machine.txt",
                manifest,
            )

    assert result == new_doc_id
    mock_ingest.assert_called_once()
