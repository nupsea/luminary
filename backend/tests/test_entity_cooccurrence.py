from __future__ import annotations

from app.workflows.ingestion_nodes.entity_extract import build_document_graph


def _mention(entity_id: str, name: str, chunk_id: str) -> dict:
    return {"id": entity_id, "name": name, "type": "PERSON", "chunk_id": chunk_id}


def test_an_entity_named_twice_in_a_chunk_does_not_co_occur_with_itself():
    """`canonical_entities` carries a row per MENTION. A chunk naming Ulysses twice
    put his id in the list twice, and combinations() paired him with himself: 8,235
    of 74,376 edges in a real library. Weight accumulates on repetition, so the
    self-pair outranks every real one and is the first pair the card generator is
    handed -- which produced "how are the two mentions of Ulysses connected?"."""
    graph = build_document_graph(
        doc_id="doc-1",
        canonical_entities=[
            _mention("ulysses", "Ulysses", "chunk-1"),
            _mention("ulysses", "Ulysses", "chunk-1"),
            _mention("minerva", "Minerva", "chunk-1"),
        ],
        alias_map={},
        ner_chunks=[],
        chunks=[],
        content_type="prose",
        is_technical=False,
    )

    assert dict(graph.co_occurrences) == {("minerva", "ulysses"): 1}


def test_a_pair_is_one_edge_and_not_two_disagreeing_ones():
    """Mention order varies by chunk, so the same two entities were written as
    (minerva, ulysses) and (ulysses, minerva) -- two edges accruing separate
    weights (19.0 and 17.0 in the_odyssey) and two chances to ask one question."""
    graph = build_document_graph(
        doc_id="doc-1",
        canonical_entities=[
            _mention("ulysses", "Ulysses", "chunk-1"),
            _mention("minerva", "Minerva", "chunk-1"),
            _mention("minerva", "Minerva", "chunk-2"),
            _mention("ulysses", "Ulysses", "chunk-2"),
        ],
        alias_map={},
        ner_chunks=[],
        chunks=[],
        content_type="prose",
        is_technical=False,
    )

    assert dict(graph.co_occurrences) == {("minerva", "ulysses"): 2}
