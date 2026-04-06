"""Tests for S93: Flashcard generation from notes.

Test plan:
  1. test_generate_from_notes_raises_without_tag_or_ids -- unit: ValueError if both absent
  2. test_generate_from_notes_by_tag -- integration: create notes with tag, generate, assert cards
  3. test_generate_from_notes_by_ids -- integration: create notes by IDs, generate, assert cards
  4. test_generate_endpoint_422_no_scope -- API: POST /notes/flashcards/generate with no tag/ids
  5. test_generate_endpoint_201 -- API: POST /notes/flashcards/generate with tag returns cards
  6. test_alice_notes_flashcards -- slow: Alice notes, generate, assert source='note'
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytest_plugins = ["conftest_books"]


# ---------------------------------------------------------------------------
# Unit test — pure ValueError check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_from_notes_raises_without_tag_or_ids():
    """FlashcardService.generate_from_notes raises ValueError when no scope given."""
    from app.services.flashcard import get_flashcard_service

    svc = get_flashcard_service()
    with pytest.raises(ValueError, match="Must provide tag or note_ids"):
        # We pass None/empty for both — should raise before any DB call
        # Use a dummy session mock that will never be used
        await svc.generate_from_notes(tag=None, note_ids=[], count=5, session=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_generate_endpoint_422_no_scope(client):
    """POST /notes/flashcards/generate with neither tag nor note_ids returns 422."""
    resp = client.post(
        "/notes/flashcards/generate",
        json={"count": 3},
    )
    assert resp.status_code == 422


def test_generate_endpoint_201(client):
    """POST /notes with tag, then generate flashcards by that tag returns 201."""
    tag = "s93test"
    # Create two notes with the tag
    for content in [
        "The Cheshire Cat can vanish leaving only its smile",
        "Alice fell down a rabbit hole into Wonderland",
    ]:
        r = client.post("/notes", json={"content": content, "tags": [tag]})
        assert r.status_code == 201

    # Two-pass LLM: 1st call = concept extraction, 2nd call = card generation
    concept_resp = (
        '{"domain": "Wonderland", "concepts": '
        '[{"concept": "Cheshire Cat vanishing", "type": "concept"}]}'
    )
    card_resp = (
        '[{"question": "What can the Cheshire Cat do?", '
        '"answer": "Vanish leaving its smile", "source_excerpt": "..."}]'
    )
    mock_llm = AsyncMock(side_effect=[concept_resp, card_resp])
    with patch("app.services.llm.LLMService.generate", mock_llm):
        resp = client.post(
            "/notes/flashcards/generate",
            json={"tag": tag, "count": 2},
        )

    assert resp.status_code == 201
    cards = resp.json()
    assert isinstance(cards, list)
    assert len(cards) >= 1
    assert cards[0]["source"] == "note"
    assert cards[0]["question"]


def test_generate_from_notes_by_ids(client):
    """Create notes, generate by explicit note_ids, cards have source='note'."""
    note_ids = []
    for content in [
        "The White Rabbit is always late",
        "The Mad Hatter hosts an eternal tea party",
    ]:
        r = client.post("/notes", json={"content": content, "tags": []})
        assert r.status_code == 201
        note_ids.append(r.json()["id"])

    # Two-pass LLM: 1st call = concept extraction, 2nd call = card generation
    concept_resp = (
        '{"domain": "Wonderland", "concepts": '
        '[{"concept": "White Rabbit punctuality", "type": "concept"}]}'
    )
    card_resp = (
        '[{"question": "Who is always late?", '
        '"answer": "The White Rabbit", "source_excerpt": "..."}]'
    )
    mock_llm = AsyncMock(side_effect=[concept_resp, card_resp])
    with patch("app.services.llm.LLMService.generate", mock_llm):
        resp = client.post(
            "/notes/flashcards/generate",
            json={"note_ids": note_ids, "count": 2},
        )

    assert resp.status_code == 201
    cards = resp.json()
    assert len(cards) >= 1
    assert all(c["source"] == "note" for c in cards)
    assert all(c["question"] for c in cards)


# ---------------------------------------------------------------------------
# Slow integration test
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_alice_notes_flashcards(all_books_ingested):
    """Create Alice notes, generate flashcards, assert source='note' and cards saved."""
    with TestClient(app) as c:
        tag = "alice-s93-slow"
        note_ids = []
        for content in [
            "Alice followed the White Rabbit into Wonderland",
            "The Cheshire Cat can vanish but its grin remains",
            "The Queen of Hearts shouts 'Off with their heads!'",
        ]:
            r = c.post("/notes", json={"content": content, "tags": [tag]})
            assert r.status_code == 201
            note_ids.append(r.json()["id"])

        # Two-pass LLM: 1st call = concept extraction, 2nd call = card generation
        concept_resp = (
            '{"domain": "Wonderland", "concepts": '
            '[{"concept": "White Rabbit", "type": "character"}, '
            '{"concept": "Cheshire Cat grin", "type": "concept"}]}'
        )
        card_resp = (
            '[{"question": "Who did Alice follow?", '
            '"answer": "The White Rabbit", "source_excerpt": "Alice followed..."}, '
            '{"question": "What remains after the Cheshire Cat vanishes?", '
            '"answer": "Its grin", "source_excerpt": "grin remains"}]'
        )
        mock_llm = AsyncMock(side_effect=[concept_resp, card_resp])
        with patch("app.services.llm.LLMService.generate", mock_llm):
            resp = c.post(
                "/notes/flashcards/generate",
                json={"tag": tag, "count": 3},
            )

        assert resp.status_code == 201
        cards = resp.json()
        assert len(cards) >= 1
        for card in cards:
            assert card["source"] == "note"
            assert isinstance(card["source_excerpt"], str)
            assert card["question"]
            assert card["answer"]
