"""Tests for PrereqExtractorService (S139).

Unit tests (AC2):
  - test_parse_prereqs_valid: valid JSON returns filtered list
  - test_parse_prereqs_below_threshold: confidence < 0.7 filtered out
  - test_parse_prereqs_invalid_json: non-JSON returns []
  - test_parse_prereqs_empty_array: empty array returns []
  - test_parse_prereqs_with_fences: fenced JSON is parsed correctly

Integration test (AC4, marked slow):
  - test_prereq_edges_written_after_enrich: ingest minimal fixture,
    run PrereqExtractorService.enrich(), assert Kuzu edges exist.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.services.prereq_extractor import _parse_prereqs

# ---------------------------------------------------------------------------
# Pure function tests (AC2)
# ---------------------------------------------------------------------------


def test_parse_prereqs_valid():
    """Valid JSON with confidence >= 0.7 is returned."""
    raw = '[{"requires": "closures", "required_by": "decorators", "confidence": 0.85}]'
    result = _parse_prereqs(raw)
    assert len(result) == 1
    assert result[0]["requires"] == "closures"
    assert result[0]["required_by"] == "decorators"
    assert result[0]["confidence"] == pytest.approx(0.85)


def test_parse_prereqs_below_threshold():
    """Items with confidence < 0.7 are filtered out."""
    raw = '[{"requires": "closures", "required_by": "decorators", "confidence": 0.5}]'
    result = _parse_prereqs(raw)
    assert result == []


def test_parse_prereqs_at_threshold():
    """Items with confidence == 0.7 are included."""
    raw = '[{"requires": "functions", "required_by": "closures", "confidence": 0.7}]'
    result = _parse_prereqs(raw)
    assert len(result) == 1


def test_parse_prereqs_invalid_json():
    """Non-JSON input returns empty list (non-fatal)."""
    result = _parse_prereqs("not json at all")
    assert result == []


def test_parse_prereqs_empty_array():
    """Empty JSON array returns empty list."""
    result = _parse_prereqs("[]")
    assert result == []


def test_parse_prereqs_with_fences():
    """Markdown-fenced JSON is stripped and parsed correctly."""
    raw = '```json\n[{"requires": "closures", "required_by": "decorators", "confidence": 0.9}]\n```'
    result = _parse_prereqs(raw)
    assert len(result) == 1
    assert result[0]["requires"] == "closures"


def test_parse_prereqs_multiple_items():
    """Multiple items are returned, below-threshold ones filtered."""
    raw = (
        "["
        '{"requires": "closures", "required_by": "decorators", "confidence": 0.9},'
        '{"requires": "loops", "required_by": "comprehensions", "confidence": 0.4},'
        '{"requires": "functions", "required_by": "closures", "confidence": 0.8}'
        "]"
    )
    result = _parse_prereqs(raw)
    assert len(result) == 2
    names = [r["requires"] for r in result]
    assert "closures" in names
    assert "functions" in names
    assert "loops" not in names


def test_parse_prereqs_missing_fields():
    """Items missing required fields are skipped."""
    raw = '[{"requires": "closures", "confidence": 0.9}]'  # missing required_by
    result = _parse_prereqs(raw)
    assert result == []


# ---------------------------------------------------------------------------
# Integration test: enrich() writes Kuzu edges (AC4)
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_prereq_edges_written_after_enrich(tmp_path):
    """Ingest a minimal fixture, run PrereqExtractorService.enrich(),
    assert PREREQUISITE_OF edges exist in Kuzu.

    Mocks litellm to return a fixed prerequisite JSON per section call.
    Uses real Kuzu (tmp_path) and real SQLite (in-memory).
    Only mocks LiteLLM (external system boundary).
    """
    import os

    # Point DATA_DIR to tmp_path so Kuzu uses an isolated DB
    os.environ["DATA_DIR"] = str(tmp_path)
    from app.config import get_settings

    get_settings.cache_clear()
    graph_module._graph_service = None

    # Create in-memory SQLite
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    sm = async_sessionmaker(engine, expire_on_commit=False)
    db_module._engine = engine
    db_module._session_factory = sm

    await create_all_tables(engine)

    # Seed: Document node, Entity nodes, SectionSummaryModel
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())

    # Seed graph nodes
    from app.services.graph import get_graph_service

    gv = get_graph_service()
    gv.upsert_document(doc_id, "Python Tutorial", "tech_book")

    entity_closures_id = str(uuid.uuid4())
    entity_decorators_id = str(uuid.uuid4())
    gv.upsert_entity(entity_closures_id, "closures", "CONCEPT")
    gv.upsert_entity(entity_decorators_id, "decorators", "CONCEPT")
    gv.add_mention(entity_closures_id, doc_id)
    gv.add_mention(entity_decorators_id, doc_id)

    # Seed SectionSummaryModel
    from app.models import SectionSummaryModel

    async with sm() as session:
        summary = SectionSummaryModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            section_id=section_id,
            heading="Decorators",
            content="This section covers decorators. Reader must already understand closures.",
            unit_index=1,
        )
        session.add(summary)
        await session.commit()

    # Mock litellm.acompletion to return a fixed prereq JSON
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[
        0
    ].message.content = '[{"requires": "closures", "required_by": "decorators", "confidence": 0.9}]'

    from app.services.prereq_extractor import PrereqExtractorService

    patch_target = "app.services.prereq_extractor.litellm.acompletion"
    with patch(patch_target, new=AsyncMock(return_value=mock_response)):
        svc = PrereqExtractorService()
        count = await svc.enrich(doc_id)

    assert count >= 1, f"Expected at least 1 edge written, got {count}"

    # Query Kuzu: assert PREREQUISITE_OF edge exists
    result = gv._conn.execute(
        "MATCH (a:Entity)-[r:PREREQUISITE_OF]->(b:Entity)"
        " WHERE r.document_id = $did RETURN a.name, b.name",
        {"did": doc_id},
    )
    edges = []
    while result.has_next():
        row = result.get_next()
        edges.append((row[0], row[1]))

    assert len(edges) >= 1, f"Expected PREREQUISITE_OF edges in Kuzu, got none. Edges: {edges}"
    # decorators requires closures: (decorators, closures) edge expected
    assert any("closures" in pair for pair in edges), (
        f"Expected 'closures' in edge targets. Got: {edges}"
    )
