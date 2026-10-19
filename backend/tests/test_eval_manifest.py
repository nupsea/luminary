"""The eval harness uploads its corpus the way a user's upload arrives (evals.lib.manifest)."""

import sys
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib import manifest  # noqa: E402


class _Response:
    def __init__(self, body: dict) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._body


def test_ingest_leaves_classification_to_the_pipeline(tmp_path, monkeypatch):
    (tmp_path / "paper.txt").write_text("An essay on pipes.")
    monkeypatch.setattr(manifest, "SOURCE_ROOT", tmp_path)
    monkeypatch.setattr(manifest.time, "sleep", lambda _s: None)
    posted: dict = {}

    def post(url, **kwargs):
        posted.update(kwargs)
        return _Response({"document_id": "d1"})

    def get(url, **kwargs):
        if url.endswith("/status"):
            return _Response({"stage": "complete"})
        return _Response({"content_type": "paper"})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)

    assert manifest.ingest_document("http://backend", "paper.txt") == "d1"
    # A supplied content_type is final, so any value here would skip classification.
    assert "content_type" not in (posted.get("data") or {})
