"""Tests for S225 -- graph-augmented deterministic query expansion.

`_graph_expand` lazy-imports `get_entity_extractor`, `find_canonical`, and
`get_graph_service` (I-5). Patch targets therefore live where they are
defined, not where they are called from inside the helper.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retriever import (
    _GRAPH_EXPAND_MAX_TOKENS,
    HybridRetriever,
    _graph_expand,
)
from app.types import ScoredChunk


def _make_chunk(chunk_id: str, document_id: str = "doc-1") -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=f"text for {chunk_id}",
        section_heading="",
        page=0,
        score=1.0,
        source="vector",
    )


def _mock_extractor(entities: list[dict]) -> MagicMock:
    extractor = MagicMock()
    extractor.extract = MagicMock(return_value=entities)
    return extractor


def _mock_graph_with_aliases(name_to_aliases: dict[str, str]) -> MagicMock:
    """Returns a mock graph service whose _conn.execute mimics Kuzu results.

    name_to_aliases maps lowercased canonical name -> pipe-delimited alias
    string (matches the `Entity.aliases` storage shape).
    """

    class _Result:
        def __init__(self, row: list | None) -> None:
            self._row = row
            self._consumed = False

        def has_next(self) -> bool:
            return self._row is not None and not self._consumed

        def get_next(self) -> list:
            self._consumed = True
            return self._row  # type: ignore[return-value]

    def execute(_query: str, params: dict) -> _Result:
        name = params["name"]
        if name in name_to_aliases:
            return _Result([name_to_aliases[name]])
        return _Result(None)

    graph = MagicMock()
    graph._conn = MagicMock()
    graph._conn.execute = MagicMock(side_effect=execute)
    return graph


@pytest.mark.asyncio
async def test_graph_expand_no_entities_passthrough():
    """No entities detected -> query returned unchanged, Kuzu untouched."""
    extractor = _mock_extractor([])
    graph = MagicMock()

    with (
        patch("app.services.ner.get_entity_extractor", return_value=extractor),
        patch("app.services.graph.get_graph_service", return_value=graph),
    ):
        result = await _graph_expand("Tell me a story.")

    assert result == "Tell me a story."
    graph._conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_graph_expand_kuzu_unreachable_fail_soft():
    """Kuzu execute raising returns query unchanged -- no exception propagates."""
    extractor = _mock_extractor([{"name": "holmes", "type": "PERSON"}])
    graph = MagicMock()
    graph._conn.execute.side_effect = RuntimeError("kuzu down")

    with (
        patch("app.services.ner.get_entity_extractor", return_value=extractor),
        patch("app.services.graph.get_graph_service", return_value=graph),
    ):
        result = await _graph_expand("What did Mr. Holmes say?")

    # Aliases lookup failed but canonical was still appended.
    assert result.startswith("What did Mr. Holmes say?")
    assert "holmes" in result.lower()


@pytest.mark.asyncio
async def test_graph_expand_resolves_aliases():
    """Canonical + aliases get appended to the query."""
    extractor = _mock_extractor([{"name": "sherlock holmes", "type": "PERSON"}])
    graph = _mock_graph_with_aliases(
        {"sherlock holmes": "Holmes|Mr. Holmes|detective"}
    )

    with (
        patch("app.services.ner.get_entity_extractor", return_value=extractor),
        patch("app.services.graph.get_graph_service", return_value=graph),
    ):
        result = await _graph_expand("Who is the detective in the story?")

    # Canonical name plus the alias surface forms are appended to the query.
    assert "sherlock" in result.lower()
    assert "Mr." in result or "mr." in result.lower()
    assert "Holmes" in result or "holmes" in result.lower()


@pytest.mark.asyncio
async def test_graph_expand_token_cap():
    """Total appended tokens are capped at _GRAPH_EXPAND_MAX_TOKENS."""
    # 3 entities, each with many alias tokens -> would otherwise blow past 30.
    extractor = _mock_extractor(
        [
            {"name": f"name{i}", "type": "PERSON"}
            for i in range(3)
        ]
    )
    long_aliases = "|".join([f"alias{i}_{j} extra word" for i in range(3) for j in range(5)])
    graph = _mock_graph_with_aliases(
        {f"name{i}": long_aliases for i in range(3)}
    )

    with (
        patch("app.services.ner.get_entity_extractor", return_value=extractor),
        patch("app.services.graph.get_graph_service", return_value=graph),
    ):
        result = await _graph_expand("query")

    appended = result[len("query "):].split()
    assert len(appended) <= _GRAPH_EXPAND_MAX_TOKENS


@pytest.mark.asyncio
async def test_graph_expand_extractor_failure_fail_soft():
    """Any exception in the helper falls back to the original query."""
    extractor = MagicMock()
    extractor.extract = MagicMock(side_effect=RuntimeError("gliner failed"))

    with patch("app.services.ner.get_entity_extractor", return_value=extractor):
        result = await _graph_expand("anything")

    assert result == "anything"


@pytest.mark.asyncio
async def test_retrieve_graph_expand_false_bypasses_helper():
    """retrieve(graph_expand=False) never calls _graph_expand."""
    retriever = HybridRetriever()

    with (
        patch(
            "app.services.retriever._graph_expand", new=AsyncMock(return_value="EXPANDED")
        ) as expand_mock,
        patch.object(retriever, "vector_search", return_value=[_make_chunk("c1")]),
        patch.object(
            retriever, "keyword_search", new=AsyncMock(return_value=[_make_chunk("c2")])
        ),
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        await retriever.retrieve(
            "What happened?", document_ids=["doc-1"], k=5, graph_expand=False
        )

    expand_mock.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_graph_expand_true_passes_expanded_query():
    """retrieve(graph_expand=True) feeds the expanded query into both searches."""
    retriever = HybridRetriever()

    with (
        patch(
            "app.services.retriever._graph_expand",
            new=AsyncMock(return_value="What happened? sherlock holmes"),
        ),
        patch.object(
            retriever, "vector_search", return_value=[_make_chunk("c1")]
        ) as vec_mock,
        patch.object(
            retriever, "keyword_search", new=AsyncMock(return_value=[_make_chunk("c2")])
        ) as kw_mock,
        patch("app.services.retriever._expand_context", new=AsyncMock(side_effect=lambda r, k: r)),
    ):
        await retriever.retrieve(
            "What happened?", document_ids=["doc-1"], k=5, graph_expand=True
        )

    assert vec_mock.call_args[0][0] == "What happened? sherlock holmes"
    assert kw_mock.call_args[0][0] == "What happened? sherlock holmes"
