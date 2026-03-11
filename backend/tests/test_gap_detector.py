"""Tests for S94: Notes vs Book gap detection.

Test plan:
  1. test_detect_gaps_no_notes_found -- unit: ValueError when no notes match IDs
  2. test_detect_gaps_malformed_llm -- unit: malformed JSON returns fallback GapReport
  3. test_detect_gaps_returns_report -- integration: notes + mocked LLM -> gaps/covered
  4. test_gap_detect_endpoint_422_empty -- API: POST /notes/gap-detect with empty note_ids
  5. test_gap_detect_endpoint_404_no_notes -- API: note_ids that don't exist -> 404
  6. test_alice_gap_detection_slow -- slow: real notes + Alice in Wonderland -> report
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.gap_detector import _extract_json

pytest_plugins = ["conftest_books"]


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_extract_json_clean():
    raw = '{"gaps": ["missing concept"], "covered": ["found one"]}'
    result = _extract_json(raw)
    assert result["gaps"] == ["missing concept"]
    assert result["covered"] == ["found one"]


def test_extract_json_with_fence():
    raw = '```json\n{"gaps": ["g1"], "covered": []}\n```'
    result = _extract_json(raw)
    assert result["gaps"] == ["g1"]


def test_extract_json_malformed_returns_empty():
    result = _extract_json("This is not JSON at all.")
    assert result == {}


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_gap_detect_endpoint_422_empty(client):
    """POST /notes/gap-detect with empty note_ids returns 422."""
    resp = client.post(
        "/notes/gap-detect",
        json={"note_ids": [], "document_id": "fake-doc-id"},
    )
    assert resp.status_code == 422


def test_gap_detect_endpoint_404_no_notes(client):
    """POST /notes/gap-detect with nonexistent note IDs returns 404."""
    resp = client.post(
        "/notes/gap-detect",
        json={"note_ids": ["nonexistent-id-1", "nonexistent-id-2"], "document_id": "x"},
    )
    assert resp.status_code == 404


def test_detect_gaps_returns_report(client):
    """Create a note, mock LLM, call gap-detect, assert gaps and covered present."""
    create = client.post(
        "/notes",
        json={"content": "Alice follows the White Rabbit into Wonderland", "tags": []},
    )
    assert create.status_code == 201
    note_id = create.json()["id"]

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = (
        '{"gaps": ["Cheshire Cat invisibility"], "covered": ["Alice and White Rabbit"]}'
    )

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[])

    with patch("app.services.gap_detector.litellm.acompletion", AsyncMock(return_value=mock_resp)):
        with patch("app.services.retriever.get_retriever", return_value=mock_retriever):
            resp = client.post(
                "/notes/gap-detect",
                json={"note_ids": [note_id], "document_id": "fake-doc"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "gaps" in data
    assert "covered" in data
    assert "query_used" in data
    assert data["gaps"] == ["Cheshire Cat invisibility"]
    assert data["covered"] == ["Alice and White Rabbit"]


def test_detect_gaps_malformed_llm(client):
    """When LLM returns non-JSON, returns fallback GapReport with error message."""
    create = client.post("/notes", json={"content": "Some note content", "tags": []})
    assert create.status_code == 201
    note_id = create.json()["id"]

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "Sorry I cannot help with that."

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[])

    with patch("app.services.gap_detector.litellm.acompletion", AsyncMock(return_value=mock_resp)):
        with patch("app.services.retriever.get_retriever", return_value=mock_retriever):
            resp = client.post(
                "/notes/gap-detect",
                json={"note_ids": [note_id], "document_id": "fake-doc"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["gaps"]) == 1
    assert "unavailable" in data["gaps"][0].lower()
    assert data["covered"] == []


# ---------------------------------------------------------------------------
# Slow integration test
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_alice_gap_detection_slow(all_books_ingested):
    """Create Alice notes, run gap detection against Alice book, assert report returned."""
    with TestClient(app) as c:
        # Get Alice document ID
        docs_resp = c.get("/documents?page_size=100")
        assert docs_resp.status_code == 200
        items = docs_resp.json().get("items", [])
        alice_docs = [d for d in items if "alice" in d["title"].lower()]
        if not alice_docs:
            pytest.skip("Alice in Wonderland not ingested")
        alice_doc_id = alice_docs[0]["id"]

        # Create notes about Alice
        note_ids = []
        for content in [
            "Alice fell down a rabbit hole and met the White Rabbit",
            "The Mad Hatter hosted an unbirthday tea party",
        ]:
            r = c.post("/notes", json={"content": content, "tags": []})
            assert r.status_code == 201
            note_ids.append(r.json()["id"])

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = (
            '{"gaps": ["Queen of Hearts"], "covered": ["White Rabbit", "Mad Hatter"]}'
        )

        with patch(
            "app.services.gap_detector.litellm.acompletion",
            AsyncMock(return_value=mock_resp),
        ):
            resp = c.post(
                "/notes/gap-detect",
                json={"note_ids": note_ids, "document_id": alice_doc_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "gaps" in data
        assert "covered" in data
        assert isinstance(data["gaps"], list)
        assert isinstance(data["covered"], list)
