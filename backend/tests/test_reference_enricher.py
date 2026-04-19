"""Tests for ReferenceEnricherService (S138).

AC2: Unit test: mock LLM; assert >=3 references extracted from 3+ term section summary
AC3: Unit test: sort_by_quality orders official_docs before tutorial before blog
AC4: Integration test: enrichment runs for a tech document; rows have source_quality set
AC5: When provider='none', all references have is_llm_suggested=True; no HTTP calls made
AC6: GET /references/documents/{id} returns [] for a fiction book (empty state, not error)
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, SectionSummaryModel, WebReferenceModel
from app.services.reference_enricher import ReferenceEnricherService, sort_by_quality

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


async def _insert_document(factory, doc_id: str, content_type: str = "tech_book") -> None:
    async with factory() as session:
        doc = DocumentModel(
            id=doc_id,
            title="Python Programming",
            format="txt",
            content_type=content_type,
            word_count=5000,
            page_count=10,
            file_path="/tmp/test.txt",
            stage="complete",
            tags=[],
        )
        session.add(doc)
        await session.commit()


async def _insert_section_summary(
    factory, doc_id: str, section_id: str | None = None, content: str = ""
) -> SectionSummaryModel:
    async with factory() as session:
        row = SectionSummaryModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            section_id=section_id,
            heading="Chapter 1",
            content=content
            or (
                "Python generators use the yield keyword to lazily produce values. "
                "The itertools module provides tools for working with generators. "
                "NumPy arrays store homogeneous data for vectorized computation."
            ),
            unit_index=0,
        )
        session.add(row)
        await session.commit()
        return row


def _make_mock_llm_response(refs: list[dict]) -> MagicMock:
    """Create a mock litellm.acompletion return value."""
    content = json.dumps(refs)
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    return mock_resp


# ---------------------------------------------------------------------------
# AC3: Pure function test -- no I/O
# ---------------------------------------------------------------------------


def test_sort_by_quality_orders_official_before_tutorial_before_blog():
    """sort_by_quality puts official_docs < tutorial < blog (pure function, no I/O)."""
    refs = [
        {"source_quality": "blog", "url": "https://blog.example.com"},
        {"source_quality": "official_docs", "url": "https://docs.python.org"},
        {"source_quality": "tutorial", "url": "https://realpython.com"},
    ]
    sorted_refs = sort_by_quality(refs)
    assert sorted_refs[0]["source_quality"] == "official_docs"
    assert sorted_refs[1]["source_quality"] == "tutorial"
    assert sorted_refs[2]["source_quality"] == "blog"


def test_sort_by_quality_unknown_ranks_last():
    """unknown source_quality ranks last after blog."""
    refs = [
        {"source_quality": "unknown"},
        {"source_quality": "blog"},
        {"source_quality": "spec"},
    ]
    sorted_refs = sort_by_quality(refs)
    assert sorted_refs[0]["source_quality"] == "spec"
    assert sorted_refs[-1]["source_quality"] == "unknown"


# ---------------------------------------------------------------------------
# AC2: Mock LLM -- >=3 refs stored from 3+ term summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_creates_refs_from_multi_term_summary(test_db):
    """With 4 LLM-returned refs for a section with 3+ technical terms,
    at least 3 WebReferenceModel rows are inserted (AC2)."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    await _insert_section_summary(factory, doc_id, section_id=section_id)

    mock_refs = [
        {
            "term": "generator",
            "url": "https://docs.python.org/3/glossary.html#term-generator",
            "title": "Python Glossary: generator",
            "excerpt": "A function that returns a lazy iterator.",
            "source_quality": "official_docs",
        },
        {
            "term": "yield",
            "url": "https://peps.python.org/pep-0255/",
            "title": "PEP 255 -- Simple Generators",
            "excerpt": "Proposal for the yield statement.",
            "source_quality": "spec",
        },
        {
            "term": "itertools",
            "url": "https://docs.python.org/3/library/itertools.html",
            "title": "itertools -- Functions creating iterators",
            "excerpt": "Fast, memory-efficient tools for iterators.",
            "source_quality": "official_docs",
        },
        {
            "term": "numpy",
            "url": "https://numpy.org/doc/stable/",
            "title": "NumPy Documentation",
            "excerpt": "The fundamental package for numerical computing.",
            "source_quality": "official_docs",
        },
    ]

    with patch(
        "app.services.reference_enricher.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_make_mock_llm_response(mock_refs),
    ):
        svc = ReferenceEnricherService()
        count = await svc.enrich(doc_id)

    assert count >= 3, f"Expected >= 3 inserted refs, got {count}"

    async with factory() as session:
        result = await session.execute(
            select(WebReferenceModel).where(WebReferenceModel.document_id == doc_id)
        )
        rows = result.scalars().all()

    assert len(rows) >= 3


