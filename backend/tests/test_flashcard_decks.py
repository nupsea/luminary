"""The deck list never pairs a deck's count with a document it was not counted from (#382)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.factories import make_card, make_document


@pytest.fixture
def factory(memory_db):
    return memory_db.factory


async def test_a_deck_over_two_documents_names_neither(factory):
    now = datetime.now(UTC)
    async with factory() as session:
        for doc_id in ("doc-a", "doc-b", "doc-c"):
            session.add(make_document(id=doc_id, title=doc_id, format="txt", file_path=""))
        await session.flush()
        cards = [("shared", "doc-a"), ("shared", "doc-a"), ("shared", "doc-b"), ("own", "doc-c"),
                 ("own", "doc-c")]  # fmt: skip
        for deck, doc_id in cards:
            session.add(make_card(document_id=doc_id, source="document", deck=deck,
                                  due_date=now, created_at=now))  # fmt: skip
        await session.commit()

    decks = {d["deck"]: d for d in TestClient(app).get("/flashcards/decks").json()}

    # Before #382 this read 3 cards beside doc-b, which holds 1 of them.
    assert (decks["shared"]["card_count"], decks["shared"]["document_id"]) == (3, None)
    assert (decks["own"]["card_count"], decks["own"]["document_id"]) == (2, "doc-c")
    assert decks["own"]["source_type"] == "document"
