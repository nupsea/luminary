"""Concurrent ingestion stability tests.

Uses asyncio.gather to fire 5 simultaneous POST /documents/ingest requests and
asserts that all documents eventually reach stage='complete' or stage='error'
(never stuck in an intermediate stage), and that no Kuzu RuntimeError lock
exception propagates to HTTP clients.

Marked @pytest.mark.slow — excluded from make test (fast CI path).
Run explicitly with:
    uv run pytest tests/test_concurrent.py -v -m slow
"""

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
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

pytestmark = pytest.mark.slow

_FIXTURE_TEXTS = [
    b"Alice and Bob discussed the system design. Alice proposed a new architecture.",
    b"The history of computing spans seven decades of rapid innovation and change.",
    b"Machine learning algorithms require substantial amounts of labelled training data.",
    b"Abstract: This paper presents a novel approach to distributed consensus protocols.",
    b"def fib(n):\n    if n <= 1:\n        return n\n    return fib(n-1) + fib(n-2)",
]


# ---------------------------------------------------------------------------
# Mock ML services (fast, no model downloads)
# ---------------------------------------------------------------------------


class _MockEmbeddingService:
    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]


class _MockEntityExtractor:
    def extract(self, chunks: list[dict]) -> list[dict]:
        if not chunks:
            return []
        doc_id = chunks[0]["document_id"]
        chunk_id = chunks[0]["id"]
        entity_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:concurrent-test"))
        return [
            {
                "id": entity_id,
                "name": "concurrent test entity",
                "type": "CONCEPT",
                "chunk_id": chunk_id,
                "document_id": doc_id,
            }
        ]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def concurrent_db(tmp_path, monkeypatch):
    """File-based SQLite + isolated temp dirs + mocked ML services."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    # File-based SQLite (required for concurrent writes via multiple connections)
    db_path = tmp_path / "luminary.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    # Reset vector / graph / retriever so they recreate in tmp_path
    orig_lance = vs_module._lancedb_service
    orig_graph = graph_module._graph_service
    orig_embedder = embedder_module._embedding_service
    orig_extractor = ner_module._extractor
    orig_retriever = retriever_module._retriever

    vs_module._lancedb_service = None
    graph_module._graph_service = None
    retriever_module._retriever = None

    # Inject fast mock ML services
    embedder_module._embedding_service = _MockEmbeddingService()  # type: ignore[assignment]
    ner_module._extractor = _MockEntityExtractor()  # type: ignore[assignment]

    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)

    yield tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    vs_module._lancedb_service = orig_lance
    graph_module._graph_service = orig_graph
    embedder_module._embedding_service = orig_embedder  # type: ignore[assignment]
    ner_module._extractor = orig_extractor
    retriever_module._retriever = orig_retriever
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_five_concurrent_uploads_all_reach_terminal_stage(concurrent_db):
    """5 simultaneous POST /documents/ingest requests must all reach a terminal stage.

    Asserts:
    - All HTTP ingest responses return 200 with a document_id
    - No Kuzu RuntimeError (lock exception) propagates as HTTP 500 to clients
    - All documents eventually reach stage='complete' or stage='error' within 30s
      (never stuck in 'parsing', 'chunking', 'embedding', etc.)
    """
    tmp_path = concurrent_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Create 5 small text fixture files
        doc_files = []
        for i, content in enumerate(_FIXTURE_TEXTS):
            fp = tmp_path / f"concurrent_{i}.txt"
            fp.write_bytes(content)
            doc_files.append(fp)

        # Fire all 5 ingestion requests simultaneously
        async def ingest_one(path):
            with path.open("rb") as fh:
                return await client.post(
                    "/documents/ingest",
                    files={"file": (path.name, fh, "text/plain")},
                )

        responses = await asyncio.gather(*[ingest_one(fp) for fp in doc_files])

        # All must return 200 — no Kuzu lock RuntimeError should surface as 500
        for resp in responses:
            assert resp.status_code == 200, (
                f"Ingest returned {resp.status_code}: {resp.text[:200]}"
            )
            body = resp.json()
            assert "document_id" in body
            # No lock exception in response body
            assert "RuntimeError" not in resp.text
            assert "lock" not in resp.text.lower()

        doc_ids = [resp.json()["document_id"] for resp in responses]

        # Poll until all documents reach a terminal stage (complete or error)
        terminal = {"complete", "error"}
        deadline = asyncio.get_event_loop().time() + 30.0

        while True:
            stages = {}
            for doc_id in doc_ids:
                r = await client.get(f"/documents/{doc_id}/status")
                assert r.status_code == 200, f"Status check failed: {r.text}"
                stages[doc_id] = r.json().get("stage", "")

            if all(s in terminal for s in stages.values()):
                break

            if asyncio.get_event_loop().time() > deadline:
                stuck = {k: v for k, v in stages.items() if v not in terminal}
                pytest.fail(
                    f"Documents stuck in non-terminal stage after 30s: {stuck}"
                )

            await asyncio.sleep(0.5)

        # Verify all documents ended in a known terminal stage
        for doc_id, stage in stages.items():
            assert stage in terminal, (
                f"Document {doc_id} in unexpected stage: {stage}"
            )
