"""Tests for DiagramExtractorService (S136): prompt and parse helpers, and graph writes."""

import pytest
from sqlalchemy import select

from app.models import GraphDiagramDepictionModel, GraphDiagramEdgeModel, GraphDiagramNodeModel
from app.services.diagram_extractor import (
    DiagramExtractorService,
    _build_prompt,
    _parse_llm_response,
)
from tests.graph_seed import add_documents, add_graph

# Helpers


# Pure-function tests (no DB, no LLM)


def test_build_prompt_architecture_contains_component() -> None:
    """_build_prompt for architecture_diagram includes 'COMPONENT' keyword."""
    prompt = _build_prompt("architecture_diagram", "A shows B")
    assert "COMPONENT" in prompt
    assert "A shows B" in prompt


def test_build_prompt_sequence_contains_actor() -> None:
    """_build_prompt for sequence_diagram includes 'ACTOR' keyword."""
    prompt = _build_prompt("sequence_diagram", "Client calls Server")
    assert "ACTOR" in prompt


def test_parse_llm_response_valid_json() -> None:
    """_parse_llm_response returns dict for plain JSON."""
    raw = '{"nodes": [{"name": "A", "node_type": "COMPONENT"}], "edges": []}'
    result = _parse_llm_response(raw)
    assert result["nodes"][0]["name"] == "A"
    assert result["edges"] == []


def test_parse_llm_response_fenced_json() -> None:
    """_parse_llm_response strips markdown code fences before parsing."""
    raw = '```json\n{"nodes": [], "edges": []}\n```'
    result = _parse_llm_response(raw)
    assert "nodes" in result
    assert "edges" in result


def test_parse_llm_response_invalid_json() -> None:
    """_parse_llm_response raises ValueError for invalid JSON."""
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_llm_response("not json at all {")


# Graph writes (mocked LiteLLM output, real SQLite)


async def _write(document_id: str, image_type: str, llm_json: str) -> None:
    parsed = _parse_llm_response(llm_json)
    await DiagramExtractorService()._write_to_graph(
        document_id=document_id,
        image_id=f"img-{document_id}",
        image_type=image_type,
        nodes=parsed["nodes"],
        edges=parsed["edges"],
    )


async def _nodes(memory_db, document_id: str) -> list[tuple[str, str]]:
    N = GraphDiagramNodeModel
    async with memory_db.factory() as s:
        rows = await s.execute(select(N.name, N.node_type).where(N.document_id == document_id))
        return sorted(tuple(r) for r in rows)


async def _edges(memory_db, kind: str) -> list[tuple[str, str, str]]:
    N, E = GraphDiagramNodeModel, GraphDiagramEdgeModel
    async with memory_db.factory() as s:
        src = select(N.name).where(N.id == E.source_id).scalar_subquery()
        dst = select(N.name).where(N.id == E.target_id).scalar_subquery()
        rows = await s.execute(select(src, dst, E.label).where(E.kind == kind))
        return [tuple(r) for r in rows]


async def test_architecture_diagram_extraction(memory_db) -> None:
    await add_documents(memory_db, "doc-001")
    await _write(
        "doc-001",
        "architecture_diagram",
        '{"nodes": [{"name": "Service A", "node_type": "COMPONENT"},'
        '{"name": "Service B", "node_type": "COMPONENT"}],'
        '"edges": [{"from": "Service A", "to": "Service B",'
        '"edge_type": "CONNECTS_TO", "label": "calls"}]}',
    )
    assert await _nodes(memory_db, "doc-001") == [
        ("Service A", "COMPONENT"),
        ("Service B", "COMPONENT"),
    ]
    assert await _edges(memory_db, "CONNECTS_TO") == [("Service A", "Service B", "calls")]


async def test_sequence_diagram_routing(memory_db) -> None:
    await add_documents(memory_db, "doc-seq")
    await _write(
        "doc-seq",
        "sequence_diagram",
        '{"nodes": [{"name": "Client", "node_type": "ACTOR"},'
        '{"name": "Server", "node_type": "ACTOR"}],'
        '"edges": [{"from": "Client", "to": "Server", "edge_type": "SENDS_TO",'
        '"message": "POST /login"}]}',
    )
    assert await _nodes(memory_db, "doc-seq") == [("Client", "ACTOR"), ("Server", "ACTOR")]
    assert await _edges(memory_db, "SENDS_TO") == [("Client", "Server", "POST /login")]


async def test_er_diagram_routing(memory_db) -> None:
    await add_documents(memory_db, "doc-er")
    await _write(
        "doc-er",
        "er_diagram",
        '{"nodes": [{"name": "User", "node_type": "ENTITY_DM"},'
        '{"name": "Order", "node_type": "ENTITY_DM"}],'
        '"edges": [{"from": "User", "to": "Order", "edge_type": "REFERENCES_DM"}]}',
    )
    assert {t for _, t in await _nodes(memory_db, "doc-er")} == {"ENTITY_DM"}
    assert await _edges(memory_db, "REFERENCES_DM") == [("User", "Order", "")]


async def test_depicts_links_a_component_to_the_entity_it_names(memory_db) -> None:
    await add_graph(memory_db, "doc-depicts", {"entity-pg": ("postgresql", "LIBRARY")})
    await _write(
        "doc-depicts",
        "architecture_diagram",
        '{"nodes": [{"name": "PostgreSQL", "node_type": "COMPONENT"}], "edges": []}',
    )
    async with memory_db.factory() as s:
        [depiction] = await s.scalars(select(GraphDiagramDepictionModel))
    assert depiction.entity_id == "entity-pg"


async def test_a_second_write_does_not_duplicate_nodes(memory_db) -> None:
    await add_documents(memory_db, "doc-idem")
    for _ in range(2):
        await _write(
            "doc-idem",
            "architecture_diagram",
            '{"nodes": [{"name": "Cache", "node_type": "COMPONENT"}], "edges": []}',
        )
    assert await _nodes(memory_db, "doc-idem") == [("Cache", "COMPONENT")]