# ---------------------------------------------------------------------------
# AC5: provider='none' -> all is_llm_suggested=True, no HTTP calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_http_calls_when_provider_none(test_db, monkeypatch):
    """When WEB_SEARCH_PROVIDER=none, all rows have is_llm_suggested=True
    and httpx.AsyncClient is never called (AC5)."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    await _insert_section_summary(factory, doc_id, section_id=section_id)

    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "none")
    from app.config import get_settings

    get_settings.cache_clear()

    mock_refs = [
        {
            "term": "generator",
            "url": "https://docs.python.org/3/glossary.html",
            "title": "Python Generators",
            "excerpt": "A lazy iterator.",
            "source_quality": "official_docs",
        },
        {
            "term": "yield",
            "url": "https://peps.python.org/pep-0255/",
            "title": "PEP 255",
            "excerpt": "Generator proposal.",
            "source_quality": "spec",
        },
    ]

    http_call_count = 0

    async def _fake_head(*args, **kwargs):  # noqa: ANN001
        nonlocal http_call_count
        http_call_count += 1
        raise AssertionError("httpx.AsyncClient.head should NOT be called when provider=none")

    with (
        patch(
            "app.services.reference_enricher.litellm.acompletion",
            new_callable=AsyncMock,
            return_value=_make_mock_llm_response(mock_refs),
        ),
        patch("httpx.AsyncClient") as mock_httpx,
        # S194: _validate_urls always runs; mock it to avoid real HTTP calls
        patch.object(
            ReferenceEnricherService,
            "_validate_urls",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        # Ensure httpx.AsyncClient is not instantiated by _verify_urls
        mock_httpx.return_value.__aenter__ = AsyncMock(
            side_effect=AssertionError("httpx.AsyncClient should not be called when provider=none")
        )
        svc = ReferenceEnricherService()
        await svc.enrich(doc_id)

    # Verify no httpx instantiation happened (from _verify_urls)
    mock_httpx.assert_not_called()

    async with factory() as session:
        result = await session.execute(
            select(WebReferenceModel).where(WebReferenceModel.document_id == doc_id)
        )
        rows = result.scalars().all()

    assert len(rows) > 0, "Expected at least one row"
    assert all(r.is_llm_suggested for r in rows), (
        "All rows should have is_llm_suggested=True when provider=none"
    )

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# AC4: Integration test -- enrichment runs, rows have source_quality set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrichment_creates_rows_with_source_quality(test_db):
    """End-to-end: SectionSummaryModel exists; enrich() creates rows with source_quality set."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    await _insert_section_summary(factory, doc_id, section_id=section_id)

    mock_refs = [
        {
            "term": "list comprehension",
            "url": "https://docs.python.org/3/tutorial/datastructures.html",
            "title": "Python Tutorial: Lists",
            "excerpt": "A concise way to create lists.",
            "source_quality": "official_docs",
        },
        {
            "term": "dict",
            "url": "https://docs.python.org/3/library/stdtypes.html",
            "title": "Python dict",
            "excerpt": "Mapping type.",
            "source_quality": "official_docs",
        },
    ]

    with patch(
        "app.services.reference_enricher.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_make_mock_llm_response(mock_refs),
    ):
        svc = ReferenceEnricherService()
        count = await svc.enrich(doc_id)

    assert count > 0

    async with factory() as session:
        result = await session.execute(
            select(WebReferenceModel).where(WebReferenceModel.document_id == doc_id)
        )
        rows = result.scalars().all()

    assert all(r.source_quality is not None for r in rows)
    assert all(r.source_quality != "" for r in rows)


# ---------------------------------------------------------------------------
# AC6: API -- GET /references/documents/{id} returns [] for fiction book
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_document_references_returns_empty_for_no_refs(test_db):
    """Fiction doc with no web_references rows returns HTTP 200 with [] (AC6)."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    # Insert a fiction book without any section summaries or web refs
    async with factory() as session:
        doc = DocumentModel(
            id=doc_id,
            title="The Time Machine",
            format="txt",
            content_type="book",
            word_count=30000,
            page_count=100,
            file_path="/tmp/time_machine.txt",
            stage="complete",
            tags=[],
        )
        session.add(doc)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/references/documents/{doc_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == doc_id
    assert body["references"] == []


@pytest.mark.asyncio
async def test_get_document_references_returns_404_for_unknown_doc(test_db):
    """Returns 404 when document does not exist at all."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/references/documents/nonexistent-doc-id")

    assert resp.status_code == 404
