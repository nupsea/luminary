"""A node that reports an error ends ingestion as an error, never as a complete document."""

import pytest

from app.workflows import ingestion

NODES = [
    "parse",
    "classify",
    "transcribe",
    "chunk",
    "entity_extract",
    "embed",
    "keyword_index",
    "section_summarize",
    "summarize",
    "enrichment_enqueue",
    "error_finalize",
]


@pytest.mark.parametrize("failing", ["parse", "chunk", "embed"])
async def test_an_error_status_goes_to_error_finalize(monkeypatch, failing):
    visited: list[str] = []

    def stub(name):
        async def node(state):
            visited.append(name)
            return {**state, "status": "error" if name == failing else "ok"}

        return node

    for name in NODES:
        monkeypatch.setattr(ingestion, f"{name}_node", stub(name))

    await ingestion._build_graph().ainvoke({"document_id": "d", "status": "parsing"})

    assert visited[-2:] == [failing, "error_finalize"]
