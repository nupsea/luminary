"""Full-document integration tests using real ML services.

These tests exercise the complete ingestion pipeline (parse → classify → chunk →
embed → keyword_index → entity_extract) against full public-domain documents
using the REAL EmbeddingService (BAAI/bge-m3 via ONNX Runtime) and the REAL
EntityExtractor (GLiNER).

LiteLLM classification is still mocked to avoid Ollama as a CI dependency.

These tests are marked @pytest.mark.slow and are NOT part of the default
``make test`` (fast CI) path.  Run them with::

    make test-full
    # or
    cd backend && uv run pytest tests/test_integration_full.py -v -m slow

On first run the test will download BAAI/bge-m3 and the GLiNER model into the
temporary DATA_DIR.  This can take several minutes depending on network speed.
Subsequent runs reuse the model cache inside the pytest tmp_path directory.
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
import app.services.graph as graph_module
import app.services.retriever as retriever_module
import app.services.vector_store as vs_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel

FIXTURES_FULL_DIR = Path(__file__).parent / "fixtures" / "full"

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Isolated fixture: real SQLite file, real LanceDB, real Kuzu, real ML services
# ---------------------------------------------------------------------------


@pytest.fixture
async def full_integration_db(tmp_path, monkeypatch):
    """Isolated environment for full integration tests.

    Uses:
    - Real SQLite file in tmp_path (not in-memory)
    - Real LanceDB in tmp_path
    - Real Kuzu in tmp_path
    - Real EmbeddingService (BAAI/bge-m3) — model cached in tmp_path
    - Real EntityExtractor (GLiNER) — model cached in tmp_path

    LiteLLM is still mocked to avoid Ollama dependency.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    from app.config import get_settings

    get_settings.cache_clear()

    # Use real SQLite file (not in-memory) so LanceDB chunk lookups work
    db_url = f"sqlite+aiosqlite:///{tmp_path}/luminary.db"
    engine = make_engine(db_url)
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Swap DB singletons
    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    # Reset LanceDB, Kuzu, and retriever singletons so they re-create against tmp_path.
    # Do NOT reset the embedding/NER singletons — let them use real services.
    orig_lancedb = vs_module._lancedb_service
    orig_graph = graph_module._graph_service
    orig_retriever = retriever_module._retriever

    vs_module._lancedb_service = None
    graph_module._graph_service = None
    retriever_module._retriever = None

    # Ensure raw/ dir exists
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)

    yield engine, factory, tmp_path

    # Teardown: restore originals
    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    vs_module._lancedb_service = orig_lancedb
    graph_module._graph_service = orig_graph
    retriever_module._retriever = orig_retriever
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helper: run full ingestion (real ML, mocked LiteLLM classify only)
# ---------------------------------------------------------------------------


async def _ingest_full(
    fixture_name: str,
    factory: async_sessionmaker,
    tmp_path: Path,
    monkeypatch,
    *,
    mock_llm_response: str = "notes",
) -> str:
    """Copy fixture to raw dir, create DocumentModel, run full ingestion pipeline.

    LiteLLM is mocked so classify_node does not need a running Ollama instance.
    EmbeddingService and EntityExtractor are NOT mocked — real ML runs.

    Returns the document_id.
    """
    import litellm

    import app.services.llm as llm_module

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = mock_llm_response
    mock_resp.usage = None
    monkeypatch.setattr(litellm, "acompletion", AsyncMock(return_value=mock_resp))
    llm_module._llm_service = None  # force re-creation against mock

    from app.workflows.ingestion import run_ingestion

    doc_id = str(uuid.uuid4())
    src = FIXTURES_FULL_DIR / fixture_name
    dest = tmp_path / "raw" / f"{doc_id}.txt"
    shutil.copy(src, dest)

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title=src.stem.replace("_", " ").title(),
                format="txt",
                content_type=mock_llm_response,
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
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_full_ingest_fiction(full_integration_db, monkeypatch):
    """Ingest the full Time Machine text (~180k chars) with real ML services.

    Asserts:
    - stage='complete' after pipeline
    - chunk_count >= 50
    - entity_count >= 10  (GLiNER finds persons, places, dates in H.G. Wells)
    - search for 'time traveller' returns >= 3 results
    """
    engine, factory, tmp_path = full_integration_db

    doc_id = await _ingest_full(
        "time_machine.txt",
        factory,
        tmp_path,
        monkeypatch,
        mock_llm_response="book",
    )

    # 1. Document should reach 'complete' stage
    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc is not None, "DocumentModel should exist"
    assert doc.stage == "complete", f"Expected stage='complete', got '{doc.stage}'"

    # 2. At least 50 chunks should be stored (book: 600-char chunks, ~180k chars → ~300+)
    async with factory() as session:
        result = await session.execute(select(func.count()).where(ChunkModel.document_id == doc_id))
        chunk_count = result.scalar_one()
    assert chunk_count >= 50, f"Expected >=50 chunks, got {chunk_count}"

    # 3. At least 10 entities should be in the knowledge graph (real GLiNER)
    from app.services.graph import get_graph_service

    graph_data = get_graph_service().get_graph_for_document(doc_id)
    entity_count = len(graph_data["nodes"])
    assert entity_count >= 10, f"Expected >=10 graph nodes from GLiNER, got {entity_count}"

    # 4. Search for 'time traveller' returns >= 3 results via hybrid retrieval
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/search", params={"q": "time traveller"})

    assert response.status_code == 200
    body = response.json()
    results: list = body.get("results", [])
    total_matches = sum(len(group["matches"]) for group in results)
    assert total_matches >= 3, (
        f"Expected >=3 search results for 'time traveller', got {total_matches}"
    )


@pytest.mark.slow
async def test_full_ingest_technical(full_integration_db, monkeypatch):
    """Ingest the full Art of Unix Programming text with real ML services.

    Asserts:
    - stage='complete' after pipeline
    - chunk_count >= 100
    - entity_count >= 15  (GLiNER finds persons, orgs, concepts, technologies)
    - search for 'Unix philosophy' returns >= 3 results
    """
    engine, factory, tmp_path = full_integration_db

    doc_id = await _ingest_full(
        "art_of_unix.txt",
        factory,
        tmp_path,
        monkeypatch,
        mock_llm_response="paper",
    )

    # 1. Document should reach 'complete' stage
    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc is not None, "DocumentModel should exist"
    assert doc.stage == "complete", f"Expected stage='complete', got '{doc.stage}'"

    # 2. At least 100 chunks should be stored (paper: 300-char chunks, ~109k chars → ~360+)
    async with factory() as session:
        result = await session.execute(select(func.count()).where(ChunkModel.document_id == doc_id))
        chunk_count = result.scalar_one()
    assert chunk_count >= 100, f"Expected >=100 chunks, got {chunk_count}"

    # 3. At least 15 entities should be in the knowledge graph (real GLiNER)
    from app.services.graph import get_graph_service

    graph_data = get_graph_service().get_graph_for_document(doc_id)
    entity_count = len(graph_data["nodes"])
    assert entity_count >= 15, f"Expected >=15 graph nodes from GLiNER, got {entity_count}"

    # 4. Search for 'Unix philosophy' returns >= 3 results via hybrid retrieval
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/search", params={"q": "Unix philosophy"})

    assert response.status_code == 200
    body = response.json()
    results: list = body.get("results", [])
    total_matches = sum(len(group["matches"]) for group in results)
    assert total_matches >= 3, (
        f"Expected >=3 search results for 'Unix philosophy', got {total_matches}"
    )
