"""End-to-end integration test for Time Machine: full pipeline from ingest to all 5 features.

Marked @pytest.mark.slow — not part of default make test.
Run alone:
    cd backend && uv run pytest tests/test_e2e_book.py -v -m slow --timeout=700
Run with all book tests (shared fixture, each book ingested once):
    make test-books-all

Relies on all_books_ingested session fixture from conftest_books.py which is
loaded via pytest_plugins below.  When run in the same session as
test_diagnostics.py and test_book_content.py, all 3 books are ingested exactly
once.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import app.database as db_module
from app.main import app
from app.models import DocumentModel
from app.services.graph import get_graph_service
from app.services.retriever import get_retriever

# Load shared session fixture
pytest_plugins = ["tests.conftest_books"]

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------


async def _async_iter(items):
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# TestTimeMachineEndToEnd
# ---------------------------------------------------------------------------


class TestTimeMachineEndToEnd:
    """Full pipeline verification for The Time Machine."""

    @pytest.fixture(autouse=True)
    def setup(self, all_books_ingested):
        self.doc_id: str = all_books_ingested["The Time Machine"]["doc_id"]
        self.elapsed: float = all_books_ingested["The Time Machine"]["elapsed_seconds"]

    # ------------------------------------------------------------------
    # Ingest verification
    # ------------------------------------------------------------------

    async def test_ingest_completed(self):
        """Stage must be 'complete' after ingestion."""
        async with db_module._session_factory() as session:
            doc = await session.get(DocumentModel, self.doc_id)
        assert doc is not None, "Document not found in DB"
        assert doc.stage == "complete", f"Expected stage='complete', got '{doc.stage}'"

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def test_diagnostics_counts(self):
        """GET /documents/{id}/diagnostics returns expected pipeline counts."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/documents/{self.doc_id}/diagnostics")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        d = resp.json()
        assert d["chunk_count"] >= 100, f"chunk_count={d['chunk_count']} < 100"
        assert d["fts_count"] >= 100, f"fts_count={d['fts_count']} < 100"
        assert d["vector_count"] >= 50, f"vector_count={d['vector_count']} < 50"
        assert d["entity_count"] >= 20, f"entity_count={d['entity_count']} < 20"
        assert d["edge_count"] >= 10, f"edge_count={d['edge_count']} < 10"

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    async def test_vector_search(self):
        """Vector search for 'time traveller' returns >= 3 non-empty results."""
        retriever = get_retriever()
        results = retriever.vector_search("time traveller", [self.doc_id], k=5)
        assert len(results) >= 3, f"vector_search returned {len(results)} results"
        for r in results:
            assert r.text.strip(), f"Empty text in vector result: {r}"
            assert r.document_id == self.doc_id

    async def test_keyword_search(self):
        """BM25 keyword search for 'Eloi Morlocks' returns >= 2 results."""
        retriever = get_retriever()
        results = await retriever.keyword_search("Eloi Morlocks", [self.doc_id], k=5)
        assert len(results) >= 2, f"keyword_search returned {len(results)} results"
        for r in results:
            assert r.text.strip(), f"Empty text in keyword result: {r}"

    async def test_hybrid_retrieve(self):
        """Hybrid RRF retrieval for 'What is the Time Machine?' returns >= 5 results."""
        retriever = get_retriever()
        results = await retriever.retrieve(
            "What is the Time Machine?", [self.doc_id], k=10
        )
        assert len(results) >= 5, (
            f"hybrid retrieve returned {len(results)} results"
        )

    # ------------------------------------------------------------------
    # Q&A streaming
    # ------------------------------------------------------------------

    async def test_qa_stream(self):
        """QAService.stream_answer yields >= 1 token event and done=true with citations."""
        from app.services.qa import QAService

        citations = [
            {
                "document_title": "The Time Machine",
                "section_heading": "Chapter I",
                "page": 1,
                "excerpt": "The Time Traveller...",
            }
        ]
        llm_response = "The Time Traveller invented it." + json.dumps(
            {"citations": citations, "confidence": "high"}
        )

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value=_async_iter([llm_response]))

        with patch("app.services.qa.get_llm_service", return_value=mock_llm):
            svc = QAService()
            events = [
                e
                async for e in svc.stream_answer(
                    "Who invented the Time Machine?", [self.doc_id], "single", None
                )
            ]

        token_events = [e for e in events if '"token"' in e]
        done_events = [e for e in events if '"done": true' in e]

        assert len(token_events) >= 1, (
            f"Expected >= 1 token event, got {len(token_events)}. All events: {events}"
        )
        assert len(done_events) >= 1, "Expected done=true event"

        # Verify citations in done event
        done_payload = json.loads(done_events[-1][len("data: "):])
        assert done_payload.get("done") is True
        assert len(done_payload.get("citations", [])) >= 1, (
            f"Expected >= 1 citation, got {done_payload.get('citations', [])}"
        )

    # ------------------------------------------------------------------
    # Knowledge graph
    # ------------------------------------------------------------------

    async def test_graph_nodes(self):
        """Graph endpoint returns >= 20 nodes and >= 10 edges."""
        svc = get_graph_service()
        graph_data = svc.get_graph_for_document(self.doc_id)
        nodes = graph_data["nodes"]
        edges = graph_data["edges"]
        assert len(nodes) >= 20, f"Expected >= 20 nodes, got {len(nodes)}"
        assert len(edges) >= 10, f"Expected >= 10 edges, got {len(edges)}"

    # ------------------------------------------------------------------
    # Search endpoint
    # ------------------------------------------------------------------

    async def test_search_endpoint(self):
        """GET /search?q=Weena returns 200 with >= 1 result."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/search", params={"q": "Weena", "document_id": self.doc_id}
            )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        results = data if isinstance(data, list) else data.get("results", [])
        assert len(results) >= 1, (
            f"Expected >= 1 search result for 'Weena', got {len(results)}"
        )

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------

    def test_ingest_elapsed(self):
        """Time Machine ingestion must complete within 600 seconds."""
        print(f"\nTime Machine ingestion: {self.elapsed:.1f}s", flush=True)
        assert self.elapsed <= 600, (
            f"Ingestion took {self.elapsed:.1f}s, budget is 600s"
        )
