"""Tests for NoteTaggerService and _parse_tag_list.

Covers:
  - _parse_tag_list pure function: valid JSON, fenced JSON, invalid JSON, empty input
  - suggest_tags returns [] for short content
  - suggest_tags returns [] (no exception) on litellm.ServiceUnavailableError
  - POST /notes/{note_id}/suggest-tags returns 200 for existing note
  - POST /notes/nonexistent-id/suggest-tags returns 404
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.note_tagger import NoteTaggerService, _parse_tag_list

# ---------------------------------------------------------------------------
# _parse_tag_list pure function tests
# ---------------------------------------------------------------------------


def test_parse_tag_list_valid_json():
    result = _parse_tag_list('["python", "machine learning", "nlp"]')
    assert result == ["python", "machine learning", "nlp"]


def test_parse_tag_list_fenced_json():
    raw = '```json\n["ai", "notes"]\n```'
    result = _parse_tag_list(raw)
    assert result == ["ai", "notes"]


def test_parse_tag_list_invalid_json():
    result = _parse_tag_list("not json at all")
    assert result == []


def test_parse_tag_list_empty_input():
    assert _parse_tag_list("") == []


def test_parse_tag_list_caps_at_five():
    raw = '["a", "b", "c", "d", "e", "f", "g"]'
    result = _parse_tag_list(raw)
    assert len(result) == 5


def test_parse_tag_list_lowercases():
    result = _parse_tag_list('["Python", "ML"]')
    assert result == ["python", "ml"]


def test_parse_tag_list_array_inside_prose():
    raw = 'Here are your tags: ["history", "science"]'
    result = _parse_tag_list(raw)
    assert result == ["history", "science"]


# ---------------------------------------------------------------------------
# NoteTaggerService.suggest_tags unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_tags_short_content():
    svc = NoteTaggerService()
    result = await svc.suggest_tags("hi")
    assert result == []


@pytest.mark.asyncio
async def test_suggest_tags_short_content_boundary():
    svc = NoteTaggerService()
    # exactly 19 chars -- below 20 threshold
    result = await svc.suggest_tags("a" * 19)
    assert result == []


@pytest.mark.asyncio
async def test_suggest_tags_service_unavailable():
    import litellm

    svc = NoteTaggerService()
    with patch(
        "litellm.acompletion",
        new=AsyncMock(
            side_effect=litellm.ServiceUnavailableError(
                message="Ollama unreachable", llm_provider="ollama", model="mistral"
            )
        ),
    ):
        result = await svc.suggest_tags("a" * 30)
    assert result == []


@pytest.mark.asyncio
async def test_suggest_tags_returns_list():
    svc = NoteTaggerService()
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = '["history", "time travel"]'

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await svc.suggest_tags("a" * 30)

    assert result == ["history", "time travel"]


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_suggest_tags_endpoint_not_found(client):
    resp = client.post("/notes/nonexistent-id/suggest-tags")
    assert resp.status_code == 404


def test_suggest_tags_endpoint_existing_note(client):
    # Create a note with short content (5 chars) -- returns [] without calling LLM
    create = client.post("/notes", json={"content": "a" * 5, "tags": []})
    assert create.status_code == 201
    note_id = create.json()["id"]

    resp = client.post(f"/notes/{note_id}/suggest-tags")
    assert resp.status_code == 200
    data = resp.json()
    assert "tags" in data
    assert isinstance(data["tags"], list)


def test_suggest_tags_endpoint_200_for_long_content(client):
    # Create a note with long content
    create = client.post("/notes", json={"content": "x" * 25, "tags": []})
    note_id = create.json()["id"]

    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = '["reading", "notes"]'

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        resp = client.post(f"/notes/{note_id}/suggest-tags")

    assert resp.status_code == 200
    data = resp.json()
    assert data["tags"] == ["reading", "notes"]


def test_suggest_tags_api_returns_empty_not_503(client):
    """Offline Ollama path: suggest-tags endpoint returns HTTP 200 with tags=[], not 503."""
    create = client.post("/notes", json={"content": "x" * 25, "tags": []})
    assert create.status_code == 201
    note_id = create.json()["id"]

    mock_tagger = MagicMock()
    mock_tagger.suggest_tags = AsyncMock(return_value=[])

    with patch("app.services.note_tagger.get_note_tagger", return_value=mock_tagger):
        resp = client.post(f"/notes/{note_id}/suggest-tags")

    assert resp.status_code == 200
    assert resp.json()["tags"] == []
