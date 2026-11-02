"""The compiled chat and ingestion graphs have exactly the shape written here.

A diagram of either graph is drawn from these edge lists, so an edge that moves
without this file moving with it fails CI instead of leaving the diagram wrong.
`conditional` marks an edge taken only when its router picks it.
"""

import pytest

from app.runtime.chat_graph import build_chat_graph
from app.workflows.ingestion import ingestion_graph, route_chunker

START, END = "__start__", "__end__"

CHAT_EDGES = {
    (START, "classify_node", False),
    *(
        ("classify_node", strategy, True)
        for strategy in (
            "direct_node",
            "teach_back_node",
            "socratic_node",
            "notes_gap_node",
            "notes_node",
            "summary_node",
            "graph_node",
            "comparative_node",
            "search_node",
        )
    ),
    ("summary_node", "search_node", True),
    ("summary_node", "synthesize_node", True),
    ("graph_node", "search_node", True),
    ("graph_node", "synthesize_node", True),
    ("notes_node", "synthesize_node", False),
    ("comparative_node", "synthesize_node", False),
    ("search_node", "synthesize_node", False),
    ("direct_node", END, False),
    ("teach_back_node", END, False),
    ("socratic_node", END, False),
    ("notes_gap_node", END, False),
    ("synthesize_node", "confidence_gate_node", False),
    ("confidence_gate_node", END, True),
    ("confidence_gate_node", "augment_node", True),
    ("confidence_gate_node", "web_augment_node", True),
    ("augment_node", "synthesize_node", False),
    ("web_augment_node", "synthesize_node", False),
}

_CHUNKERS = (
    "chunk_code",
    "chunk_tech_book",
    "chunk_book",
    "chunk_conversation",
    "chunk_paper",
    "chunk_generic",
)
INGESTION_EDGES = {
    (START, "parse", False),
    ("parse", "classify", False),
    ("classify", "transcribe", True),
    *(("classify", chunker, True) for chunker in _CHUNKERS),
    ("transcribe", "chunk_transcript", False),
    *((chunker, "entity_extract", False) for chunker in ("chunk_transcript", *_CHUNKERS)),
    ("entity_extract", "embed", False),
    ("embed", "keyword_index", False),
    ("keyword_index", "section_summarize", False),
    ("section_summarize", "summarize", False),
    ("summarize", "enrichment_enqueue", False),
    ("enrichment_enqueue", END, False),
}


def _edges(compiled) -> set[tuple[str, str, bool]]:
    return {(e.source, e.target, e.conditional) for e in compiled.get_graph().edges}


def test_chat_graph_shape():
    assert _edges(build_chat_graph().compile()) == CHAT_EDGES


def test_ingestion_graph_shape():
    assert _edges(ingestion_graph) == INGESTION_EDGES


def test_every_ingestion_stage_fails_to_error_finalize():
    """A handler's goto is not an edge, so get_graph() draws error_finalize unconnected."""
    handled = {
        name for name, spec in ingestion_graph.builder.nodes.items() if spec.error_handler_node
    }
    assert handled == {source for source, _, _ in INGESTION_EDGES} - {START}
    assert "error_finalize" in ingestion_graph.builder.nodes


@pytest.mark.parametrize(
    "form, chunker",
    [
        ("source_code", "chunk_code"),
        ("reference", "chunk_tech_book"),
        ("article", "chunk_tech_book"),
        ("prose", "chunk_book"),
        ("script", "chunk_book"),
        ("dialogue", "chunk_conversation"),
        ("paper", "chunk_paper"),
        ("entries", "chunk_generic"),
        (None, "chunk_generic"),
    ],
)
def test_each_form_routes_to_its_chunker(form, chunker):
    assert route_chunker({"format": "txt", "form": form}) == chunker
