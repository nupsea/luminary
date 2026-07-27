"""Dedup scope for flashcard generation.

A collection study session interleaves cards generated from a document with
cards generated from the notes in that collection, but the two land in
different decks. Comparing only within a deck let near-duplicates be created.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import CollectionMemberModel, CollectionModel, FlashcardModel
from app.services.flashcard import _study_scope_member_ids


@pytest.fixture
async def session():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _card(card_id: str, question: str, *, deck: str, document_id=None, note_id=None):
    return FlashcardModel(
        id=card_id,
        document_id=document_id,
        note_id=note_id,
        source="document" if document_id else "note",
        deck=deck,
        question=question,
        answer="a",
        source_excerpt="",
    )


async def _collection_with(s, collection_id: str, members: list[tuple[str, str]]):
    s.add(CollectionModel(id=collection_id, name=collection_id, color="#fff"))
    for member_id, member_type in members:
        s.add(
            CollectionMemberModel(
                id=f"{collection_id}-{member_id}",
                collection_id=collection_id,
                member_id=member_id,
                member_type=member_type,
            )
        )
    await s.commit()


@pytest.mark.asyncio
async def test_scope_spans_documents_and_notes_of_the_collection(session):
    await _collection_with(
        session, "col-1", [("doc-1", "document"), ("note-1", "note"), ("doc-2", "document")]
    )
    members = await _study_scope_member_ids("doc-1", session)
    assert set(members) == {"doc-1", "note-1", "doc-2"}


@pytest.mark.asyncio
async def test_scope_excludes_unrelated_collections(session):
    await _collection_with(session, "col-1", [("doc-1", "document"), ("note-1", "note")])
    await _collection_with(session, "col-2", [("doc-9", "document"), ("note-9", "note")])
    members = await _study_scope_member_ids("doc-1", session)
    assert "note-9" not in members and "doc-9" not in members


@pytest.mark.asyncio
async def test_document_in_no_collection_yields_no_members(session):
    assert await _study_scope_member_ids("orphan-doc", session) == []


@pytest.mark.asyncio
async def test_note_cards_in_another_deck_become_comparable(session, monkeypatch):
    """The regression: a note card in deck 'search' was invisible to a document
    generating into deck 'default', so a near-duplicate question was created."""
    await _collection_with(session, "col-1", [("doc-1", "document"), ("note-1", "note")])
    session.add(_card("c1", "Deck-mate question", deck="default", document_id="doc-other"))
    session.add(_card("c2", "What does a Bi-encoder do?", deck="search", note_id="note-1"))
    await session.commit()

    captured: list[list[str]] = []

    class _Embedder:
        def encode(self, texts):
            captured.append(list(texts))
            return [[1.0, 0.0] for _ in texts]

    import app.services.embedder as embedder_module

    monkeypatch.setattr(embedder_module, "get_embedding_service", lambda: _Embedder())

    from app.services.flashcard import _fetch_existing_embeddings

    deck_only, _ = await _fetch_existing_embeddings("default", session)
    assert "What does a Bi-encoder do?" not in deck_only

    scoped, _ = await _fetch_existing_embeddings("default", session, document_id="doc-1")
    assert "What does a Bi-encoder do?" in scoped
    assert "Deck-mate question" in scoped, "deck-based comparison must still apply"
