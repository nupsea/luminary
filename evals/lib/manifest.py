"""Manifest helpers: maps source_file -> document_id and ingestion plumbing."""

import json
import sys
import time
from pathlib import Path

import httpx

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden"
MANIFEST_PATH = GOLDEN_DIR / "manifest.json"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_manifest() -> dict[str, str]:
    if MANIFEST_PATH.exists():
        with MANIFEST_PATH.open() as f:
            return json.load(f)
    return {}


def save_manifest(manifest: dict[str, str]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w") as f:
        json.dump(manifest, f, indent=2)


def is_document_alive(backend_url: str, doc_id: str) -> bool:
    """Return True iff GET /documents/{doc_id}/status returns 2xx."""
    try:
        resp = httpx.get(f"{backend_url}/documents/{doc_id}/status", timeout=10.0)
        return 200 <= resp.status_code < 300
    except Exception:
        return False


def lookup_document_by_filename(backend_url: str, source_file: str) -> str | None:
    """Return document_id for an already-ingested file, or None if not found."""
    stem = Path(source_file).stem.lower()
    try:
        resp = httpx.get(
            f"{backend_url}/documents",
            params={"page_size": 100},
            timeout=15.0,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        for doc in items:
            title = (doc.get("title") or "").lower()
            if title == stem and doc.get("stage") == "complete":
                return doc["id"]
    except Exception as exc:
        print(f"  WARNING: GET /documents failed: {exc}", file=sys.stderr)
    return None


def ingest_document(backend_url: str, source_file: str) -> str | None:
    """Ingest a source file via POST /ingest and wait for completion."""
    file_path = REPO_ROOT / source_file
    if not file_path.exists():
        print(f"  ERROR: source file not found: {file_path}", file=sys.stderr)
        return None

    try:
        with file_path.open("rb") as fh:
            resp = httpx.post(
                f"{backend_url}/documents/ingest",
                data={"content_type": "book"},
                files={"file": (file_path.name, fh, "text/plain")},
                timeout=30.0,
            )
        resp.raise_for_status()
        doc_id = resp.json().get("document_id")
        if not doc_id:
            print(f"  ERROR: /ingest returned no document_id for {source_file}", file=sys.stderr)
            return None
    except Exception as exc:
        print(f"  ERROR: /ingest failed for {source_file}: {exc}", file=sys.stderr)
        return None

    print(f"  Waiting for ingestion to complete (document_id={doc_id})...")
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(5)
        try:
            status_resp = httpx.get(f"{backend_url}/documents/{doc_id}/status", timeout=10.0)
            status_resp.raise_for_status()
            stage = status_resp.json().get("stage", "")
            if stage in ["complete", "summarize", "section_summarize"]:
                print(f"  Ingestion finished enough: {source_file} -> {doc_id} (stage={stage})")
                return doc_id
            if stage == "error":
                print(f"  ERROR: ingestion failed for {source_file}", file=sys.stderr)
                return None
            print(f"    stage={stage}...")
        except Exception as exc:
            print(f"  WARNING: status check failed: {exc}", file=sys.stderr)

    print(f"  ERROR: ingestion timed out for {source_file}", file=sys.stderr)
    return None


def ensure_ingested(backend_url: str, source_file: str, manifest: dict[str, str]) -> str | None:
    """Return the document_id for source_file, ingesting if not yet in manifest."""
    cached = manifest.get(source_file)
    if cached and is_document_alive(backend_url, cached):
        return cached
    if cached:
        print(f"  Manifest entry for {source_file} is stale ({cached}); dropping and re-resolving")
        manifest.pop(source_file, None)
        save_manifest(manifest)

    doc_id = lookup_document_by_filename(backend_url, source_file)
    if doc_id:
        print(f"  Found existing document for {source_file} -> {doc_id} (skipping re-ingest)")
        manifest[source_file] = doc_id
        save_manifest(manifest)
        return doc_id

    print(f"  Ingesting {source_file} (not yet in manifest)...")
    doc_id = ingest_document(backend_url, source_file)
    if doc_id:
        manifest[source_file] = doc_id
        save_manifest(manifest)
    return doc_id
