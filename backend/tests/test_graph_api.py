"""Slow integration test: verify GET /graph/{id} returns nodes and edges after full ingest.

Marked @pytest.mark.slow — not part of default make test.
Run with:
    cd backend && uv run pytest tests/test_graph_api.py -v -m slow
"""

import shutil
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
import app.services.retriever as retriever_module
import app.services.vector_store as vs_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel

FIXTURES_FULL_DIR = Path(__file__).parent / "fixtures" / "full"

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Fixture: isolated full-pipeline environment
# ---------------------------------------------------------------------------


@pytest.fixture
async def graph_api_db(tmp_path, monkeypatch):
    """Isolated environment with real SQLite, LanceDB, Kuzu, and ML services."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    from app.config import get_settings

    get_settings.cache_clear()

    db_url = f"sqlite+aiosqlite:///{tmp_path}/luminary.db"
    engine = make_engine(db_url)
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    orig_lancedb = vs_module._lancedb_service
    orig_graph = graph_module._graph_service
    orig_retriever = retriever_module._retriever

    vs_module._lancedb_service = None
    graph_module._graph_service = None
    retriever_module._retriever = None

    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    vs_module._lancedb_service = orig_lancedb
    graph_module._graph_service = orig_graph
    retriever_module._retriever = orig_retriever
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_returns_nodes_after_ingest(graph_api_db, monkeypatch):
    """Ingest time_machine.txt → GET /graph/{id} must return >=20 nodes and >=10 edges.

    Verifies:
    - response status 200
    - len(nodes) >= 20
    - len(edges) >= 10
    - every node has id (str), label (str), type (str), size (number > 0)
    - every edge has source (str), target (str), weight (number)
    """
    import litellm

    import app.services.llm as llm_module

    engine, factory, tmp_path = graph_api_db

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "book"
    mock_resp.usage = None
    monkeypatch.setattr(litellm, "acompletion", AsyncMock(return_value=mock_resp))
    llm_module._llm_service = None

    from app.workflows.ingestion import run_ingestion

    doc_id = str(uuid.uuid4())
    src = FIXTURES_FULL_DIR / "time_machine.txt"
    dest = tmp_path / "raw" / f"{doc_id}.txt"
    shutil.copy(src, dest)

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="The Time Machine",
                format="txt",
                content_type="book",
                word_count=0,
                page_count=0,
                file_path=str(dest),
                stage="parsing",
            )
        )
        await session.commit()

    await run_ingestion(doc_id, str(dest), "txt")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/graph/{doc_id}")

    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    edges = data["edges"]

    assert len(nodes) >= 20, f"Expected >=20 nodes after ingest, got {len(nodes)}"
    assert len(edges) >= 10, f"Expected >=10 edges after ingest, got {len(edges)}"

    for node in nodes:
        assert isinstance(node.get("id"), str), f"Node 'id' must be str: {node}"
        assert isinstance(node.get("label"), str), f"Node 'label' must be str: {node}"
        assert isinstance(node.get("type"), str), f"Node 'type' must be str: {node}"
        size = node.get("size")
        assert isinstance(size, (int, float)) and size > 0, (
            f"Node 'size' must be a positive number: {node}"
        )

    for edge in edges:
        assert isinstance(edge.get("source"), str), f"Edge 'source' must be str: {edge}"
        assert isinstance(edge.get("target"), str), f"Edge 'target' must be str: {edge}"
        weight = edge.get("weight")
        assert isinstance(weight, (int, float)), (
            f"Edge 'weight' must be a number: {edge}"
        )
