"""GET /study/collections/{id}/dashboard over a three-level collection tree.

P: doc_p (tags t1, t2; 2 chunks), note_p (tag t1)
  C1: doc_c1 (tag t3; 1 chunk)
    G: note_g (untagged, 3000 chars)
  C2: doc_c2 (no cards)
outside: doc_out (tag t1), whose cards must not count
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import (
    ChunkModel,
    CollectionMemberModel,
    CollectionModel,
    DocumentModel,
    FlashcardModel,
    NoteModel,
    NoteTagIndexModel,
)

_NOW = datetime.now(UTC)


def _doc(doc_id: str, tags: list[str]) -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title=f"Title {doc_id}",
        format="txt",
        content_type="book",
        word_count=1,
        page_count=0,
        file_path="/tmp/x.txt",
        stage="complete",
        tags=tags,
    )


def _chunk(doc_id: str, index: int) -> ChunkModel:
    return ChunkModel(id=f"{doc_id}-{index}", document_id=doc_id, text="t", chunk_index=index)


def _card(*, document_id=None, note_id=None, state="review", stability=5.0, due_in_days=10):
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=document_id,
        note_id=note_id,
        question="Q?",
        answer="A.",
        source_excerpt="A.",
        fsrs_state=state,
        fsrs_stability=stability,
        fsrs_difficulty=0.5,
        due_date=_NOW + timedelta(days=due_in_days),
    )


def _member(collection_id: str, member_id: str, member_type: str) -> CollectionMemberModel:
    return CollectionMemberModel(
        id=str(uuid.uuid4()),
        collection_id=collection_id,
        member_id=member_id,
        member_type=member_type,
    )


@pytest.fixture
async def tree(test_db):
    _, factory, _ = test_db
    async with factory() as session:
        session.add_all(
            [
                CollectionModel(id="P", name="Parent"),
                CollectionModel(id="C1", name="Child one", parent_collection_id="P"),
                CollectionModel(id="G", name="Grandchild", parent_collection_id="C1"),
                CollectionModel(id="C2", name="Child two", parent_collection_id="P"),
                CollectionModel(id="EMPTY", name="Empty"),
                _doc("doc_p", ["t1", "t2"]),
                _doc("doc_c1", ["t3"]),
                _doc("doc_c2", []),
                _doc("doc_out", ["t1"]),
                _chunk("doc_p", 0),
                _chunk("doc_p", 1),
                _chunk("doc_c1", 0),
                NoteModel(id="note_p", content="First line\nrest of the note"),
                NoteModel(id="note_g", content="x" * 3000),
                NoteTagIndexModel(note_id="note_p", tag_full="t1", tag_root="t1"),
                _member("P", "doc_p", "document"),
                _member("P", "note_p", "note"),
                _member("C1", "doc_c1", "document"),
                _member("G", "note_g", "note"),
                _member("C2", "doc_c2", "document"),
                _card(document_id="doc_p", state="new", due_in_days=-1),
                _card(document_id="doc_p", stability=40.0),
                _card(note_id="note_p", due_in_days=-1),
                _card(document_id="doc_c1"),
                _card(document_id="doc_c1"),
                _card(document_id="doc_c1"),
                _card(note_id="note_g", state="new", due_in_days=-2),
                _card(document_id="doc_out", due_in_days=-1),
            ]
        )
        await session.commit()


async def _dashboard(collection_id: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(f"/study/collections/{collection_id}/dashboard")


@pytest.mark.asyncio
async def test_dashboard_rolls_up_the_whole_tree(tree):
    resp = await _dashboard("P")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["collection_name"] == "Parent"
    assert (body["due_today"], body["new_today"], body["mastery_pct"]) == (3, 2, 14.3)
    assert body["topics"] == [
        {"tag": "t1", "card_count": 3, "note_count": 1},
        {"tag": "t3", "card_count": 3, "note_count": 0},
        {"tag": "t2", "card_count": 2, "note_count": 0},
    ]
    sources = sorted(body["sources"], key=lambda s: s["id"])
    assert [(s["id"], s["title"], s["type"], s["weight"]) for s in sources] == [
        ("doc_c1", "Title doc_c1", "document", 1),
        ("doc_c2", "Title doc_c2", "document", 0),
        ("doc_p", "Title doc_p", "document", 2),
        ("note_g", "x" * 60, "note", 2),
        ("note_p", "First line", "note", 1),
    ]
    assert sorted(body["sub_collections"], key=lambda s: s["id"]) == [
        {"id": "C1", "name": "Child one", "card_count": 4},
        {"id": "C2", "name": "Child two", "card_count": 0},
    ]


@pytest.mark.asyncio
async def test_dashboard_of_a_leaf(tree):
    body = (await _dashboard("C1")).json()
    assert (body["due_today"], body["new_today"], body["mastery_pct"]) == (1, 1, 0.0)
    assert body["topics"] == [{"tag": "t3", "card_count": 3, "note_count": 0}]
    assert body["sub_collections"] == [{"id": "G", "name": "Grandchild", "card_count": 1}]


@pytest.mark.asyncio
async def test_dashboard_of_an_empty_collection(tree):
    body = (await _dashboard("EMPTY")).json()
    assert (body["due_today"], body["new_today"], body["mastery_pct"]) == (0, 0, 0.0)
    assert body["topics"] == body["sources"] == body["sub_collections"] == []


@pytest.mark.asyncio
async def test_dashboard_of_a_missing_collection(tree):
    assert (await _dashboard("nope")).status_code == 404
