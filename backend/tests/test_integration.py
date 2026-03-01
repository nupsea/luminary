"""Integration tests: real document ingestion pipeline with mocked heavy ML services.

Tests ingest two public-domain text fixtures end-to-end through the full LangGraph
pipeline (parse → classify → chunk → embed → keyword_index → entity_extract) and
assert the pipeline produces usable output in the database.

Heavy ML services are mocked:
  - LiteLLM: classification LLM call returns a fixed content type
  - EmbeddingService: returns deterministic 1024-dim dummy vectors (no model download)
  - EntityExtractor: returns one synthetic entity per document (no GLiNER download)

Real services used:
  - SQLite (in-memory, via async engine)
  - LanceDB (temp directory)
  - Kuzu graph DB (temp directory)
  - FTS5 keyword index (part of SQLite)
  - Text splitting / parsing (pure Python)

Run integration tests:
  cd backend && uv run pytest tests/test_integration.py -v
"""

import shutil
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.embedder as embedder_module
import app.services.graph as graph_module
import app.services.ner as ner_module
import app.services.retriever as retriever_module
import app.services.vector_store as vs_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class _MockEmbeddingService:
    """Returns a deterministic 1024-dim dummy vector for any input text."""

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]


class _MockEntityExtractor:
    """Returns exactly one synthetic entity per non-empty document."""

    def extract(self, chunks: list[dict], content_type: str = "unknown") -> list[dict]:
        if not chunks:
            return []
        doc_id = chunks[0]["document_id"]
        chunk_id = chunks[0]["id"]
        entity_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:integration-test"))
        return [
            {
                "id": entity_id,
                "name": "integration test entity",
                "type": "CONCEPT",
                "chunk_id": chunk_id,
                "document_id": doc_id,
            }
        ]


