"""A node that raises ends ingestion at error_finalize, never as a complete document."""

import pytest

from app.workflows import ingestion
from app.workflows.ingestion_nodes.embed import VectorCountMismatch

NODES = [
    "parse",
    "classify",
    "transcribe",
    "chunk_transcript",
    "chunk_code",
    "chunk_tech_book",
    "chunk_book",
    "chunk_conversation",
    "chunk_paper",
    "chunk_generic",
    "entity_extract",
    "embed",
    "keyword_index",
    "section_summarize",
    "summarize",
    "enrichment_enqueue",
    "error_finalize",
]


def _stub_graph(monkeypatch, fail: dict[str, list[Exception]]):
    """Every node records its visit; a node in `fail` raises its listed errors in turn."""
    visited: list[str] = []

    def stub(name):
        async def node(state):
            visited.append(name)
            if fail.get(name):
                raise fail[name].pop(0)
            return {}

        return node

    for name in NODES:
        monkeypatch.setattr(ingestion, f"{name}_node", stub(name))
    return ingestion._build_graph(), visited


@pytest.mark.parametrize("failing", ["parse", "chunk_generic", "embed", "section_summarize"])
async def test_a_raising_node_goes_to_error_finalize(monkeypatch, failing):
    graph, visited = _stub_graph(monkeypatch, {failing: [RuntimeError("boom")]})

    result = await graph.ainvoke({"document_id": "d", "format": "txt", "status": "parsing"})

    assert visited[-2:] == [failing, "error_finalize"]
    assert result["status"] == "error"
    assert result["error"] == "boom"


async def test_a_short_vector_write_is_retried_once(monkeypatch):
    graph, visited = _stub_graph(monkeypatch, {"embed": [VectorCountMismatch("short")]})

    await graph.ainvoke({"document_id": "d", "format": "txt", "status": "parsing"})

    assert visited.count("embed") == 2
    assert visited[-1] == "enrichment_enqueue"


async def test_a_vector_write_short_twice_fails_the_document(monkeypatch):
    errors = [VectorCountMismatch("short"), VectorCountMismatch("still short")]
    graph, visited = _stub_graph(monkeypatch, {"embed": errors})

    result = await graph.ainvoke({"document_id": "d", "format": "txt", "status": "parsing"})

    assert visited[-3:] == ["embed", "embed", "error_finalize"]
    assert result["error"] == "still short"


async def test_any_other_embed_error_is_not_retried(monkeypatch):
    graph, visited = _stub_graph(monkeypatch, {"embed": [OSError("disk")]})

    await graph.ainvoke({"document_id": "d", "format": "txt", "status": "parsing"})

    assert visited.count("embed") == 1
    assert visited[-1] == "error_finalize"
