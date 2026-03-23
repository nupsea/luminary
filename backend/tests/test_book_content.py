"""Per-book content verification — entities, keywords, co-occurrences, and semantic search.

All parameters read from DATA/books/manifest.json — zero hardcoded values.

Marked @pytest.mark.slow — not part of default make test.
Run with all book tests (shared fixture, each book ingested once):
    make test-books-all
Run alone:
    cd backend && uv run pytest tests/test_book_content.py -v -m slow --timeout=2400

Relies on all_books_ingested session fixture from conftest_books.py which is
loaded via pytest_plugins below.  When run in the same session as
test_diagnostics.py and test_e2e_book.py, all 3 books are ingested exactly once.
"""

import json
from pathlib import Path

import pytest
from sqlalchemy import text

import app.database as db_module
from app.services.graph import get_graph_service
from app.services.retriever import HybridRetriever

# Load manifest at import time so parametrize can reference it.
REPO_ROOT = Path(__file__).parent.parent.parent
MANIFEST_PATH = REPO_ROOT / "DATA" / "books" / "manifest.json"
MANIFEST: list[dict] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
MANIFEST_BY_NAME: dict[str, dict] = {e["name"]: e for e in MANIFEST}

# Load shared session fixture from conftest_books.py.
pytest_plugins = ["tests.conftest_books"]

pytestmark = pytest.mark.slow


class TestBookContentVerification:
    """Per-book content verification after full ingestion."""

    @pytest.mark.parametrize("book_name", [e["name"] for e in MANIFEST])
    def test_known_entities_in_kuzu(self, book_name: str, all_books_ingested):
        """Each book's known entities must appear in the Kuzu graph (case-insensitive substring)."""
        doc_id = all_books_ingested[book_name]["doc_id"]
        book_entry = MANIFEST_BY_NAME[book_name]

        svc = get_graph_service()
        graph_data = svc.get_graph_for_document(doc_id)
        node_names = {node["label"].lower() for node in graph_data["nodes"]}

        for entity in book_entry["known_entities"]:
            found = any(entity.lower() in name for name in node_names)
            assert found, (
                f'Entity "{entity}" not found in Kuzu graph for {book_name}. '
                f"Found nodes: {sorted(node_names)[:20]}"
            )

    @pytest.mark.parametrize("book_name", [e["name"] for e in MANIFEST])
    async def test_known_keywords_in_fts(self, book_name: str, all_books_ingested):
        """Each book's known keywords must return >= 1 FTS5 hit with keyword in text."""
        doc_id = all_books_ingested[book_name]["doc_id"]
        book_entry = MANIFEST_BY_NAME[book_name]
        retriever = HybridRetriever()

        for keyword in book_entry["known_keywords"]:
            results = await retriever.keyword_search(keyword, [doc_id], k=5)
            found_in_text = results and any(
                keyword.lower() in r.text.lower() for r in results
            )
            assert len(results) >= 1 and found_in_text, (
                f'Keyword "{keyword}" returned 0 FTS5 hits for {book_name}'
            )

    @pytest.mark.parametrize("book_name", [e["name"] for e in MANIFEST])
    def test_co_occurrence_edges(self, book_name: str, all_books_ingested):
        """Known entity pairs must have CO_OCCURS edges in the Kuzu graph."""
        doc_id = all_books_ingested[book_name]["doc_id"]
        book_entry = MANIFEST_BY_NAME[book_name]

        svc = get_graph_service()
        graph_data = svc.get_graph_for_document(doc_id)
        nodes = graph_data["nodes"]
        edges = graph_data["edges"]

        for entity_a, entity_b in book_entry["known_co_occurrences"]:
            node_a = next(
                (n for n in nodes if entity_a.lower() in n["label"].lower()), None
            )
            node_b = next(
                (n for n in nodes if entity_b.lower() in n["label"].lower()), None
            )
            node_a_id = node_a["id"] if node_a else None
            node_b_id = node_b["id"] if node_b else None

            edge_found = any(
                (e["source"] == node_a_id and e["target"] == node_b_id)
                or (e["source"] == node_b_id and e["target"] == node_a_id)
                for e in edges
            )
            assert edge_found, (
                f'No CO_OCCURS edge between "{entity_a}" and "{entity_b}" in {book_name}. '
                f"node_a found: {node_a_id is not None}, node_b found: {node_b_id is not None}"
            )

    @pytest.mark.parametrize("book_name", [e["name"] for e in MANIFEST])
    def test_semantic_search_relevance(self, book_name: str, all_books_ingested):
        """Semantic queries must return chunks containing the expected keyword."""
        doc_id = all_books_ingested[book_name]["doc_id"]
        book_entry = MANIFEST_BY_NAME[book_name]
        retriever = HybridRetriever()

        for entry in book_entry["semantic_queries"]:
            query = entry["query"]
            expected_keyword = entry["expected_keyword"]
            results = retriever.vector_search(query, [doc_id], k=5)
            found = results and any(
                expected_keyword.lower() in r.text.lower() for r in results
            )
            assert len(results) >= 1 and found, (
                f'Query "{query}" did not return any chunk containing '
                f'"{expected_keyword}" for {book_name}. '
                f'Top result: {results[0].text[:200] if results else "(no results)"}'
            )

    @pytest.mark.parametrize("book_name", [e["name"] for e in MANIFEST])
    async def test_fts_raw_term_coverage(self, book_name: str, all_books_ingested):
        """Raw FTS5 COUNT must be >= 1 for each known keyword per book."""
        doc_id = all_books_ingested[book_name]["doc_id"]
        book_entry = MANIFEST_BY_NAME[book_name]
        session_factory = db_module.get_session_factory()

        for keyword in book_entry["known_keywords"]:
            async with session_factory() as session:
                result = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM chunks_fts "
                        "WHERE chunks_fts MATCH :kw AND document_id = :did"
                    ),
                    {"kw": keyword, "did": doc_id},
                )
                count = result.scalar()
            assert count >= 1, (
                f'FTS5 raw COUNT for "{keyword}" in {book_name} = 0. '
                f"This means the keyword is not present in any indexed chunk for this document."
            )

    def test_ingest_timing_all_books(self, all_books_ingested):
        """All books must be ingested within their time budget; timings always printed."""
        failures = []
        for book_entry in MANIFEST:
            name = book_entry["name"]
            budget = book_entry["ingest_time_budget_seconds"]
            elapsed = all_books_ingested[name]["elapsed_seconds"]
            print(f"{name} ingestion: {elapsed:.1f}s (budget: {budget}s)", flush=True)
            if elapsed > budget:
                failures.append(
                    f"'{name}' took {elapsed:.1f}s, budget is {budget}s"
                )
        if failures:
            raise AssertionError(
                "Ingestion budget exceeded:\n" + "\n".join(failures)
            )
