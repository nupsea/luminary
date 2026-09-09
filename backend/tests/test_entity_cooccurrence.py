from __future__ import annotations

from app.workflows.ingestion_nodes.entity_extract import write_entity_graph


class _RecordingGraph:
    """Records CO_OCCURS writes and no-ops everything else."""

    def __init__(self) -> None:
        self.co_occurrences: list[tuple[str, str]] = []

    def add_co_occurrence(self, entity_id_a: str, entity_id_b: str, document_id: str) -> None:
        self.co_occurrences.append((entity_id_a, entity_id_b))

    def __getattr__(self, _name: str):
        return lambda *args, **kwargs: None


def _mention(entity_id: str, name: str, chunk_id: str) -> dict:
    return {"id": entity_id, "name": name, "type": "PERSON", "chunk_id": chunk_id}


def test_an_entity_named_twice_in_a_chunk_does_not_co_occur_with_itself():
    """`canonical_entities` carries a row per MENTION. A chunk naming Ulysses twice
    put his id in the list twice, and combinations() paired him with himself: 8,235
    of 74,376 edges in a real library. Weight accumulates on repetition, so the
    self-pair outranks every real one and is the first pair the card generator is
    handed -- which produced "how are the two mentions of Ulysses connected?"."""
    graph = _RecordingGraph()

    write_entity_graph(
        graph,
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

    assert all(a != b for a, b in graph.co_occurrences), graph.co_occurrences
    assert graph.co_occurrences == [("minerva", "ulysses")]


def test_a_pair_is_one_edge_and_not_two_disagreeing_ones():
    """Mention order varies by chunk, so the same two entities were written as
    (minerva, ulysses) and (ulysses, minerva) -- two edges accruing separate
    weights (19.0 and 17.0 in the_odyssey) and two chances to ask one question."""
    graph = _RecordingGraph()

    write_entity_graph(
        graph,
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

    assert graph.co_occurrences == [("minerva", "ulysses"), ("minerva", "ulysses")]