# ---------------------------------------------------------------------------
# Test DB + service fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def integration_db(tmp_path, monkeypatch):
    """Isolated environment: in-memory SQLite, temp LanceDB dir, temp Kuzu dir,
    mocked embedding service and entity extractor."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    from app.config import get_settings

    get_settings.cache_clear()

    # Set up in-memory SQLite
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Swap DB singletons
    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    # Reset service singletons so they re-create against tmp_path
    orig_lancedb = vs_module._lancedb_service
    orig_graph = graph_module._graph_service
    orig_embedder = embedder_module._embedding_service
    orig_extractor = ner_module._extractor
    orig_retriever = retriever_module._retriever

    vs_module._lancedb_service = None
    graph_module._graph_service = None
    retriever_module._retriever = None

    # Inject fast mock services (no model downloads)
    embedder_module._embedding_service = _MockEmbeddingService()  # type: ignore[assignment]
    ner_module._extractor = _MockEntityExtractor()  # type: ignore[assignment]

    # Ensure raw/ dir exists (ingestion_endpoint creates it, direct calls need it)
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)

    yield engine, factory, tmp_path

    # Teardown: restore originals
    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    vs_module._lancedb_service = orig_lancedb
    graph_module._graph_service = orig_graph
    embedder_module._embedding_service = orig_embedder  # type: ignore[assignment]
    ner_module._extractor = orig_extractor
    retriever_module._retriever = orig_retriever
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helper: run ingestion directly (bypassing HTTP for speed)
# ---------------------------------------------------------------------------


async def _ingest_fixture(
    fixture_name: str,
    factory: async_sessionmaker,
    tmp_path: Path,
    monkeypatch,
    *,
    mock_llm_response: str = "notes",
) -> str:
    """Copy fixture to raw dir, create DocumentModel, run full ingestion pipeline.

    Returns the document_id.
    """
    import litellm

    import app.services.llm as llm_module
    from app.workflows.ingestion import run_ingestion

    # Mock LiteLLM so classify_node doesn't need Ollama
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = mock_llm_response
    mock_resp.usage = None
    monkeypatch.setattr(litellm, "acompletion", AsyncMock(return_value=mock_resp))
    llm_module._llm_service = None  # force re-creation against mock

    doc_id = str(uuid.uuid4())
    src = FIXTURES_DIR / fixture_name
    dest = tmp_path / "raw" / f"{doc_id}.txt"
    shutil.copy(src, dest)

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title=src.stem.replace("_", " ").title(),
                format="txt",
                content_type="notes",
                word_count=0,
                page_count=0,
                file_path=str(dest),
                stage="parsing",
            )
        )
        await session.commit()

    await run_ingestion(doc_id, str(dest), "txt")
    return doc_id


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


async def test_ingest_fiction(integration_db, monkeypatch):
    """Ingest The Time Machine (fiction); assert pipeline reaches 'complete' stage,
    produces ≥5 chunks, and stores ≥1 entity in the knowledge graph."""
    engine, factory, tmp_path = integration_db

    doc_id = await _ingest_fixture(
        "time_machine.txt", factory, tmp_path, monkeypatch, mock_llm_response="book"
    )

    # 1. Document should reach 'complete' stage
    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc is not None, "DocumentModel should exist"
    assert doc.stage == "complete", f"Expected stage='complete', got '{doc.stage}'"

    # 2. At least 5 chunks should be in the database
    async with factory() as session:
        result = await session.execute(
            select(func.count()).where(ChunkModel.document_id == doc_id)
        )
        chunk_count = result.scalar_one()
    assert chunk_count >= 5, f"Expected ≥5 chunks, got {chunk_count}"

    # 3. At least 1 entity should be extracted into the knowledge graph
    from app.services.graph import get_graph_service

    graph_data = get_graph_service().get_graph_for_document(doc_id)
    assert len(graph_data["nodes"]) >= 1, (
        f"Expected ≥1 graph node, got {len(graph_data['nodes'])}"
    )


async def test_ingest_technical(integration_db, monkeypatch):
    """Ingest Art of Unix Programming Ch.1 (technical); assert pipeline reaches
    'complete' stage, produces ≥5 chunks, and stores ≥1 entity."""
    engine, factory, tmp_path = integration_db

    doc_id = await _ingest_fixture(
        "art_of_unix_ch1.txt", factory, tmp_path, monkeypatch, mock_llm_response="paper"
    )

    # 1. Document should reach 'complete' stage
    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc is not None, "DocumentModel should exist"
    assert doc.stage == "complete", f"Expected stage='complete', got '{doc.stage}'"

    # 2. At least 5 chunks should be in the database
    async with factory() as session:
        result = await session.execute(
            select(func.count()).where(ChunkModel.document_id == doc_id)
        )
        chunk_count = result.scalar_one()
    assert chunk_count >= 5, f"Expected ≥5 chunks, got {chunk_count}"

    # 3. At least 1 entity should be extracted into the knowledge graph
    from app.services.graph import get_graph_service

    graph_data = get_graph_service().get_graph_for_document(doc_id)
    assert len(graph_data["nodes"]) >= 1, (
        f"Expected ≥1 graph node, got {len(graph_data['nodes'])}"
    )


async def test_search_after_ingest(integration_db, monkeypatch):
    """After ingesting The Time Machine, GET /search?q=time+machine should return
    at least one result via hybrid retrieval (FTS5 keyword search)."""
    _engine, factory, tmp_path = integration_db

    # Run ingestion first
    await _ingest_fixture(
        "time_machine.txt", factory, tmp_path, monkeypatch, mock_llm_response="book"
    )

    # Search via the HTTP endpoint
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/search", params={"q": "time machine"})

    assert response.status_code == 200
    body = response.json()
    results: list = body.get("results", [])
    total_matches = sum(len(group["matches"]) for group in results)
    assert total_matches >= 1, (
        f"Expected ≥1 search result for 'time machine', got {total_matches}. "
        f"Groups: {[g['document_title'] for g in results]}"
    )
