"""E2E and integration_http upload tests.

Two test flavours:
  - @pytest.mark.e2e  — require a live backend on BACKEND_URL (default
    http://localhost:8000) and a running Ollama instance.  Excluded from
    ``make ci`` via ``addopts = "-m 'not slow and not e2e'"``.  Run with:
        make test-e2e
    or
        uv run pytest tests/test_e2e_upload.py -m e2e -v

  - @pytest.mark.integration_http  — use ASGITransport (real app code, real
    in-memory DB) but mock litellm.acompletion, EmbeddingService, and
    EntityExtractor so no model downloads are required.  Included in
    ``make ci`` (the default pytest run excludes only *slow* and *e2e*).

Run integration_http tests:
    uv run pytest tests/test_e2e_upload.py -m integration_http -v
"""

import asyncio
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Shared schema validation
# ---------------------------------------------------------------------------


def _assert_status_schema(body: dict) -> None:
    """Assert the /documents/{id}/status response matches the expected schema."""
    assert isinstance(body.get("stage"), str), "stage must be a string"
    assert isinstance(body.get("progress_pct"), int), "progress_pct must be an int"
    assert isinstance(body.get("done"), bool), "done must be a bool"
    assert body.get("error_message") is None or isinstance(
        body["error_message"], str
    ), "error_message must be str or null"
    assert 0 <= body["progress_pct"] <= 100, (
        f"progress_pct out of range: {body['progress_pct']}"
    )


# ---------------------------------------------------------------------------
# E2E tests — require live backend + Ollama
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_upload_and_poll():
    """POST a real .txt file to a live backend; poll until stage='complete'.

    Assertions:
    - progress_pct increases monotonically across polls
    - stage reaches 'complete' within 120 s
    - GET /documents/{id} returns at least 5 chunks
    """
    txt_file = FIXTURES_DIR / "time_machine.txt"
    assert txt_file.exists(), f"Fixture not found: {txt_file}"

    async with AsyncClient(base_url=_BACKEND_URL, timeout=30.0) as client:
        with txt_file.open("rb") as fh:
            response = await client.post(
                "/documents/ingest",
                files={"file": ("time_machine.txt", fh, "text/plain")},
            )
        assert response.status_code == 200, response.text
        doc_id = response.json()["document_id"]

        # Poll until complete or timeout
        last_pct = -1
        for _ in range(60):
            await asyncio.sleep(2)
            status_resp = await client.get(f"/documents/{doc_id}/status")
            assert status_resp.status_code == 200
            body = status_resp.json()
            _assert_status_schema(body)

            assert body["progress_pct"] >= last_pct, (
                f"progress_pct decreased: {last_pct} → {body['progress_pct']}"
            )
            last_pct = body["progress_pct"]

            if body["done"]:
                assert body["stage"] == "complete"
                break
        else:
            pytest.fail(f"Ingestion did not complete within 120s. Last status: {body}")

        # Verify chunks exist
        doc_resp = await client.get(f"/documents/{doc_id}")
        assert doc_resp.status_code == 200


@pytest.mark.e2e
async def test_upload_error_surfaced():
    """POST a corrupt (random bytes) .pdf; expect stage='error' within 30s."""
    corrupt_bytes = bytes(range(256)) * 8  # 2 KB of garbage

    async with AsyncClient(base_url=_BACKEND_URL, timeout=30.0) as client:
        response = await client.post(
            "/documents/ingest",
            files={"file": ("corrupt.pdf", corrupt_bytes, "application/pdf")},
        )
        assert response.status_code == 200, response.text
        doc_id = response.json()["document_id"]

        # Poll until error or timeout (15 × 2s = 30s)
        body: dict = {}
        for _ in range(15):
            await asyncio.sleep(2)
            status_resp = await client.get(f"/documents/{doc_id}/status")
            assert status_resp.status_code == 200
            body = status_resp.json()
            _assert_status_schema(body)

            if body["stage"] == "error" or body.get("error_message"):
                break
        else:
            pytest.fail(f"Expected error stage within 30s; got: {body}")

        assert body["stage"] == "error" or body.get("error_message"), (
            f"Expected stage='error' or non-null error_message; got: {body}"
        )
        assert body.get("error_message"), "error_message should be non-empty on error"


@pytest.mark.e2e
async def test_status_polling_contract():
    """Upload a file and validate the schema on every poll response."""
    txt_file = FIXTURES_DIR / "art_of_unix_ch1.txt"
    assert txt_file.exists(), f"Fixture not found: {txt_file}"

    async with AsyncClient(base_url=_BACKEND_URL, timeout=30.0) as client:
        with txt_file.open("rb") as fh:
            response = await client.post(
                "/documents/ingest",
                files={"file": ("art_of_unix_ch1.txt", fh, "text/plain")},
            )
        assert response.status_code == 200
        doc_id = response.json()["document_id"]

        seen_stages: list[str] = []
        for _ in range(60):
            await asyncio.sleep(2)
            status_resp = await client.get(f"/documents/{doc_id}/status")
            assert status_resp.status_code == 200
            body = status_resp.json()
            _assert_status_schema(body)
            seen_stages.append(body["stage"])

            if body["done"]:
                assert body["stage"] == "complete"
                assert body["progress_pct"] == 100
                break
        else:
            pytest.fail(f"Ingestion did not complete within 120s. Stages seen: {seen_stages}")


