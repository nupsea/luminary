"""Tests for ReferenceValidatorService and S194 reference validation endpoints.

AC8:  No external HTTP calls made during tests (httpx mocked)
AC9:  validate_references marks reachable URL as is_valid=True with last_checked_at set
AC10: validate_references marks unreachable URL as is_valid=False
AC11: GET /references excludes invalid refs by default; includes them with include_invalid=true
AC12: extraction + validation pipeline persists valid/invalid is_valid
"""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, SectionSummaryModel, WebReferenceModel
from app.services.reference_validator import ReferenceValidatorService

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


async def _insert_document(factory, doc_id: str) -> None:
    async with factory() as session:
        doc = DocumentModel(
            id=doc_id,
            title="Test Document",
            format="txt",
            content_type="tech_book",
            word_count=5000,
            page_count=10,
            file_path="/tmp/test.txt",
            stage="complete",
            tags=[],
        )
        session.add(doc)
        await session.commit()


async def _insert_ref(
    factory,
    doc_id: str,
    url: str = "https://example.com",
    is_valid: bool | None = None,
    term: str = "test",
) -> str:
    ref_id = str(uuid.uuid4())
    async with factory() as session:
        row = WebReferenceModel(
            id=ref_id,
            document_id=doc_id,
            section_id=str(uuid.uuid4()),
            term=term,
            url=url,
            title=f"Ref for {term}",
            excerpt="Test excerpt",
            source_quality="official_docs",
            is_llm_suggested=True,
            is_valid=is_valid,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.commit()
    return ref_id


# ---------------------------------------------------------------------------
# AC9: validate_references marks reachable URL as is_valid=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_marks_reachable_url_as_valid(test_db):
    """Reachable URL gets is_valid=True and last_checked_at set (AC9)."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    ref_id = await _insert_ref(factory, doc_id, url="https://docs.python.org")

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.head = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.reference_validator.httpx.AsyncClient", return_value=mock_client):
        svc = ReferenceValidatorService()
        result = await svc.validate_references(doc_id)

    assert result["valid"] == 1
    assert result["invalid"] == 0

    async with factory() as session:
        ref_result = await session.execute(
            select(WebReferenceModel).where(WebReferenceModel.id == ref_id)
        )
        ref = ref_result.scalar_one()

    assert ref.is_valid is True
    assert ref.last_checked_at is not None


# ---------------------------------------------------------------------------
# AC10: validate_references marks unreachable URL as is_valid=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_marks_unreachable_url_as_invalid(test_db):
    """Unreachable URL (timeout/4xx/5xx) gets is_valid=False (AC10)."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    ref_id = await _insert_ref(factory, doc_id, url="https://broken.example.com")

    mock_client = AsyncMock()
    mock_client.head = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.reference_validator.httpx.AsyncClient", return_value=mock_client):
        svc = ReferenceValidatorService()
        result = await svc.validate_references(doc_id)

    assert result["valid"] == 0
    assert result["invalid"] == 1

    async with factory() as session:
        ref_result = await session.execute(
            select(WebReferenceModel).where(WebReferenceModel.id == ref_id)
        )
        ref = ref_result.scalar_one()

    assert ref.is_valid is False
    assert ref.last_checked_at is not None


# ---------------------------------------------------------------------------
# AC10 variant: 404 status code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_marks_404_url_as_invalid(test_db):
    """URL returning 404 gets is_valid=False."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)
    ref_id = await _insert_ref(factory, doc_id, url="https://not-found.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.head = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.reference_validator.httpx.AsyncClient", return_value=mock_client):
        svc = ReferenceValidatorService()
        result = await svc.validate_references(doc_id)

    assert result["invalid"] == 1

    async with factory() as session:
        ref_result = await session.execute(
            select(WebReferenceModel).where(WebReferenceModel.id == ref_id)
        )
        ref = ref_result.scalar_one()
    assert ref.is_valid is False


# ---------------------------------------------------------------------------
# AC11: GET /references excludes invalid refs by default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_references_excludes_invalid_by_default(test_db):
    """GET /references/documents/{id} excludes is_valid=False (AC11)."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)

    # Insert one valid, one invalid, one unchecked ref
    await _insert_ref(factory, doc_id, url="https://valid.com", is_valid=True, term="valid")
    await _insert_ref(factory, doc_id, url="https://invalid.com", is_valid=False, term="invalid")
    await _insert_ref(factory, doc_id, url="https://unchecked.com", is_valid=None, term="unchecked")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Default: exclude invalid
        resp = await client.get(f"/references/documents/{doc_id}")
        assert resp.status_code == 200
        refs = resp.json()["references"]
        urls = [r["url"] for r in refs]
        assert "https://valid.com" in urls
        assert "https://unchecked.com" in urls
        assert "https://invalid.com" not in urls

        # include_invalid=true: show all
        resp2 = await client.get(
            f"/references/documents/{doc_id}", params={"include_invalid": "true"}
        )
        assert resp2.status_code == 200
        refs2 = resp2.json()["references"]
        urls2 = [r["url"] for r in refs2]
        assert "https://invalid.com" in urls2
        assert len(refs2) == 3


# ---------------------------------------------------------------------------
# AC12: extraction + validation pipeline sets is_valid on new refs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_validates_refs_before_persisting(test_db):
    """Reference extraction validates URLs; reachable = True, unreachable = False (AC12)."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)

    # Insert a section summary
    async with factory() as session:
        row = SectionSummaryModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            section_id=section_id,
            heading="Chapter 1",
            content="Python generators use yield.",
            unit_index=0,
        )
        session.add(row)
        await session.commit()

    mock_refs = [
        {
            "term": "generator",
            "url": "https://docs.python.org/gen",
            "title": "Generator docs",
            "excerpt": "Lazy iterator.",
            "source_quality": "official_docs",
        },
        {
            "term": "yield",
            "url": "https://broken.example.com/yield",
            "title": "Yield broken",
            "excerpt": "Broken link.",
            "source_quality": "tutorial",
        },
    ]

    # Mock LLM
    mock_llm_resp = MagicMock()
    mock_llm_resp.choices = [MagicMock()]
    mock_llm_resp.choices[0].message.content = json.dumps(mock_refs)

    # Mock URL validation: first URL reachable, second broken
    async def mock_validate_urls(urls):
        result = {}
        for url in urls:
            result[url] = "broken" not in url
        return result

    with (
        patch(
            "app.services.llm.litellm.acompletion",
            new_callable=AsyncMock,
            return_value=mock_llm_resp,
        ),
        patch(
            "app.services.reference_validator.ReferenceValidatorService.validate_urls",
            side_effect=mock_validate_urls,
        ),
    ):
        from app.services.reference_enricher import ReferenceEnricherService

        svc = ReferenceEnricherService()
        count = await svc.refresh_section(section_id=section_id, document_id=doc_id)

    assert count == 2

    async with factory() as session:
        result = await session.execute(
            select(WebReferenceModel).where(WebReferenceModel.document_id == doc_id)
        )
        rows = result.scalars().all()

    valid_rows = [r for r in rows if r.is_valid is True]
    invalid_rows = [r for r in rows if r.is_valid is False]
    assert len(valid_rows) >= 1
    assert len(invalid_rows) >= 1
    assert all(r.last_checked_at is not None for r in rows)


# ---------------------------------------------------------------------------
# Validate URLs helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_urls_returns_dict():
    """validate_urls returns {url: bool} dict."""
    mock_response_ok = MagicMock()
    mock_response_ok.status_code = 200

    mock_response_404 = MagicMock()
    mock_response_404.status_code = 404

    call_count = 0

    async def mock_head(url):
        nonlocal call_count
        call_count += 1
        if "good" in url:
            return mock_response_ok
        return mock_response_404

    mock_client = AsyncMock()
    mock_client.head = mock_head
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.reference_validator.httpx.AsyncClient", return_value=mock_client):
        svc = ReferenceValidatorService()
        result = await svc.validate_urls(["https://good.com", "https://bad.com"])

    assert result["https://good.com"] is True
    assert result["https://bad.com"] is False
