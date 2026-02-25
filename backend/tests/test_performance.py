"""Performance baseline tests — search latency, memory growth, ingestion throughput.

These are regression guards, not hard SLAs. The goal is to catch 10x regressions
(e.g. search taking 30s instead of 300ms) rather than optimise to the millisecond.

Marked @pytest.mark.slow — excluded from make test (fast CI path).
Run explicitly with:
    uv run pytest tests/test_performance.py -v -m slow

make test-perf is equivalent.
"""

import asyncio
import time
import uuid
from pathlib import Path

import psutil
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

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# 20 search queries drawn from both fixture documents
_SEARCH_QUERIES = [
    # Time Machine queries
    "time traveller",
    "fourth dimension",
    "Eloi and Morlocks",
    "time machine invention",
    "Length Breadth Thickness Duration",
    "conscious movement along time",
    "golden age future humanity",
    "Weena companion",
    "White Sphinx pedestal",
    "Psychologist model machine",
    # Art of Unix queries
    "Unix philosophy",
    "modularity clean interfaces",
    "Rule of Simplicity",
    "open source culture",
    "design philosophy Unix programming",
    "durability of Unix",
    "software complexity",
    "engineering traditions",
    "technical culture apprenticeship",
    "power tools programming",
]


# ---------------------------------------------------------------------------
# Mock ML services
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
        entity_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:perf-test"))
        return [
            {
                "id": entity_id,
                "name": "perf test entity",
                "type": "CONCEPT",
                "chunk_id": chunk_id,
                "document_id": doc_id,
            }
        ]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def perf_db(tmp_path, monkeypatch):
    """File-based SQLite + temp dirs + mock ML services for performance tests."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    db_path = tmp_path / "luminary.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    orig_lance = vs_module._lancedb_service
    orig_graph = graph_module._graph_service
    orig_embedder = embedder_module._embedding_service
    orig_extractor = ner_module._extractor
    orig_retriever = retriever_module._retriever

    vs_module._lancedb_service = None
    graph_module._graph_service = None
    retriever_module._retriever = None
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
# Helpers
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    """Compute the p-th percentile (0-100) of a sorted or unsorted list."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct / 100.0
    lo = int(k)
    hi = lo + 1
    if hi >= len(sorted_vals):
        return sorted_vals[-1]
    frac = k - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


async def _ingest_and_wait(
    client: AsyncClient, tmp_path: Path, name: str, content: bytes, deadline: float
) -> str | None:
    """POST /ingest for content and poll until terminal stage. Returns doc_id or None."""
    fp = tmp_path / name
    fp.write_bytes(content)
    with fp.open("rb") as fh:
        resp = await client.post(
            "/documents/ingest",
            files={"file": (name, fh, "text/plain")},
        )
    if resp.status_code != 200:
        return None
    doc_id = resp.json().get("document_id")
    terminal = {"complete", "error"}
    while time.perf_counter() < deadline:
        sr = await client.get(f"/documents/{doc_id}/status")
        if sr.status_code == 200 and sr.json().get("stage") in terminal:
            return doc_id
        await asyncio.sleep(0.2)
    return None  # timed out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_search_latency_p50_p95(perf_db):
    """p50 search latency < 500ms, p95 < 2000ms over 20 queries.

    Ingests 10 documents first, then measures GET /search latency.
    """
    tmp_path = perf_db

    fixture_a = (FIXTURES_DIR / "time_machine.txt").read_bytes()
    fixture_b = (FIXTURES_DIR / "art_of_unix_ch1.txt").read_bytes()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Ingest 10 documents (5 copies of each fixture, different names)
        deadline = time.perf_counter() + 120.0
        ingested = []
        for i in range(5):
            doc_id_a = await _ingest_and_wait(
                client, tmp_path, f"time_machine_{i}.txt", fixture_a, deadline
            )
            doc_id_b = await _ingest_and_wait(
                client, tmp_path, f"art_of_unix_{i}.txt", fixture_b, deadline
            )
            if doc_id_a:
                ingested.append(doc_id_a)
            if doc_id_b:
                ingested.append(doc_id_b)

        assert len(ingested) >= 8, (
            f"Expected >=8 documents to complete ingestion, got {len(ingested)}"
        )

        # Run 20 search queries and record latencies
        latencies_ms: list[float] = []
        for query in _SEARCH_QUERIES:
            t0 = time.perf_counter()
            r = await client.get("/search", params={"q": query})
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert r.status_code == 200, f"Search failed for '{query}': {r.text}"
            latencies_ms.append(elapsed_ms)

        p50 = _percentile(latencies_ms, 50)
        p95 = _percentile(latencies_ms, 95)

        print(f"\nSearch latency: p50={p50:.1f}ms  p95={p95:.1f}ms  n=20")

        assert p50 < 500, f"p50 search latency {p50:.1f}ms exceeds 500ms baseline"
        assert p95 < 2000, f"p95 search latency {p95:.1f}ms exceeds 2000ms baseline"


@pytest.mark.slow
async def test_ingestion_throughput_10_docs_within_120s(perf_db):
    """10 documents (~10k chars each) all reach complete within 120s (mocked embedder)."""
    tmp_path = perf_db

    fixture_a = (FIXTURES_DIR / "time_machine.txt").read_bytes()
    fixture_b = (FIXTURES_DIR / "art_of_unix_ch1.txt").read_bytes()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        wall_start = time.perf_counter()
        deadline = wall_start + 120.0

        tasks = []
        for i in range(5):
            tasks.append(
                _ingest_and_wait(client, tmp_path, f"tm_{i}.txt", fixture_a, deadline)
            )
            tasks.append(
                _ingest_and_wait(client, tmp_path, f"au_{i}.txt", fixture_b, deadline)
            )

        results = await asyncio.gather(*tasks)
        wall_elapsed = time.perf_counter() - wall_start

        completed = [r for r in results if r is not None]
        print(
            f"\nIngestion throughput: {len(completed)}/10 docs completed "
            f"in {wall_elapsed:.1f}s"
        )

        assert len(completed) == 10, (
            f"Only {len(completed)}/10 documents completed within 120s"
        )
        assert wall_elapsed < 120, (
            f"10 documents took {wall_elapsed:.1f}s (limit: 120s)"
        )


@pytest.mark.slow
async def test_memory_growth_under_500mb_for_10_docs(perf_db):
    """Memory RSS growth during ingestion of 10 documents must be < 500MB."""
    tmp_path = perf_db

    fixture_a = (FIXTURES_DIR / "time_machine.txt").read_bytes()
    fixture_b = (FIXTURES_DIR / "art_of_unix_ch1.txt").read_bytes()

    process = psutil.Process()
    rss_before = process.memory_info().rss

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        deadline = time.perf_counter() + 120.0
        tasks = []
        for i in range(5):
            tasks.append(
                _ingest_and_wait(client, tmp_path, f"mem_tm_{i}.txt", fixture_a, deadline)
            )
            tasks.append(
                _ingest_and_wait(client, tmp_path, f"mem_au_{i}.txt", fixture_b, deadline)
            )
        await asyncio.gather(*tasks)

    rss_after = process.memory_info().rss
    growth_mb = (rss_after - rss_before) / (1024 * 1024)

    print(f"\nMemory growth: {growth_mb:.1f}MB (before={rss_before // (1024*1024)}MB)")

    assert growth_mb < 500, (
        f"Memory grew by {growth_mb:.1f}MB (limit: 500MB) after ingesting 10 documents"
    )