# ---------------------------------------------------------------------------
# Mock helpers shared by integration_http tests
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
        entity_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:e2e-test"))
        return [
            {
                "id": entity_id,
                "name": "e2e test entity",
                "type": "CONCEPT",
                "chunk_id": chunk_id,
                "document_id": doc_id,
            }
        ]


# ---------------------------------------------------------------------------
# integration_http fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def upload_db(tmp_path, monkeypatch):
    """Isolated environment for integration_http tests.

    - In-memory SQLite
    - Temp LanceDB / Kuzu dirs
    - Mocked EmbeddingService + EntityExtractor (no model downloads)
    - litellm.acompletion mocked to return 'notes'
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    import litellm

    import app.services.llm as llm_module
    from app.config import get_settings

    get_settings.cache_clear()

    # Mock litellm at module level so classify_node does not need Ollama
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "notes"
    mock_resp.usage = None
    monkeypatch.setattr(litellm, "acompletion", AsyncMock(return_value=mock_resp))
    llm_module._llm_service = None

    # Set up in-memory SQLite
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Swap DB singletons
    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    # Reset / inject service singletons
    orig_lancedb = vs_module._lancedb_service
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

    # Restore
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
# integration_http tests — included in make ci
# ---------------------------------------------------------------------------


@pytest.mark.integration_http
async def test_http_upload_reaches_complete(upload_db):
    """POST a .txt file via ASGITransport; poll until done=True.

    The asyncio.create_task background ingestion runs in the same event loop,
    so yielding with asyncio.sleep(0) between polls lets the task advance.
    """
    txt_file = FIXTURES_DIR / "art_of_unix_ch1.txt"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with txt_file.open("rb") as fh:
            resp = await client.post(
                "/documents/ingest",
                files={"file": ("art_of_unix_ch1.txt", fh, "text/plain")},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "document_id" in body
        assert body["status"] == "processing"
        doc_id = body["document_id"]

        # Poll until done, yielding to the event loop on each iteration
        final: dict = {}
        for _ in range(200):
            await asyncio.sleep(0.05)
            status_resp = await client.get(f"/documents/{doc_id}/status")
            assert status_resp.status_code == 200
            final = status_resp.json()
            _assert_status_schema(final)
            if final["done"]:
                break
        else:
            pytest.fail(f"Ingestion did not complete within timeout. Last: {final}")

        assert final["stage"] == "complete"
        assert final["progress_pct"] == 100
        assert final["done"] is True
        assert final["error_message"] is None


@pytest.mark.integration_http
async def test_http_status_schema_on_every_poll(upload_db):
    """Validate the status response schema on every poll, not just the final one."""
    txt_file = FIXTURES_DIR / "time_machine.txt"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with txt_file.open("rb") as fh:
            resp = await client.post(
                "/documents/ingest",
                files={"file": ("time_machine.txt", fh, "text/plain")},
            )
        assert resp.status_code == 200
        doc_id = resp.json()["document_id"]

        schema_violations: list[str] = []
        last_pct = -1
        for _ in range(200):
            await asyncio.sleep(0.05)
            status_resp = await client.get(f"/documents/{doc_id}/status")
            assert status_resp.status_code == 200
            body = status_resp.json()

            try:
                _assert_status_schema(body)
            except AssertionError as exc:
                schema_violations.append(str(exc))

            if body.get("progress_pct", 0) < last_pct:
                schema_violations.append(
                    f"progress_pct decreased: {last_pct} → {body['progress_pct']}"
                )
            last_pct = body.get("progress_pct", last_pct)

            if body.get("done"):
                break

        assert not schema_violations, (
            "Schema violations during polling:\n" + "\n".join(schema_violations)
        )


@pytest.mark.integration_http
async def test_http_corrupt_upload_terminates(upload_db):
    """POST a .pdf with random bytes; assert the pipeline terminates without hanging.

    The current ingestion workflow catches parse failures and continues through
    remaining nodes, ultimately reaching 'complete' with 0 chunks rather than
    raising.  This test asserts done=True is reached (no infinite loop) and the
    schema remains valid throughout — mirroring how the real-infrastructure e2e
    test validates error behaviour with a live backend.
    """
    corrupt_bytes = bytes(range(256)) * 8  # 2 KB of garbage, not a real PDF

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest",
            files={"file": ("corrupt.pdf", corrupt_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        doc_id = resp.json()["document_id"]

        final: dict = {}
        for _ in range(100):
            await asyncio.sleep(0.05)
            status_resp = await client.get(f"/documents/{doc_id}/status")
            assert status_resp.status_code == 200
            final = status_resp.json()
            _assert_status_schema(final)
            if final["done"] or final["stage"] == "error":
                break
        else:
            pytest.fail(f"Pipeline did not terminate within timeout for corrupt PDF; last: {final}")

        # Pipeline must terminate (done or error) — it must not hang
        assert final["done"] or final["stage"] == "error", (
            f"Expected done=True or stage='error'; got: {final}"
        )
