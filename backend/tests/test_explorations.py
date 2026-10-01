"""GET /chat/explorations and GraphService.get_related_entity_pairs_for_document."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.graph import get_graph_service
from tests.graph_seed import add_graph


def _related(*triples: tuple[str, str, str, float]) -> tuple:
    return tuple(
        ("RELATED_TO", a, b, {"label": label, "confidence": conf}) for a, b, label, conf in triples
    )


async def test_no_pairs_for_a_document_without_relations(memory_db):
    assert await get_graph_service().get_related_entity_pairs_for_document("doc-missing") == []


async def test_pairs_are_named_and_most_confident_first(memory_db):
    await add_graph(
        memory_db,
        "doc-aw",
        {"e0": ("alice", "PERSON"), "e1": ("rabbit", "PERSON"), "e2": ("queen", "PERSON")},
        edges=_related(("e0", "e1", "follows", 0.5), ("e1", "e2", "opposes", 0.95)),
    )
    pairs = await get_graph_service().get_related_entity_pairs_for_document("doc-aw", limit=5)
    assert pairs == [
        ("rabbit", "queen", "opposes", pytest.approx(0.95)),
        ("alice", "rabbit", "follows", pytest.approx(0.5)),
    ]


async def test_pairs_respect_the_limit(memory_db):
    entities = {f"e{i}": (f"entity{i}", "CONCEPT") for i in range(6)}
    await add_graph(
        memory_db,
        "doc-lim",
        entities,
        edges=_related(*((f"e{i}", f"e{i + 1}", "linked", i / 5) for i in range(5))),
    )
    pairs = await get_graph_service().get_related_entity_pairs_for_document("doc-lim", limit=3)
    assert len(pairs) == 3


@pytest.fixture
async def client(memory_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_explorations_returns_200_empty_for_unknown_doc(client):
    resp = await client.get("/chat/explorations?document_id=nonexistent-doc-xyz")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_explorations_names_the_related_entities(memory_db, client):
    await add_graph(
        memory_db,
        "s109",
        {"e1": ("time traveller", "PERSON"), "e2": ("weena", "PERSON")},
        edges=_related(("e1", "e2", "rescues", 0.8)),
    )
    resp = await client.get("/chat/explorations?document_id=s109")
    assert resp.status_code == 200
    [suggestion] = resp.json()
    assert "rescues" in suggestion["text"]
    assert set(suggestion["entity_names"]) == {"time traveller", "weena"}
