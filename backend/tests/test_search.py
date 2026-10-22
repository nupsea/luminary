"""Tests for GET /search hybrid cross-document search endpoint."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.services.retriever import get_retriever
from app.types import ScoredChunk

# Helpers


def _make_chunk(chunk_id: str, document_id: str, score: float = 0.8) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text="Sample text for chunk " + chunk_id,
        section_heading="Introduction",
        page=1,
        score=score,
        source="both",
    )


def _mock_session(fetchall_sequence: list[list]) -> AsyncMock:
    """Build a mock async session.

    Each item in fetchall_sequence is returned by successive execute() calls.
    """
    mock_session = AsyncMock()
    results = []
    for rows in fetchall_sequence:
        r = MagicMock()
        r.fetchall.return_value = rows
        r.all.return_value = rows
        r.scalars.return_value = [row[0] for row in rows]
        results.append(r)
    if len(results) == 1:
        mock_session.execute = AsyncMock(return_value=results[0])
    else:
        mock_session.execute = AsyncMock(side_effect=results)
    return mock_session


def _db_override(session: AsyncMock):
    """Return an async generator function suitable for dependency_overrides[get_db]."""

    async def _override():
        yield session

    return _override


def _retriever_override(retriever: MagicMock):
    return lambda: retriever


# Fixtures


@pytest.fixture(autouse=True)
def clear_overrides():
    """Clean up dependency overrides after each test."""
    yield
    app.dependency_overrides.clear()


# Tests


def test_search_returns_grouped_results():
    """Endpoint returns results grouped by document."""
    chunks = [
        _make_chunk("c1", "doc-a", 0.9),
        _make_chunk("c2", "doc-a", 0.7),
        _make_chunk("c3", "doc-b", 0.8),
    ]
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=chunks)

    session = _mock_session([[("doc-a", "Paper A", "paper"), ("doc-b", "Paper B", "notes")]])

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=einstein")

    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    groups = {g["document_id"]: g for g in data["results"]}
    assert "doc-a" in groups
    assert "doc-b" in groups
    assert len(groups["doc-a"]["matches"]) == 2
    assert len(groups["doc-b"]["matches"]) == 1


def test_search_empty_when_no_chunks():
    """Returns empty results when retriever finds nothing."""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[])
    session = _mock_session([[]])

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=nonexistent")

    assert resp.status_code == 200
    assert resp.json() == {"results": []}


def test_search_kind_filter_applied():
    """A kind filter resolves to document_ids and passes them to retriever."""
    chunks = [_make_chunk("c1", "doc-a", 0.9)]
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=chunks)

    # Two execute calls: kind filter, then doc metadata
    session = _mock_session(
        [
            [("doc-a",)],  # kind filter result
            [("doc-a", "Paper A", "paper")],  # doc metadata result
        ]
    )

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=test&kinds=paper")

    assert resp.status_code == 200
    call_args = retriever.retrieve.call_args
    passed_doc_ids = call_args[1].get("document_ids") or call_args[0][1]
    assert "doc-a" in passed_doc_ids


def test_search_kind_filter_no_matches_returns_empty():
    """Returns empty when the kind filter yields no matching documents."""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[])
    session = _mock_session([[]])  # empty filter result

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=test&kinds=paper")

    assert resp.status_code == 200
    assert resp.json() == {"results": []}
    retriever.retrieve.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("/search", id="search_missing_query_returns_422"),
        pytest.param(
            "/search?q=test&rerank=true&rerank_depth=500",
            id="search_rerank_depth_over_cap_returns_422",
        ),
        pytest.param("/search?q=test&limit=201", id="search_limit_over_cap_returns_422"),
    ],
)
def test_search_rejects_invalid_query(url):
    with TestClient(app) as client:
        resp = client.get(url)
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "url, flag, expected",
    [
        pytest.param(
            "/search?q=test&hyde=true",
            "hyde",
            True,
            id="search_hyde_flag_passes_through_to_retriever",
        ),
        pytest.param("/search?q=test", "hyde", False, id="search_hyde_default_false"),
        pytest.param(
            "/search?q=test&rerank=true",
            "rerank",
            True,
            id="search_rerank_flag_passes_through_to_retriever",
        ),
        pytest.param("/search?q=test", "rerank", False, id="search_rerank_default_false"),
    ],
)
def test_search_flag_passes_through_to_retriever(url, flag, expected):
    chunks = [_make_chunk("c1", "doc-a", 0.9)]
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=chunks)
    session = _mock_session([[("doc-a", "Paper A", "paper")]])

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get(url)

    assert resp.status_code == 200
    call_kwargs = retriever.retrieve.call_args.kwargs
    assert call_kwargs.get(flag) is expected


def test_search_rerank_depth_and_threshold_pass_through():
    """?rerank_depth / ?rerank_threshold forward to retriever.retrieve (L2 funnel)."""
    chunks = [_make_chunk("c1", "doc-a", 0.9)]
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=chunks)
    session = _mock_session([[("doc-a", "Paper A", "paper")]])

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=test&rerank=true&rerank_depth=100&rerank_threshold=0.5")

    assert resp.status_code == 200
    call_kwargs = retriever.retrieve.call_args.kwargs
    assert call_kwargs.get("rerank_depth") == 100
    assert call_kwargs.get("rerank_threshold") == 0.5


def test_search_limit_200_passes_through():
    """limit=200 is accepted and forwarded as k -- the eval pool-recall arm needs it."""
    chunks = [_make_chunk("c1", "doc-a", 0.9)]
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=chunks)
    session = _mock_session([[("doc-a", "Paper A", "paper")]])

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=test&limit=200")

    assert resp.status_code == 200
    assert retriever.retrieve.call_args.kwargs.get("k") == 200


def test_search_expand_context_flag_passes_through():
    """?expand_context=false forwards to retriever.retrieve (eval pool-recall arm)."""
    chunks = [_make_chunk("c1", "doc-a", 0.9)]
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=chunks)
    session = _mock_session([[("doc-a", "Paper A", "paper")]])

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=test&expand_context=false")

    assert resp.status_code == 200
    assert retriever.retrieve.call_args.kwargs.get("expand_context") is False


def test_search_result_fields():
    """Result items contain all expected fields with correct types."""
    chunks = [_make_chunk("c1", "doc-a", 0.876)]
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=chunks)

    session = _mock_session([[("doc-a", "Paper A", "paper")]])

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=test")

    assert resp.status_code == 200
    match = resp.json()["results"][0]["matches"][0]
    assert match["chunk_id"] == "c1"
    assert match["document_id"] == "doc-a"
    assert match["document_title"] == "Paper A"
    assert match["kind"] == "paper"
    assert match["section_heading"] == "Introduction"
    assert match["page"] == 1
    assert "text_excerpt" in match
    assert isinstance(match["relevance_score"], float)
    assert match["global_rank"] == 1


def test_search_global_rank_restores_retriever_order_across_groups():
    """global_rank is 1-indexed retriever order, contiguous across the grouped
    response, and skips chunks dropped for missing document metadata -- so a
    client flattening groups can sort by it to recover the true ranking."""
    chunks = [
        _make_chunk("c1", "doc-a", 0.95),
        _make_chunk("c2", "doc-b", 0.90),
        _make_chunk("c3", "doc-ghost", 0.85),  # no metadata row -> dropped
        _make_chunk("c4", "doc-a", 0.60),
    ]
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=chunks)

    session = _mock_session([[("doc-a", "Paper A", "paper"), ("doc-b", "Paper B", "notes")]])

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=test")

    assert resp.status_code == 200
    flat = [m for g in resp.json()["results"] for m in g["matches"]]
    by_rank = sorted(flat, key=lambda m: m["global_rank"])
    assert [m["global_rank"] for m in by_rank] == [1, 2, 3]
    assert [m["chunk_id"] for m in by_rank] == ["c1", "c2", "c4"]
