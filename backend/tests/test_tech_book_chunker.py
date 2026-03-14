"""Tests for S131 — code-aware chunking.

Covers:
- AC1: tech_book and tech_article in ContentType (import check)
- AC2: _classify() identifies tech_book from fenced code blocks
- AC3: chunk_mixed_content preserves a 50-line Python function intact
- AC4: _parse_ast_signature valid and malformed cases
- AC5: CodeSnippetModel table exists after create_all_tables
- AC6: integration test ingests a Markdown doc with fenced code blocks
- AC7: GET /documents/{id}/code_snippets returns correct responses
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, CodeSnippetModel, DocumentModel, SectionModel
from app.services.tech_book_chunker import (
    _parse_ast_signature,
    chunk_mixed_content,
)
from app.workflows.ingestion import ContentType, _chunk_tech_book, _classify

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TECH_DOC_WITH_CODE = """\
# Python Tutorial

This tutorial covers Python functions.

```python
def add(a, b):
    return a + b
```

Now let's look at classes:

```python
class Counter:
    def __init__(self):
        self.count = 0

    def increment(self):
        self.count += 1
```

More content about Python follows.

```python
def subtract(x, y):
    return x - y
```

Final thoughts on Python.
"""

FIFTY_LINE_FUNCTION = (
    "def compute_fibonacci(n: int) -> list[int]:\n"
    "    \"\"\"Return the first n Fibonacci numbers.\"\"\"\n"
    + ("    pass  # placeholder line\n" * 47)
    + "    return []\n"
)


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

    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)

    yield tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _make_doc(doc_id: str, content_type: str = "tech_book") -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title="Test Tech Book",
        format="md",
        content_type=content_type,
        word_count=300,
        page_count=0,
        file_path="/tmp/test.md",
        stage="chunking",
        tags=[],
    )


# ---------------------------------------------------------------------------
# AC1: ContentType includes tech_book and tech_article
# ---------------------------------------------------------------------------


def test_content_type_includes_tech_types():
    """tech_book and tech_article must be valid values of ContentType literal."""
    import typing

    args = typing.get_args(ContentType)
    assert "tech_book" in args
    assert "tech_article" in args


# ---------------------------------------------------------------------------
# AC2: _classify() detects tech_book from >= 3 fenced code blocks
# ---------------------------------------------------------------------------


def test_classify_tech_book_from_code_fences():
    """A file with >= 3 fenced code blocks must classify as 'tech_book'."""
    raw_text = (
        "Some intro text.\n\n"
        "```python\nprint('hello')\n```\n\n"
        "More text.\n\n"
        "```javascript\nconsole.log('hi');\n```\n\n"
        "Even more.\n\n"
        "```bash\necho hello\n```\n\n"
        "Closing remarks."
    )
    result = _classify(raw_text, [], word_count=100, file_ext="md")
    assert result == "tech_book", f"Expected 'tech_book', got '{result}'"


def test_classify_regular_book_not_overridden():
    """A file without code fences and with chapters still classifies as 'book'."""
    headings = [
        {"heading": "Chapter 1", "level": 1, "text": ""},
        {"heading": "Chapter 2", "level": 1, "text": ""},
        {"heading": "Chapter 3", "level": 1, "text": ""},
    ]
    raw_text = "word " * 50000
    result = _classify(raw_text, headings, word_count=50000, file_ext="txt")
    assert result == "book"


# ---------------------------------------------------------------------------
# AC3: chunk_mixed_content preserves 50-line Python function intact
# ---------------------------------------------------------------------------


def test_atomic_code_block_not_split():
    """A 50-line Python function must produce one atomic code chunk."""
    section_text = "Some intro prose.\n\n```python\n" + FIFTY_LINE_FUNCTION + "\n```\n\nSome outro."

    chunks = chunk_mixed_content(
        section_text,
        section_id="sec-1",
        doc_id="doc-1",
        chunk_size=500,
        chunk_overlap=80,
    )

    code_chunks = [c for c in chunks if c["is_code_block"]]
    assert len(code_chunks) == 1, f"Expected 1 code chunk, got {len(code_chunks)}"

    code_text = code_chunks[0]["text"]
    assert "compute_fibonacci" in code_text, "Function name must appear in code chunk"
    assert code_chunks[0]["has_code"] is True
    assert code_chunks[0]["code_language"] == "python"
    # Function body must be intact: all 49 placeholder lines present
    assert code_text.count("pass  # placeholder line") == 47


def test_prose_chunks_have_code_false():
    """Prose chunks must have has_code=False."""
    section_text = "Simple prose with no code blocks. " * 10
    chunks = chunk_mixed_content(section_text, None, "doc-x", 300, 60)
    assert all(not c["has_code"] for c in chunks)


# ---------------------------------------------------------------------------
# AC4: _parse_ast_signature
# ---------------------------------------------------------------------------


def test_ast_signature_valid_function():
    source = "def foo(a, b):\n    return a + b\n"
    sig = _parse_ast_signature(source, "python")
    assert sig is not None
    assert "foo" in sig
    assert "a" in sig and "b" in sig


def test_ast_signature_valid_class():
    source = "class MyCounter:\n    pass\n"
    sig = _parse_ast_signature(source, "python")
    assert sig is not None
    assert "MyCounter" in sig


def test_ast_signature_malformed_no_raise():
    """Malformed Python code must return None without raising."""
    source = "def broken(:\n    pass\n"
    sig = _parse_ast_signature(source, "python")
    assert sig is None


def test_ast_signature_non_python_returns_none():
    source = "function hello() { return 42; }"
    sig = _parse_ast_signature(source, "javascript")
    assert sig is None


def test_ast_signature_no_definitions():
    source = "x = 1 + 2\n"
    sig = _parse_ast_signature(source, "python")
    assert sig is None


# ---------------------------------------------------------------------------
# AC5: CodeSnippetModel table exists after create_all_tables
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_snippets_table_exists(test_db):
    """After create_all_tables, the code_snippets table must be queryable."""
    async with db_module._session_factory() as session:
        result = await session.execute(select(CodeSnippetModel))
        rows = result.scalars().all()
    assert rows == []  # empty table, no rows yet


@pytest.mark.asyncio
async def test_chunk_model_has_code_columns(test_db):
    """ChunkModel rows must accept has_code, code_language, code_signature columns."""
    doc_id = str(uuid.uuid4())
    async with db_module._session_factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="ColTest",
                format="md",
                content_type="tech_book",
                word_count=0,
                page_count=0,
                file_path="/tmp/col.md",
                stage="complete",
                tags=[],
            )
        )
        await session.flush()
        chunk = ChunkModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            section_id=None,
            text="def hello(): pass",
            token_count=3,
            page_number=0,
            speaker=None,
            chunk_index=0,
            has_code=True,
            code_language="python",
            code_signature="def hello()",
        )
        session.add(chunk)
        await session.commit()

    async with db_module._session_factory() as session:
        result = await session.execute(select(ChunkModel).where(ChunkModel.document_id == doc_id))
        saved = result.scalar_one()
    assert saved.has_code is True
    assert saved.code_language == "python"
    assert saved.code_signature == "def hello()"


# ---------------------------------------------------------------------------
# AC6: Integration test — ingest a Markdown tech doc with fenced code blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_tech_book_creates_code_snippets(test_db):
    """Ingesting a Markdown doc with 3 fenced code blocks must create CodeSnippetModel rows."""
    from unittest.mock import patch

    from app.workflows.ingestion import IngestionState

    doc_id = str(uuid.uuid4())
    async with db_module._session_factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    state = IngestionState(
        document_id=doc_id,
        file_path="/tmp/tech.md",
        format="md",
        parsed_document={
            "title": "Test Tech Book",
            "format": "md",
            "pages": 1,
            "word_count": 200,
            "sections": [
                {
                    "heading": "Chapter 1",
                    "level": 1,
                    "text": TECH_DOC_WITH_CODE,
                    "page_start": 0,
                    "page_end": 0,
                }
            ],
            "raw_text": TECH_DOC_WITH_CODE,
        },
        content_type="tech_book",
        chunks=None,
        status="chunking",
        error=None,
        section_summary_count=None,
        audio_duration_seconds=None,
        _audio_chunks=None,
    )

    # Patch LiteLLM and LanceDB so no external calls are made
    with patch("app.services.vector_store.get_lancedb_service") as mock_vs:
        mock_vs.return_value.upsert_chunks.return_value = None
        result = await _chunk_tech_book(state, state["parsed_document"], doc_id)

    assert result["status"] == "embedding"
    assert len(result["chunks"]) >= 3  # at least the 3 code blocks

    # Verify CodeSnippetModel rows were created
    async with db_module._session_factory() as session:
        snippet_result = await session.execute(
            select(CodeSnippetModel).where(CodeSnippetModel.document_id == doc_id)
        )
        snippets = snippet_result.scalars().all()

    assert len(snippets) >= 1, "At least one CodeSnippetModel row expected"
    languages = {s.language for s in snippets}
    assert "python" in languages, "Python code blocks must produce snippets with language='python'"


# ---------------------------------------------------------------------------
# AC7: GET /documents/{id}/code_snippets endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_code_snippets_returns_empty_for_no_code_doc(test_db):
    """GET /documents/{id}/code_snippets returns [] for a doc with no code blocks."""
    doc_id = str(uuid.uuid4())
    async with db_module._session_factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Plain Book",
                format="txt",
                content_type="book",
                word_count=100,
                page_count=0,
                file_path="/tmp/plain.txt",
                stage="complete",
                tags=[],
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/code_snippets")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_code_snippets_returns_404_for_missing_doc(test_db):
    """GET /documents/{id}/code_snippets returns 404 for unknown document ID."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents/nonexistent-id/code_snippets")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_code_snippets_returns_snippets(test_db):
    """GET /documents/{id}/code_snippets returns snippets with language and signature."""
    doc_id = str(uuid.uuid4())
    snippet_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    sec_id = str(uuid.uuid4())

    async with db_module._session_factory() as session:
        session.add(_make_doc(doc_id))
        await session.flush()
        session.add(
            SectionModel(
                id=sec_id,
                document_id=doc_id,
                heading="Ch1",
                level=1,
                page_start=0,
                page_end=0,
                section_order=0,
                preview="",
            )
        )
        await session.flush()
        session.add(
            ChunkModel(
                id=chunk_id,
                document_id=doc_id,
                section_id=sec_id,
                text="def add(a, b): return a + b",
                token_count=6,
                page_number=0,
                speaker=None,
                chunk_index=0,
                has_code=True,
                code_language="python",
                code_signature="def add(a, b)",
            )
        )
        await session.flush()
        session.add(
            CodeSnippetModel(
                id=snippet_id,
                document_id=doc_id,
                chunk_id=chunk_id,
                section_id=sec_id,
                language="python",
                signature="def add(a, b)",
                content="def add(a, b): return a + b",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/code_snippets")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["language"] == "python"
    assert data[0]["signature"] == "def add(a, b)"
    assert "add" in data[0]["content"]
