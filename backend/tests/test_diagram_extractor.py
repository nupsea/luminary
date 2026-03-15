"""Tests for DiagramExtractorService (S136).

Unit tests use a real Kuzu in-memory database (via tmp_path) and mocked LiteLLM.
No SQLite DB required — ImageModel rows are constructed in-memory.

Test inventory:
  1. test_build_prompt_architecture_contains_component  -- _build_prompt includes COMPONENT keyword
  2. test_build_prompt_sequence_contains_actor          -- _build_prompt includes ACTOR keyword
  3. test_parse_llm_response_valid_json                 -- _parse_llm_response parses plain JSON
  4. test_parse_llm_response_fenced_json                -- _parse_llm_response strips markdown fences
  5. test_parse_llm_response_invalid_json               -- _parse_llm_response raises ValueError
  6. test_architecture_diagram_extraction               -- COMPONENT nodes + CONNECTS_TO edges created
  7. test_sequence_diagram_routing                      -- ACTOR nodes + SENDS_TO edges created
  8. test_er_diagram_routing                            -- ENTITY_DM nodes + REFERENCES_DM edges created
  9. test_depicts_linkage                               -- DEPICTS edge from COMPONENT to Entity if name matches
 10. test_idempotency                                   -- calling _write_to_kuzu twice does not double node count
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.diagram_extractor import (
    DiagramExtractorService,
    _build_prompt,
    _parse_llm_response,
)
from app.services.graph import KuzuService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_kuzu(tmp_path: Path) -> KuzuService:
    """Return a fresh KuzuService backed by tmp_path."""
    return KuzuService(str(tmp_path))


def _make_image_model(
    *,
    image_id: str,
    document_id: str,
    image_type: str,
    description: str,
):
    """Return a minimal mock object shaped like ImageModel."""
    m = MagicMock()
    m.id = image_id
    m.document_id = document_id
    m.image_type = image_type
    m.description = description
    return m


def _mock_litellm(json_text: str):
    """Return an AsyncMock for litellm.acompletion that returns json_text."""
    choice = MagicMock()
    choice.message.content = json_text
    response = MagicMock()
    response.choices = [choice]
    return AsyncMock(return_value=response)


# ---------------------------------------------------------------------------
# Pure-function tests (no DB, no LLM)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Async service tests (real Kuzu, mocked LiteLLM + SQLAlchemy)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_architecture_diagram_extraction(tmp_path: Path) -> None:
    """COMPONENT nodes and CONNECTS_TO edges are created for architecture_diagram."""
    kuzu = _make_kuzu(tmp_path)

    llm_json = (
        '{"nodes": ['
        '{"name": "Service A", "node_type": "COMPONENT"},'
        '{"name": "Service B", "node_type": "COMPONENT"}'
        '], "edges": ['
        '{"from": "Service A", "to": "Service B",'
        '"edge_type": "CONNECTS_TO", "label": "calls"}'
        ']}'
    )

    with patch("app.services.graph.get_graph_service", return_value=kuzu):
        svc = DiagramExtractorService()
        parsed = _parse_llm_response(llm_json)
        await svc._write_to_kuzu(
            document_id="doc-001",
            image_id="img-001",
            image_type="architecture_diagram",
            nodes=parsed["nodes"],
            edges=parsed["edges"],
        )

    # Verify DiagramNode rows exist
    result = kuzu._conn.execute(
        "MATCH (n:DiagramNode) WHERE n.document_id = 'doc-001' RETURN n.name, n.node_type"
    )
    names = []
    while result.has_next():
        row = result.get_next()
        names.append((row[0], row[1]))
    assert ("Service A", "COMPONENT") in names
    assert ("Service B", "COMPONENT") in names

    # Verify CONNECTS_TO edge exists
    edge_result = kuzu._conn.execute(
        "MATCH (a:DiagramNode)-[r:CONNECTS_TO]->(b:DiagramNode)"
        " WHERE r.document_id = 'doc-001'"
        " RETURN a.name, b.name"
    )
    edges = []
    while edge_result.has_next():
        row = edge_result.get_next()
        edges.append((row[0], row[1]))
    assert ("Service A", "Service B") in edges


@pytest.mark.asyncio
async def test_sequence_diagram_routing(tmp_path: Path) -> None:
    """ACTOR nodes and SENDS_TO edges are created for sequence_diagram."""
    kuzu = _make_kuzu(tmp_path)

    llm_json = (
        '{"nodes": ['
        '{"name": "Client", "node_type": "ACTOR"},'
        '{"name": "Server", "node_type": "ACTOR"}'
        '], "edges": ['
        '{"from": "Client", "to": "Server", "edge_type": "SENDS_TO", "message": "POST /login"}'
        ']}'
    )

    with patch("app.services.graph.get_graph_service", return_value=kuzu):
        svc = DiagramExtractorService()
        parsed = _parse_llm_response(llm_json)
        await svc._write_to_kuzu(
            document_id="doc-seq",
            image_id="img-seq",
            image_type="sequence_diagram",
            nodes=parsed["nodes"],
            edges=parsed["edges"],
        )

    result = kuzu._conn.execute(
        "MATCH (n:DiagramNode) WHERE n.document_id = 'doc-seq' RETURN n.name, n.node_type"
    )
    names = []
    while result.has_next():
        row = result.get_next()
        names.append((row[0], row[1]))
    assert ("Client", "ACTOR") in names
    assert ("Server", "ACTOR") in names

    edge_result = kuzu._conn.execute(
        "MATCH (a:DiagramNode)-[r:SENDS_TO]->(b:DiagramNode)"
        " WHERE r.document_id = 'doc-seq'"
        " RETURN a.name, b.name, r.message"
    )
    edges = []
    while edge_result.has_next():
        row = edge_result.get_next()
        edges.append((row[0], row[1], row[2]))
    assert ("Client", "Server", "POST /login") in edges


@pytest.mark.asyncio
async def test_er_diagram_routing(tmp_path: Path) -> None:
    """ENTITY_DM nodes and REFERENCES_DM edges are created for er_diagram."""
    kuzu = _make_kuzu(tmp_path)

    llm_json = (
        '{"nodes": ['
        '{"name": "User", "node_type": "ENTITY_DM"},'
        '{"name": "Order", "node_type": "ENTITY_DM"}'
        '], "edges": ['
        '{"from": "User", "to": "Order", "edge_type": "REFERENCES_DM"}'
        ']}'
    )

    with patch("app.services.graph.get_graph_service", return_value=kuzu):
        svc = DiagramExtractorService()
        parsed = _parse_llm_response(llm_json)
        await svc._write_to_kuzu(
            document_id="doc-er",
            image_id="img-er",
            image_type="er_diagram",
            nodes=parsed["nodes"],
            edges=parsed["edges"],
        )

    node_result = kuzu._conn.execute(
        "MATCH (n:DiagramNode) WHERE n.document_id = 'doc-er' RETURN n.node_type"
    )
    types = []
    while node_result.has_next():
        row = node_result.get_next()
        types.append(row[0])
    assert "ENTITY_DM" in types

    edge_result = kuzu._conn.execute(
        "MATCH (a:DiagramNode)-[r:REFERENCES_DM]->(b:DiagramNode)"
        " WHERE r.document_id = 'doc-er'"
        " RETURN a.name, b.name"
    )
    edges = []
    while edge_result.has_next():
        row = edge_result.get_next()
        edges.append((row[0], row[1]))
    assert ("User", "Order") in edges


@pytest.mark.asyncio
async def test_depicts_linkage(tmp_path: Path) -> None:
    """DEPICTS edge is created from COMPONENT node to existing Entity with matching name."""
    kuzu = _make_kuzu(tmp_path)

    # Pre-insert an Entity node named 'postgresql' with a MENTIONED_IN relationship
    entity_id = "entity-postgres-001"
    doc_id = "doc-depicts"
    kuzu.upsert_entity(entity_id, "postgresql", "LIBRARY")
    kuzu.upsert_document(doc_id, "Test Doc", "text")
    kuzu.add_mention(entity_id, doc_id)

    # Extract a COMPONENT node named "PostgreSQL" -- should match entity 'postgresql'
    llm_json = (
        '{"nodes": [{"name": "PostgreSQL", "node_type": "COMPONENT"}], "edges": []}'
    )

    with patch("app.services.graph.get_graph_service", return_value=kuzu):
        svc = DiagramExtractorService()
        parsed = _parse_llm_response(llm_json)
        await svc._write_to_kuzu(
            document_id=doc_id,
            image_id="img-depicts",
            image_type="architecture_diagram",
            nodes=parsed["nodes"],
            edges=parsed["edges"],
        )

    # Verify DEPICTS edge exists
    depicts_result = kuzu._conn.execute(
        "MATCH (d:DiagramNode)-[r:DEPICTS]->(e:Entity)"
        f" WHERE r.document_id = '{doc_id}'"
        " RETURN d.name, e.name"
    )
    depicts = []
    while depicts_result.has_next():
        row = depicts_result.get_next()
        depicts.append((row[0], row[1]))
    assert ("PostgreSQL", "postgresql") in depicts


@pytest.mark.asyncio
async def test_idempotency(tmp_path: Path) -> None:
    """Calling _write_to_kuzu twice does not duplicate DiagramNode rows."""
    kuzu = _make_kuzu(tmp_path)

    llm_json = (
        '{"nodes": [{"name": "Cache", "node_type": "COMPONENT"}], "edges": []}'
    )

    with patch("app.services.graph.get_graph_service", return_value=kuzu):
        svc = DiagramExtractorService()
        parsed = _parse_llm_response(llm_json)
        for _ in range(2):
            await svc._write_to_kuzu(
                document_id="doc-idem",
                image_id="img-idem",
                image_type="architecture_diagram",
                nodes=parsed["nodes"],
                edges=parsed["edges"],
            )

    count_result = kuzu._conn.execute(
        "MATCH (n:DiagramNode) WHERE n.document_id = 'doc-idem' RETURN count(*)"
    )
    count = count_result.get_next()[0] if count_result.has_next() else 0
    assert count == 1, f"Expected 1 DiagramNode, got {count}"
