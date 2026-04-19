"""Tests for GET /search hybrid cross-document search endpoint."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.services.retriever import get_retriever
from app.types import ScoredChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    """Clean up dependency overrides after each test."""
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


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


def test_search_content_type_filter_applied():
    """Content-type filter resolves to document_ids and passes them to retriever."""
    chunks = [_make_chunk("c1", "doc-a", 0.9)]
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=chunks)

    # Two execute calls: content_type filter, then doc metadata
    session = _mock_session(
        [
            [("doc-a",)],  # content_type filter result
            [("doc-a", "Paper A", "paper")],  # doc metadata result
        ]
    )

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=test&content_types=paper")

    assert resp.status_code == 200
    call_args = retriever.retrieve.call_args
    passed_doc_ids = call_args[1].get("document_ids") or call_args[0][1]
    assert "doc-a" in passed_doc_ids


def test_search_content_type_filter_no_matches_returns_empty():
    """Returns empty when content_type filter yields no matching documents."""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[])
    session = _mock_session([[]])  # empty filter result

    app.dependency_overrides[get_db] = _db_override(session)
    app.dependency_overrides[get_retriever] = _retriever_override(retriever)

    with TestClient(app) as client:
        resp = client.get("/search?q=test&content_types=paper")

    assert resp.status_code == 200
    assert resp.json() == {"results": []}
    retriever.retrieve.assert_not_called()


def test_search_missing_query_returns_422():
    """Missing required query param returns 422."""
    with TestClient(app) as client:
        resp = client.get("/search")
    assert resp.status_code == 422


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
    assert match["content_type"] == "paper"
    assert match["section_heading"] == "Introduction"
    assert match["page"] == 1
    assert "text_excerpt" in match
    assert isinstance(match["relevance_score"], float)
