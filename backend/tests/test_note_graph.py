"""The entities a note is about (S163), stored in `graph_note_entities`.

GLiNER is mocked to return controlled entity lists.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.main import app
from app.models import GraphNoteEntityModel, NoteModel
from app.services.note_graph import NoteGraphService
from tests.graph_seed import add_graph, add_note


def _extractor(*names: str, score: float = 0.9):
    mock = MagicMock()
    mock.extract.return_value = [
        {"name": n, "type": "CONCEPT", "score": score, "chunk_id": "c1"} for n in names
    ]
    return mock


async def _upsert(note_id, content, document_id=None, tags=(), names=()):
    with patch("app.services.ner.get_entity_extractor", return_value=_extractor(*names)):
        await NoteGraphService().upsert_note_node(note_id, content, document_id, list(tags))


async def _edges(memory_db, note_id: str) -> list[tuple[str, str]]:
    async with memory_db.factory() as s:
        rows = await s.execute(
            select(GraphNoteEntityModel.entity_id, GraphNoteEntityModel.kind).where(
                GraphNoteEntityModel.note_id == note_id
            )
        )
        return sorted(tuple(r) for r in rows)


@pytest.fixture
async def note(memory_db):
    await add_note(memory_db, "n1", "placeholder")
    return "n1"


async def test_written_about_edge_for_a_known_entity(memory_db, note):
    await add_graph(memory_db, "d1", {"e1": ("gradient descent", "CONCEPT")})
    await _upsert(note, "Notes on gradient descent.", names=("gradient descent",))

    assert await _edges(memory_db, note) == [("e1", "written_about")]
    [entity] = await NoteGraphService().get_entities_for_note(note)
    assert entity["edge_type"] == "WRITTEN_ABOUT"
    assert entity["confidence"] == pytest.approx(0.9)


async def test_an_unknown_entity_is_skipped(memory_db, note):
    await _upsert(note, "Mentions nonexistent entity xyz.", names=("nonexistent entity xyz",))
    assert await _edges(memory_db, note) == []


async def test_a_tag_matching_an_entity_name_ignoring_case_links_it(memory_db, note):
    await add_graph(memory_db, "d1", {"e1": ("Neural Networks", "CONCEPT")})
    await _upsert(note, "Content.", tags=("neural networks",))
    assert await _edges(memory_db, note) == [("e1", "tag")]


async def test_the_notes_own_document_wins_a_shared_name(memory_db, note):
    await add_graph(memory_db, "d1", {"e1": ("attention", "CONCEPT")})
    await add_graph(memory_db, "d2", {"e2": ("attention", "CONCEPT")})
    await _upsert(note, "On attention.", document_id="d2", names=("attention",))
    assert await _edges(memory_db, note) == [("e2", "written_about")]


async def test_a_resave_replaces_the_notes_edges(memory_db, note):
    await add_graph(memory_db, "d1", {"e1": ("alpha", "CONCEPT"), "e2": ("beta", "CONCEPT")})
    await _upsert(note, "alpha", names=("alpha",))
    await _upsert(note, "beta", names=("beta",))
    assert await _edges(memory_db, note) == [("e2", "written_about")]


async def test_a_deleted_note_leaves_no_edges(memory_db, note):
    """#65: deleted notes kept their graph nodes in Kuzu; the edge now cascades."""
    await add_graph(memory_db, "d1", {"e1": ("backpropagation", "CONCEPT")})
    await _upsert(note, "Backpropagation is key.", names=("backpropagation",))
    assert await _edges(memory_db, note) == [("e1", "written_about")]

    async with memory_db.factory() as s:
        await s.execute(delete(NoteModel).where(NoteModel.id == note))
        await s.commit()

    assert await _edges(memory_db, note) == []
    assert await NoteGraphService().get_entities_for_note(note) == []


async def test_edges_for_a_note_deleted_before_extraction_finished_are_not_stored(memory_db):
    """The upsert runs after the save returns, so the note can be gone by then (#65)."""
    await add_graph(memory_db, "d1", {"e1": ("backpropagation", "CONCEPT")})
    await _upsert("never-saved", "Backpropagation.", names=("backpropagation",))
    assert await _edges(memory_db, "never-saved") == []


async def test_get_note_entities_endpoint(memory_db):
    await add_graph(memory_db, "d1", {"e1": ("gradient", "CONCEPT")})
    await add_note(memory_db, "n1", "On gradients", "e1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/notes/n1/entities")

    assert resp.status_code == 200
    assert [(e["name"], e["edge_type"]) for e in resp.json()] == [("gradient", "WRITTEN_ABOUT")]


async def test_a_failed_extraction_keeps_the_notes_entities_and_updates_its_tags(memory_db, note):
    """#65: a GLiNER failure (model not installed, a crash) stored an empty entity
    list over the note's links, so one failed save erased them."""
    await add_graph(memory_db, "d1", {"e1": ("alpha", "CONCEPT"), "e2": ("beta", "CONCEPT")})
    await _upsert(note, "alpha", names=("alpha",))

    failing = MagicMock()
    failing.extract.side_effect = RuntimeError("model not loaded")
    with patch("app.services.ner.get_entity_extractor", return_value=failing):
        await NoteGraphService().upsert_note_node(note, "alpha", None, ["beta"])

    assert await _edges(memory_db, note) == [("e1", "written_about"), ("e2", "tag")]
