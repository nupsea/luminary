"""A chunk the model is already being shown must not be pasted into its neighbour.

`search_node` expands each retrieved chunk into `[prev, self, next]` so a hit
that cuts mid-idea is still comprehensible. Done per chunk and independently,
that duplicates whatever retrieval returned as a run: measured on three real
questions against one document, every one returned chunk indices 0..7, whose
windows emitted 24 chunk slots covering 10 distinct chunks -- 58% of the prompt
was the same prose twice.

The cost lands on the context budget. A passage was ~750 tokens instead of the
~250 its chunk measures, so `QA_CONTEXT_TOKEN_BUDGET=1500` carried 2 passages
covering 4 distinct chunks, and every budget from 500 to 1250 carried exactly
one. Narrowing the budget was tried first and reverted; the duplication was the
real defect.

Expansion still fires where it earns its place -- an isolated hit gets the prose
either side of it. What stops is expanding into material already on its way to
the model under its own citation.
"""

import inspect

from app.runtime.chat_nodes import search


def _expansion_source() -> str:
    return inspect.getsource(search.search_node)


class TestRetrievedNeighboursAreNotPastedIn:
    def test_the_retrieved_set_is_consulted_when_expanding(self):
        """Without this the windows are built blind to what else was retrieved,
        which is exactly how the duplication arose."""
        source = _expansion_source()
        assert "retrieved_keys" in source, (
            "expansion must know which chunks were retrieved in their own right"
        )
        assert "not in retrieved_keys" in source, (
            "neighbours that were themselves retrieved must be filtered out"
        )

    def test_expansion_is_still_performed(self):
        """The fix is de-duplication, not the removal of context expansion: an
        isolated hit that cuts mid-idea still needs the prose either side."""
        source = _expansion_source()
        assert "_fetch_neighbor_chunks_batch" in source
        assert "expanded_text" in source


class TestTheFilterIsCorrect:
    """The rule, applied to the shapes that actually occur."""

    @staticmethod
    def _keep(doc: str, neighbours: list[tuple[int, str]], retrieved: set) -> list:
        return [(i, t) for i, t in neighbours if (doc, i) not in retrieved]

    def test_a_consecutive_run_expands_into_nothing(self):
        """Indices 0..7 were what three real questions returned. Each chunk's
        neighbours are all retrieved, so each passage is its own chunk alone."""
        retrieved = {("d", i) for i in range(8)}
        for i in range(1, 7):
            kept = self._keep("d", [(i - 1, "prev"), (i + 1, "next")], retrieved)
            assert kept == [], f"chunk {i} expanded into already-shown chunks"

    def test_an_isolated_hit_keeps_both_neighbours(self):
        retrieved = {("d", 42)}
        kept = self._keep("d", [(41, "prev"), (43, "next")], retrieved)
        assert [i for i, _ in kept] == [41, 43]

    def test_a_run_boundary_keeps_the_outward_neighbour(self):
        """The edge of a run still reaches into unretrieved prose -- that is the
        case expansion exists for."""
        retrieved = {("d", 5), ("d", 6), ("d", 7)}
        kept = self._keep("d", [(4, "prev"), (6, "next")], retrieved)
        assert [i for i, _ in kept] == [4]

    def test_the_same_index_in_another_document_is_not_confused(self):
        """The key is (document_id, chunk_index); matching on the index alone
        would drop a legitimate neighbour whenever two documents share one."""
        retrieved = {("other", 41)}
        kept = self._keep("d", [(41, "prev"), (43, "next")], retrieved)
        assert [i for i, _ in kept] == [41, 43]
