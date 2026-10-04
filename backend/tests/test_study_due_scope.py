"""Collection and tag scoping of GET /study/due and /study/due-count.

Library layout, every card due unless named otherwise:
  parent collection P: doc_a (tag alpha), note_a (tag alpha)
  child collection C of P: doc_b (tag beta), note_b (untagged)
  outside any collection: doc_out (tag alpha), note_out (tag alpha)
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import (
    CollectionMemberModel,
    CollectionModel,
    DocumentModel,
    FlashcardModel,
    NoteModel,
    NoteTagIndexModel,
)

_PAST = datetime.now(UTC) - timedelta(days=1)


def _doc(doc_id: str, tags: list[str]) -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title=doc_id,
        format="txt",
        content_type="book",
        word_count=1,
        page_count=0,
        file_path="/tmp/x.txt",
        stage="complete",
        tags=tags,
    )


def _card(card_id: str, *, document_id=None, note_id=None, due=_PAST) -> FlashcardModel:
    return FlashcardModel(
        id=card_id,
        document_id=document_id,
        note_id=note_id,
        question=f"Q {card_id}?",
        answer="A.",
        source_excerpt="A.",
        fsrs_state="review",
        fsrs_stability=1.0,
        fsrs_difficulty=0.5,
        due_date=due,
    )


def _member(collection_id: str, member_id: str, member_type: str) -> CollectionMemberModel:
    return CollectionMemberModel(
        id=str(uuid.uuid4()),
        collection_id=collection_id,
        member_id=member_id,
        member_type=member_type,
    )


@pytest.fixture
async def library(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        session.add_all(
            [
                _doc("doc_a", ["alpha"]),
                _doc("doc_b", ["beta"]),
                _doc("doc_out", ["alpha"]),
                NoteModel(id="note_a", content="a"),
                NoteModel(id="note_b", content="b"),
                NoteModel(id="note_out", content="o"),
                NoteTagIndexModel(note_id="note_a", tag_full="alpha", tag_root="alpha"),
                NoteTagIndexModel(note_id="note_out", tag_full="alpha", tag_root="alpha"),
                CollectionModel(id="P", name="P"),
                CollectionModel(id="C", name="C", parent_collection_id="P"),
                CollectionModel(id="EMPTY", name="E"),
                _member("P", "doc_a", "document"),
                _member("P", "note_a", "note"),
                _member("C", "doc_b", "document"),
                _member("C", "note_b", "note"),
                _card("c_doc_a", document_id="doc_a"),
                _card("c_doc_a_future", document_id="doc_a", due=_PAST + timedelta(days=30)),
                _card("c_doc_b", document_id="doc_b"),
                _card("c_doc_out", document_id="doc_out"),
                _card("c_note_a", note_id="note_a"),
                _card("c_note_b", note_id="note_b"),
                _card("c_note_out", note_id="note_out"),
            ]
        )
        await session.commit()


async def _due(params: dict) -> tuple[set[str], int]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cards = await client.get("/study/due", params={**params, "limit": 100})
        count = await client.get("/study/due-count", params=params)
    assert cards.status_code == 200, cards.text
    assert count.status_code == 200, count.text
    return {c["id"] for c in cards.json()}, count.json()["due_today"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, {"c_doc_a", "c_doc_b", "c_doc_out", "c_note_a", "c_note_b", "c_note_out"}),
        ({"collection_id": "P"}, {"c_doc_a", "c_doc_b", "c_note_a", "c_note_b"}),
        ({"collection_id": "C"}, {"c_doc_b", "c_note_b"}),
        ({"collection_id": "EMPTY"}, set()),
        ({"collection_id": "P", "tag": "alpha"}, {"c_doc_a", "c_note_a"}),
        ({"collection_id": "P", "tag": "beta"}, {"c_doc_b"}),
        ({"collection_id": "P", "tag": "missing"}, set()),
        ({"tag": "alpha"}, {"c_doc_a", "c_doc_out", "c_note_a", "c_note_out"}),
        ({"tag": "beta"}, {"c_doc_b"}),
        # Explicit ids win over the collection scope.
        ({"collection_id": "C", "document_ids": ["doc_out"]}, {"c_doc_out"}),
        ({"collection_id": "C", "note_ids": ["note_a"]}, {"c_note_a"}),
        ({"document_ids": ["doc_a", "doc_b"]}, {"c_doc_a", "c_doc_b"}),
    ],
)
async def test_due_scope(library, params, expected):
    ids, count = await _due(params)
    assert ids == expected
    assert count == len(expected)


@pytest.mark.asyncio
async def test_tagged_card_listed_once_whatever_its_note_tags(library, test_db):
    """A tag-matched card whose note carries several tags is one card, not one per tag."""
    _, factory, _ = test_db
    async with factory() as session:
        session.add_all(
            [
                NoteModel(id="note_two", content="t"),
                NoteTagIndexModel(note_id="note_two", tag_full="alpha", tag_root="alpha"),
                NoteTagIndexModel(note_id="note_two", tag_full="gamma", tag_root="gamma"),
                _card("c_both", document_id="doc_a", note_id="note_two"),
            ]
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cards = (await client.get("/study/due", params={"tag": "alpha", "limit": 100})).json()
    ids = [c["id"] for c in cards]
    assert ids.count("c_both") == 1
    ids, count = await _due({"tag": "alpha"})
    assert count == len(ids)
