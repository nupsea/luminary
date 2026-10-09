"""Tests for GraphService and the GET /graph endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.main import app
from app.models import DocumentModel, GraphEntityModel, NoteLinkModel
from app.services.graph import DocumentGraph, get_graph_service
from tests.graph_seed import add_documents, add_graph, add_note, add_raw_edge, edges


@pytest.fixture
def svc(memory_db):
    return get_graph_service()


async def _entity(memory_db, entity_id: str) -> GraphEntityModel | None:
    async with memory_db.factory() as s:
        return await s.get(GraphEntityModel, entity_id)


async def _entity_ids(memory_db) -> set[str]:
    async with memory_db.factory() as s:
        return set(await s.scalars(select(GraphEntityModel.id)))


# Writes


async def test_a_written_entity_reads_back(memory_db, svc):
    await add_graph(memory_db, "d1", {"e1": ("Albert Einstein", "PERSON")})
    e = await _entity(memory_db, "e1")
    assert (e.name, e.type, e.document_id) == ("Albert Einstein", "PERSON", "d1")


async def test_each_mention_adds_to_frequency(memory_db, svc):
    graph = DocumentGraph()
    graph.add_entity("e1", "Tesla", "ORGANIZATION")
    graph.add_entity("e1", "Tesla", "ORGANIZATION")
    await add_documents(memory_db, "d1")
    await svc.write_document_graph("d1", graph)
    await svc.write_document_graph("d1", graph)

    e = await _entity(memory_db, "e1")
    assert (e.frequency, e.mention_count) == (4, 4)


async def test_aliases_are_stored(memory_db, svc):
    graph = DocumentGraph()
    graph.add_entity("e1", "sherlock holmes", "PERSON", aliases=["holmes", "mr. holmes"])
    await add_documents(memory_db, "d1")
    await svc.write_document_graph("d1", graph)
    assert (await _entity(memory_db, "e1")).aliases == ["holmes", "mr. holmes"]


async def test_a_graph_for_a_deleted_document_is_not_written(memory_db, svc):
    graph = DocumentGraph()
    graph.add_entity("e1", "Newton", "PERSON")
    assert await svc.write_document_graph("gone", graph) is False
    assert await _entity_ids(memory_db) == set()


async def test_replace_drops_the_documents_old_entities_only(memory_db, svc):
    await add_graph(
        memory_db,
        "d1",
        {"e1": ("ulysses", "PERSON"), "e2": ("telemachus", "PERSON")},
        co_occurs=(("e1", "e2"),),
    )
    await add_graph(memory_db, "d2", {"e3": ("achilles", "PERSON")})

    fresh = DocumentGraph()
    fresh.add_entity("e4", "penelope", "PERSON")
    await svc.write_document_graph("d1", fresh, replace=True)

    assert await _entity_ids(memory_db) == {"e3", "e4"}
    assert await svc.count_for_document("d1") == (1, 0)


async def test_co_occurrence_weight_accumulates(memory_db, svc):
    pair = {"e1": ("Newton", "PERSON"), "e2": ("Gravity", "CONCEPT")}
    await add_graph(memory_db, "d1", pair, co_occurs=(("e1", "e2"),))
    await add_graph(memory_db, "d1", pair, co_occurs=(("e1", "e2"),))
    [edge] = await edges(memory_db, "CO_OCCURS")
    assert (edge.source_id, edge.target_id, edge.weight) == ("e1", "e2", pytest.approx(2.0))


async def test_an_entity_is_never_recorded_as_co_occurring_with_itself(memory_db, svc):
    await add_graph(memory_db, "d1", {"e1": ("Ulysses", "PERSON")}, co_occurs=(("e1", "e1"),))
    assert await edges(memory_db, "CO_OCCURS") == []


async def test_an_edge_to_an_unknown_entity_is_dropped(memory_db, svc):
    await add_graph(
        memory_db,
        "d1",
        {"e1": ("closures", "CONCEPT")},
        edges=(("PREREQUISITE_OF", "e1", "nowhere", {"confidence": 0.9}),),
    )
    assert await edges(memory_db, "PREREQUISITE_OF") == []


# Deletion (#204)


async def test_deleting_a_document_deletes_its_graph_and_nothing_else(memory_db, svc):
    await add_graph(
        memory_db,
        "d1",
        {"e1": ("Darwin", "PERSON"), "e2": ("Evolution", "CONCEPT")},
        co_occurs=(("e1", "e2"),),
    )
    await add_graph(
        memory_db,
        "d2",
        {"e3": ("Darwin", "PERSON"), "e4": ("Finches", "CONCEPT")},
        co_occurs=(("e3", "e4"),),
    )
    await svc.add_same_concept_edge("e1", "e3", "d1", "d2", 0.9)

    async with memory_db.factory() as s:
        await s.execute(delete(DocumentModel).where(DocumentModel.id == "d1"))
        await s.commit()

    assert await _entity_ids(memory_db) == {"e3", "e4"}
    assert [(e.source_id, e.target_id) for e in await edges(memory_db, "CO_OCCURS")] == [
        ("e3", "e4")
    ]
    assert await svc.get_same_concept_edges() == []
    assert await svc.get_document_ids_for_entity("Darwin") == ["d2"]


async def test_the_chat_graph_node_reads_only_live_documents_in_scope(memory_db, svc):
    """#205: half the CO_OCCURS edges in a real library belonged to deleted documents,
    and the chat graph node fed them into answers."""
    from app.runtime.chat_nodes.graph import _graph_lines_for_entity

    for doc, partner in (("d1", "Minerva"), ("d2", "Penelope"), ("d3", "Circe")):
        await add_graph(
            memory_db,
            doc,
            {f"{doc}-u": ("Ulysses", "PERSON"), f"{doc}-p": (partner, "PERSON")},
            co_occurs=((f"{doc}-u", f"{doc}-p"),),
        )
    async with memory_db.factory() as s:
        await s.execute(delete(DocumentModel).where(DocumentModel.id == "d3"))
        await s.commit()

    everywhere = await _graph_lines_for_entity("Ulysses", None)
    assert sorted(everywhere) == [
        "Ulysses --co-occurs--> Minerva (weight=1.0)",
        "Ulysses --co-occurs--> Penelope (weight=1.0)",
    ]
    assert await _graph_lines_for_entity("Ulysses", ["d2"]) == [
        "Ulysses --co-occurs--> Penelope (weight=1.0)"
    ]


async def test_entity_lookups_by_name_ignore_case(memory_db, svc):
    """NER stores names lowercased and questions name them capitalised: an exact match
    gave the chat graph node no lines for any of 125 golden questions."""
    from app.runtime.chat_nodes.graph import _graph_lines_for_entity

    await add_graph(
        memory_db,
        "d1",
        {"u": ("ulysses", "PERSON"), "p": ("penelope", "PERSON"), "o": ("ödipus", "PERSON")},
        co_occurs=(("u", "p"),),
    )

    assert await _graph_lines_for_entity("Ulysses", None) == [
        "Ulysses --co-occurs--> penelope (weight=1.0)"
    ]
    assert await svc.get_document_ids_for_entity("ULYSSES") == ["d1"]
    assert await svc.get_document_ids_for_entity("Ödipus") == ["d1"]


# Views


async def test_get_graph_for_document(memory_db, svc):
    await add_graph(memory_db, "d1", {"e1": ("Darwin", "PERSON"), "e2": ("Evolution", "CONCEPT")})
    data = await svc.get_graph_for_document("d1")
    assert {n["id"] for n in data["nodes"]} == {"e1", "e2"}
    for n in data["nodes"]:
        assert n["document_id"] == "d1"
        assert n["document_ids"] == ["d1"]


async def test_empty_graph_for_unknown_document(memory_db, svc):
    assert await svc.get_graph_for_document("nonexistent") == {"nodes": [], "edges": []}


async def test_get_graph_for_documents_merges(memory_db, svc):
    await add_graph(memory_db, "d1", {"e1": ("Darwin", "PERSON")})
    await add_graph(memory_db, "d2", {"e2": ("Evolution", "CONCEPT")})
    nodes = {n["id"]: n for n in (await svc.get_graph_for_documents(["d1", "d2"]))["nodes"]}
    assert nodes["e1"]["document_ids"] == ["d1"]
    assert nodes["e2"]["document_ids"] == ["d2"]


async def test_get_graph_for_documents_scopes_co_occurrence_edges(memory_db, svc):
    await add_graph(
        memory_db,
        "d1",
        {"e1": ("Darwin", "CONCEPT"), "e2": ("Evolution", "CONCEPT")},
        co_occurs=(("e1", "e2"),),
    )
    await add_graph(
        memory_db,
        "d2",
        {"e3": ("Kepler", "CONCEPT"), "e4": ("Orbits", "CONCEPT")},
        co_occurs=(("e3", "e4"),),
    )

    one = await svc.get_graph_for_documents(["d1"])
    assert {(e["source"], e["target"]) for e in one["edges"]} == {("e1", "e2")}
    both = await svc.get_graph_for_documents(["d1", "d2"])
    assert {(e["source"], e["target"]) for e in both["edges"]} == {("e1", "e2"), ("e3", "e4")}


async def test_get_graph_for_document_includes_tech_edges(memory_db, svc):
    await add_graph(
        memory_db,
        "d1",
        {"e1": ("numpy", "LIBRARY"), "e2": ("ndarray", "DATA_STRUCTURE")},
        edges=(("IMPLEMENTS", "e1", "e2", {}),),
    )
    data = await svc.get_graph_for_document("d1")
    assert "IMPLEMENTS" in {e.get("relation") for e in data["edges"]}


async def test_get_entities_by_type_for_document(memory_db, svc):
    await add_graph(
        memory_db,
        "d1",
        {
            "e1": ("sherlock holmes", "PERSON"),
            "e2": ("dr. watson", "PERSON"),
            "e3": ("baker street", "PLACE"),
        },
    )
    result = await svc.get_entities_by_type_for_document("d1")
    assert set(result["PERSON"]) == {"sherlock holmes", "dr. watson"}
    assert result["PLACE"] == ["baker street"]
    assert await svc.get_entities_by_type_for_document("nonexistent") == {}


async def test_get_entities_by_type_filters_and_returns_fields(memory_db, svc):
    await add_graph(
        memory_db,
        "d1",
        {"e1": ("numpy", "LIBRARY"), "e2": ("alice", "PERSON"), "e3": ("sqlalchemy", "LIBRARY")},
    )
    libs = await svc.get_entities_by_type("d1", "LIBRARY")
    assert {e["name"] for e in libs} == {"numpy", "sqlalchemy"}
    assert set(libs[0]) == {"id", "name", "type", "frequency"}
    assert await svc.get_entities_by_type("d1", "PLACE") == []


# SAME_CONCEPT contradictions


async def _seed_same_concept(memory_db, svc) -> None:
    for doc, entity in (("d1", "e1"), ("d2", "e2"), ("d3", "e3"), ("d4", "e4")):
        await add_graph(memory_db, doc, {entity: (entity, "CONCEPT")})
    await svc.add_same_concept_edge(
        "e1", "e2", "d1", "d2", 0.9, contradiction=True, contradiction_note="A says X, B says Y"
    )
    await svc.add_same_concept_edge(
        "e3", "e4", "d3", "d4", 0.8, contradiction=True, contradiction_note="C says P, D says Q"
    )
    await svc.add_same_concept_edge("e1", "e3", "d1", "d3", 0.7, contradiction=False)


async def test_contradiction_edges_for_docs_scopes_to_requested_docs(memory_db, svc):
    await _seed_same_concept(memory_db, svc)
    rows = await svc.get_contradiction_edges_for_docs(["d1"])
    assert [(r["contradiction_note"], r["contradiction"]) for r in rows] == [
        ("A says X, B says Y", True)
    ]
    # d4 is only ever a target document.
    rows = await svc.get_contradiction_edges_for_docs(["d4"])
    assert {r["contradiction_note"] for r in rows} == {"C says P, D says Q"}
    assert await svc.get_contradiction_edges_for_docs([]) == []


async def test_contradiction_edges_equal_a_full_scan_filtered(memory_db, svc):
    await _seed_same_concept(memory_db, svc)
    all_edges = await svc.get_same_concept_edges()
    for docs in (["d1"], ["d2"], ["d3", "d4"], ["d1", "d3"], ["nope"]):
        expected = {
            (e["entity_id_a"], e["entity_id_b"])
            for e in all_edges
            if e["contradiction"] and (e["source_doc_id"] in docs or e["target_doc_id"] in docs)
        }
        rows = await svc.get_contradiction_edges_for_docs(docs)
        assert {(e["entity_id_a"], e["entity_id_b"]) for e in rows} == expected, docs


async def test_a_second_link_records_a_contradiction_but_never_clears_one(memory_db, svc):
    await _seed_same_concept(memory_db, svc)
    await svc.add_same_concept_edge("e2", "e1", "d2", "d1", 0.9, contradiction=False)
    rows = await svc.get_contradiction_edges_for_docs(["d1"])
    assert [r["contradiction_note"] for r in rows] == ["A says X, B says Y"]


# Notes on the Map (S172)


async def test_include_notes_returns_note_nodes_and_edges(memory_db, svc):
    await add_graph(memory_db, "d1", {"e1": ("backpropagation", "CONCEPT")})
    await add_note(memory_db, "n1", "Notes on backprop training", "e1")

    data = await svc.get_graph_for_document("d1", include_notes=True)
    [note] = [n for n in data["nodes"] if n.get("type") == "note"]
    assert (note["note_id"], note["label"]) == ("n1", "Notes on backprop training")
    [edge] = [e for e in data["edges"] if e.get("relation") == "WRITTEN_ABOUT"]
    assert (edge["source"], edge["target"]) == ("n1", "e1")

    plain = await svc.get_graph_for_document("d1")
    assert not [n for n in plain["nodes"] if n.get("type") == "note"]


async def test_a_note_about_entities_out_of_scope_is_excluded(memory_db, svc):
    await add_graph(memory_db, "d1", {"e1": ("neural nets", "CONCEPT")})
    await add_graph(memory_db, "d2", {"e2": ("attention", "CONCEPT")})
    await add_note(memory_db, "n1", "Neural net notes", "e1")
    await add_note(memory_db, "n2", "Attention notes", "e2")

    data = await svc.get_graph_for_document("d1", include_notes=True)
    assert {n["note_id"] for n in data["nodes"] if n.get("type") == "note"} == {"n1"}


async def test_links_between_notes_in_scope_are_included(memory_db, svc):
    await add_graph(memory_db, "d1", {"e1": ("optimization", "CONCEPT")})
    await add_note(memory_db, "n1", "Note on SGD", "e1")
    await add_note(memory_db, "n2", "Note on Adam", "e1")
    async with memory_db.factory() as s:
        s.add(NoteLinkModel(id="l1", source_note_id="n1", target_note_id="n2", link_type="see"))
        await s.commit()

    data = await svc.get_graph_for_document("d1", include_notes=True)
    links = [(e["source"], e["target"]) for e in data["edges"] if e.get("relation") == "LINKS_TO"]
    assert links == [("n1", "n2")]


async def test_get_graph_for_documents_include_notes(memory_db, svc):
    await add_graph(memory_db, "d1", {"e1": ("physics", "CONCEPT")})
    await add_graph(memory_db, "d2", {"e2": ("physics", "CONCEPT")})
    await add_note(memory_db, "n1", "Physics note", "e1")
    await add_note(memory_db, "n1", "Physics note", "e2")

    data = await svc.get_graph_for_documents(["d1", "d2"], include_notes=True)
    assert [n["note_id"] for n in data["nodes"] if n.get("type") == "note"] == ["n1"]


# Co-occurring pairs (I-49)


async def test_a_self_pair_already_in_the_graph_is_never_handed_out(memory_db, svc):
    """Self-pairs written before the guard existed stay in older graphs; the read
    excludes them, or the protagonist paired with himself is every document's top pair."""
    await add_graph(
        memory_db,
        "d1",
        {"e1": ("Ulysses", "PERSON"), "e2": ("Minerva", "PERSON")},
        co_occurs=(("e1", "e2"),),
    )
    await add_raw_edge(memory_db, "CO_OCCURS", "e1", "e1", "d1", weight=62.0)

    pairs = await svc.get_co_occurring_pairs_for_document("d1", limit=5)
    assert [(a, b) for a, b, _ in pairs] == [("Ulysses", "Minerva")]


