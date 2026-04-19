"""Session-scoped fixture: ingest all three canonical books once per pytest session.

Usage in test files::

    pytest_plugins = ["conftest_books"]

    def test_something(all_books_ingested):
        doc_id = all_books_ingested["The Time Machine"]["doc_id"]
        ...

The fixture:
  - Verifies each book file exists and meets word_count_min from manifest.json.
  - Creates ONE shared SQLite file, LanceDB dir, and Kuzu dir in a session temp dir.
  - Ingests all 3 books with real ML (BAAI/bge-m3 + GLiNER); LiteLLM mocked to 'book'.
  - Records elapsed_seconds per book; asserts <= ingest_time_budget_seconds.
  - Asserts each document reaches stage='complete'.
  - Yields dict: book_name → {doc_id: str, elapsed_seconds: float}.
  - Restores all module-level singletons on teardown.

Event-loop strategy: ingestion runs inside asyncio.run() which creates its own
temporary event loop. After asyncio.run() returns, event-loop-bound singletons
(_engine, _session_factory) are reset to None so that subsequent async tests
create fresh connections via the module singleton pattern against the same
DATA_DIR (which remains set for the duration of the session fixture).
LanceDB and Kuzu singletons are synchronous so they can be reused directly.
"""

import asyncio
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
import app.services.retriever as retriever_module
import app.services.vector_store as vs_module

REPO_ROOT = Path(__file__).parent.parent.parent
MANIFEST_PATH = REPO_ROOT / "DATA" / "books" / "manifest.json"


# ---------------------------------------------------------------------------
# Async helpers (run inside asyncio.run())
# ---------------------------------------------------------------------------


async def _setup_db(data_dir: Path) -> async_sessionmaker:
    from app.database import make_engine
    from app.db_init import create_all_tables

    engine = make_engine(f"sqlite+aiosqlite:///{data_dir}/luminary.db")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Register in module singletons so services inside ingestion can use them.
    db_module._engine = engine  # type: ignore[assignment]
    db_module._session_factory = factory  # type: ignore[assignment]
    return factory


async def _ingest_book(
    book: dict,
    factory: async_sessionmaker,
    data_dir: Path,
) -> str:
    """Ingest one book; LiteLLM classify mocked to 'book'. Returns doc_id."""
    import litellm

    import app.services.llm as llm_module
    from app.models import DocumentModel
    from app.workflows.ingestion import run_ingestion

    mock_resp: Any = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "book"
    mock_resp.usage = None

    orig_acompletion = getattr(litellm, "acompletion", None)
    litellm.acompletion = AsyncMock(return_value=mock_resp)  # type: ignore[attr-defined]
    llm_module._llm_service = None

    try:
        src = REPO_ROOT / book["filepath"]
        doc_id = str(uuid.uuid4())
        raw_dir = data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        dest = raw_dir / f"{doc_id}.txt"
        shutil.copy(src, dest)

        async with factory() as session:
            session.add(
                DocumentModel(
                    id=doc_id,
                    title=book["name"],
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
        return doc_id
    finally:
        if orig_acompletion is not None:
            litellm.acompletion = orig_acompletion  # type: ignore[attr-defined]
        else:
            del litellm.acompletion  # type: ignore[attr-defined]
        llm_module._llm_service = None


async def _run_all_ingestions(
    manifest: list[dict],
    data_dir: Path,
) -> dict[str, dict]:
    """Set up DB, ingest all books sequentially, return results dict."""
    factory = await _setup_db(data_dir)
    results: dict[str, dict] = {}

    for book in manifest:
        name = book["name"]
        budget = book["ingest_time_budget_seconds"]
        t0 = time.monotonic()
        doc_id = await _ingest_book(book, factory, data_dir)
        elapsed = time.monotonic() - t0

        # Verify stage
        from app.models import DocumentModel

        async with factory() as session:
            doc = await session.get(DocumentModel, doc_id)
        stage = doc.stage if doc else "missing"
        assert stage == "complete", f"Book '{name}' reached stage='{stage}' instead of 'complete'"
        assert elapsed <= budget, (
            f"Ingestion of '{name}' took {elapsed:.0f}s, budget is {budget}s. "
            f"Optimise the pipeline before increasing this budget."
        )
        results[name] = {"doc_id": doc_id, "elapsed_seconds": elapsed}
        print(
            f"[conftest_books] '{name}': doc_id={doc_id},"
            f" elapsed={elapsed:.1f}s / budget={budget}s, stage={stage}",
            flush=True,
        )

    return results


# ---------------------------------------------------------------------------
# Session-scoped fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def all_books_ingested(tmp_path_factory):
    """Ingest all three canonical books into a shared session-scoped environment.

    Yields dict mapping book name → {doc_id, elapsed_seconds}.

    Raises AssertionError immediately if any book file is missing, truncated,
    or fails to ingest within its time budget.
    """
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    # -- verify corpus files before any ingestion --
    for book in manifest:
        filepath = REPO_ROOT / book["filepath"]
        assert filepath.exists(), (
            f"Book file not found: {filepath}\nRun: ./scripts/corpus/setup_books.sh"
        )
        word_count = len(filepath.read_text(encoding="utf-8", errors="replace").split())
        assert word_count >= book["word_count_min"], (
            f"Book '{book['name']}' has {word_count} words "
            f"(minimum {book['word_count_min']}). File may be truncated.\n"
            f"Run: ./scripts/corpus/setup_books.sh"
        )

    # -- create isolated shared environment --
    data_dir = Path(str(tmp_path_factory.mktemp("books_shared")))
    prev_data_dir = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(data_dir)

    from app.config import get_settings

    get_settings.cache_clear()

    # Save originals
    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    orig_lancedb = vs_module._lancedb_service
    orig_graph = graph_module._graph_service
    orig_retriever = retriever_module._retriever

    # Reset so services re-create against data_dir
    db_module._engine = None  # type: ignore[assignment]
    db_module._session_factory = None  # type: ignore[assignment]
    vs_module._lancedb_service = None
    graph_module._graph_service = None
    retriever_module._retriever = None

    try:
        # Run ingestion inside an isolated event loop.
        # asyncio.run() creates and destroys a temporary event loop, which avoids
        # conflicts with the per-test event loops created by pytest-asyncio.
        results = asyncio.run(_run_all_ingestions(manifest, data_dir))

        # After asyncio.run(), the event loop is dead.
        # SQLAlchemy's async engine (_engine, _session_factory) is bound to that
        # dead loop, so reset them to None.  Tests will create fresh connections
        # that point to the same DATA_DIR database file.
        # LanceDB and Kuzu singletons are synchronous and remain valid.
        db_module._engine = None  # type: ignore[assignment]
        db_module._session_factory = None  # type: ignore[assignment]

        yield results

    finally:
        db_module._engine = orig_engine
        db_module._session_factory = orig_factory
        vs_module._lancedb_service = orig_lancedb
        graph_module._graph_service = orig_graph
        retriever_module._retriever = orig_retriever
        if prev_data_dir is not None:
            os.environ["DATA_DIR"] = prev_data_dir
        else:
            os.environ.pop("DATA_DIR", None)
        get_settings.cache_clear()
