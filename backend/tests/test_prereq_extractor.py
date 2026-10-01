"""Tests for PrereqExtractorService (S139).

Unit tests (AC2):
  - test_parse_prereqs_valid: valid JSON returns filtered list
  - test_parse_prereqs_below_threshold: confidence < 0.7 filtered out
  - test_parse_prereqs_invalid_json: non-JSON returns []
  - test_parse_prereqs_empty_array: empty array returns []
  - test_parse_prereqs_with_fences: fenced JSON is parsed correctly

Integration test (AC4, marked slow):
  - test_prereq_edges_written_after_enrich: ingest minimal fixture,
    run PrereqExtractorService.enrich(), assert graph edges exist.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.prereq_extractor import _parse_prereqs

# Pure function tests (AC2)


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


# Integration test: enrich() writes graph edges (AC4)


@pytest.mark.slow
async def test_prereq_edges_written_after_enrich(memory_db):
    """Run PrereqExtractorService.enrich() over one section summary; the
    PREREQUISITE_OF edge it reports is in the graph. Only LiteLLM is mocked."""
    from tests.graph_seed import add_graph

    sm = memory_db.factory
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    entity_closures_id = str(uuid.uuid4())
    entity_decorators_id = str(uuid.uuid4())
    await add_graph(
        memory_db,
        doc_id,
        {
            entity_closures_id: ("closures", "CONCEPT"),
            entity_decorators_id: ("decorators", "CONCEPT"),
        },
    )

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

    patch_target = "app.services.llm.litellm.acompletion"
    with patch(patch_target, new=AsyncMock(return_value=mock_response)):
        svc = PrereqExtractorService()
        count = await svc.enrich(doc_id)

    assert count >= 1, f"Expected at least 1 edge written, got {count}"

    from app.services.graph import get_graph_service

    edges = [
        (e["from_entity"], e["to_entity"])
        for e in await get_graph_service().get_prerequisite_edges_for_document(doc_id)
    ]
    assert len(edges) >= 1, "Expected PREREQUISITE_OF edges, got none"
    # decorators requires closures: (decorators, closures) edge expected
    assert any("closures" in pair for pair in edges), (
        f"Expected 'closures' in edge targets. Got: {edges}"
    )