async def test_one_pair_is_handed_out_once_however_its_edges_point(memory_db, svc):
    await add_graph(
        memory_db,
        "d1",
        {"e1": ("Ulysses", "PERSON"), "e2": ("Minerva", "PERSON")},
        co_occurs=(("e1", "e2"),),
    )
    await add_raw_edge(memory_db, "CO_OCCURS", "e2", "e1", "d1", weight=17.0)

    pairs = await svc.get_co_occurring_pairs_for_document("d1", limit=5)
    assert len(pairs) == 1, pairs


# API


@pytest.fixture
async def client(memory_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_get_graph_document_endpoint(memory_db, client):
    await add_graph(memory_db, "d1", {"e1": ("Curie", "PERSON")})
    resp = await client.get("/graph/d1")
    assert resp.status_code == 200
    assert [n["label"] for n in resp.json()["nodes"]] == ["Curie"]


async def test_get_graph_multi_doc_endpoint(memory_db, client):
    await add_graph(memory_db, "d1", {"e1": ("Curie", "PERSON")})
    await add_graph(memory_db, "d2", {"e2": ("Radium", "CONCEPT")})
    resp = await client.get("/graph?doc_ids=d1,d2")
    assert resp.status_code == 200
    assert {n["id"] for n in resp.json()["nodes"]} == {"e1", "e2"}


async def test_get_graph_empty_doc_ids(memory_db, client):
    resp = await client.get("/graph?doc_ids=")
    assert resp.status_code == 200
    assert resp.json()["nodes"] == []


async def test_entities_by_type_api_endpoint(memory_db, client):
    await add_graph(memory_db, "d1", {"e1": ("numpy", "LIBRARY"), "e2": ("einstein", "PERSON")})
    resp = await client.get("/graph/entities/d1?type=LIBRARY")
    assert resp.status_code == 200
    assert [(e["name"], e["type"]) for e in resp.json()["entities"]] == [("numpy", "LIBRARY")]


async def test_entities_endpoint_not_captured_by_document_id_route(memory_db, client):
    resp = await client.get("/graph/entities/doc1?type=LIBRARY")
    assert resp.status_code == 200
    assert "entities" in resp.json()
