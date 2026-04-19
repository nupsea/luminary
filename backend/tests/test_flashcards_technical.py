"""Tests for S137 — Technical flashcard types with Bloom's taxonomy levels."""

import json
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from stubs import MockLLMService as _MockLLMService

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, SectionModel
from app.services.flashcard import FlashcardService

# ---------------------------------------------------------------------------
# Fixtures (match pattern in test_flashcards.py)
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


def _make_doc(doc_id: str | None = None, **kwargs) -> DocumentModel:
    defaults = {
        "id": doc_id or str(uuid.uuid4()),
        "title": "Python Programming Guide",
        "format": "txt",
        "content_type": "tech_book",
        "word_count": 500,
        "page_count": 10,
        "file_path": "/tmp/tech.txt",
        "stage": "complete",
    }
    defaults.update(kwargs)
    return DocumentModel(**defaults)


def _make_section(
    section_id: str | None = None,
    doc_id: str = "doc-1",
    **kwargs,
) -> SectionModel:
    defaults = {
        "id": section_id or str(uuid.uuid4()),
        "document_id": doc_id,
        "heading": "Functions",
        "level": 1,
        "section_order": 0,
        "admonition_type": None,
    }
    defaults.update(kwargs)
    return SectionModel(**defaults)


def _make_chunk(
    chunk_id: str | None = None,
    doc_id: str = "doc-1",
    section_id: str | None = None,
    **kwargs,
) -> ChunkModel:
    defaults = {
        "id": chunk_id or str(uuid.uuid4()),
        "document_id": doc_id,
        "section_id": section_id,
        "text": "def add(a, b):\n    return a + b",
        "token_count": 12,
        "page_number": 1,
        "chunk_index": 0,
        "has_code": False,
    }
    defaults.update(kwargs)
    return ChunkModel(**defaults)


# ---------------------------------------------------------------------------
# AC3 — chunk with has_code=True produces trace/code_completion/debug card
# ---------------------------------------------------------------------------


async def test_generate_technical_code_chunk_produces_higher_bloom_card(test_db):
    """AC3: chunk with has_code=True yields card with flashcard_type in
    ('trace','code_completion','debug') and bloom_level in (3,4,5)."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    factorial_code = (
        "def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)"
    )
    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(
            _make_chunk(
                chunk_id,
                doc_id=doc_id,
                has_code=True,
                text=factorial_code,
            )
        )
        await session.commit()

    llm_json = json.dumps(
        [
            {
                "question": "What does factorial(3) return?",
                "answer": "6. Call stack: factorial(3)->3*factorial(2)->3*2*factorial(1)->3*2*1=6.",
                "source_excerpt": "def factorial(n):",
                "flashcard_type": "trace",
                "bloom_level": 4,
            }
        ]
    )
    mock_llm = _MockLLMService(response=llm_json)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_technical(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=1,
                session=session,
            )

    assert len(cards) == 1
    assert cards[0].flashcard_type in ("trace", "code_completion", "debug")
    assert cards[0].bloom_level in (3, 4, 5)


# ---------------------------------------------------------------------------
# AC4 — section with admonition_type='warning' produces definition card
# ---------------------------------------------------------------------------


async def test_generate_technical_warning_admonition_produces_definition(test_db):
    """AC4: section with admonition_type='warning' yields definition card at bloom_level=1."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    sec_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(
            _make_section(
                sec_id,
                doc_id=doc_id,
                heading="Memory Management",
                admonition_type="warning",
            )
        )
        session.add(
            _make_chunk(
                chunk_id,
                doc_id=doc_id,
                section_id=sec_id,
                text="WARNING: Never delete an object while iterating over it.",
            )
        )
        await session.commit()

    llm_json = json.dumps(
        [
            {
                "question": "What should you never do while iterating over an object?",
                "answer": "Delete it — this causes undefined behaviour.",
                "source_excerpt": "Never delete an object while iterating.",
                "flashcard_type": "definition",
                "bloom_level": 1,
            }
        ]
    )
    mock_llm = _MockLLMService(response=llm_json)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_technical(
                document_id=doc_id,
                scope="section",
                section_heading="Memory Management",
                count=1,
                session=session,
            )

    assert len(cards) == 1
    assert cards[0].flashcard_type == "definition"
    assert cards[0].bloom_level == 1


# ---------------------------------------------------------------------------
# AC5 — section heading with 'vs' or 'trade-off' yields design_decision card
# ---------------------------------------------------------------------------


async def test_generate_technical_tradeoff_heading_produces_design_decision(test_db):
    """AC5: section with heading containing 'vs' or 'trade-off' yields design_decision L5."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    sec_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(
            _make_section(
                sec_id,
                doc_id=doc_id,
                heading="List vs Tuple trade-off",
            )
        )
        session.add(
            _make_chunk(
                chunk_id,
                doc_id=doc_id,
                section_id=sec_id,
                text=(
                    "Lists are mutable sequences; tuples are immutable. "
                    "Use tuples for fixed data, lists when you need append/remove."
                ),
            )
        )
        await session.commit()

    llm_json = json.dumps(
        [
            {
                "question": "When should you choose a tuple over a list in Python?",
                "answer": (
                    "Choose a tuple when the data is fixed and must not change; "
                    "its immutability signals intent and allows hashing."
                ),
                "source_excerpt": "Lists are mutable; tuples are immutable.",
                "flashcard_type": "design_decision",
                "bloom_level": 5,
            }
        ]
    )
    mock_llm = _MockLLMService(response=llm_json)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_technical(
                document_id=doc_id,
                scope="section",
                section_heading="List vs Tuple trade-off",
                count=1,
                session=session,
            )

    assert len(cards) == 1
    assert cards[0].flashcard_type == "design_decision"
    assert cards[0].bloom_level == 5


# ---------------------------------------------------------------------------
# Regression guard — empty chunks returns []
# ---------------------------------------------------------------------------


async def test_generate_technical_returns_empty_when_no_chunks(test_db):
    """generate_technical() returns [] when the document has no chunks."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    mock_llm = _MockLLMService()

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_technical(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=5,
                session=session,
            )

    assert cards == []
    assert mock_llm.call_count == 0


# ---------------------------------------------------------------------------
# AC6 — stores both flashcard_type and bloom_level in DB
# ---------------------------------------------------------------------------


async def test_generate_technical_stores_type_and_bloom_level(test_db):
    """AC6 unit: generated card persists both flashcard_type and bloom_level."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    llm_json = json.dumps(
        [
            {
                "question": "What is Big-O for binary search?",
                "answer": "O(log n) — the search space halves each step.",
                "source_excerpt": "Binary search halves the search space.",
                "flashcard_type": "complexity",
                "bloom_level": 5,
            }
        ]
    )
    mock_llm = _MockLLMService(response=llm_json)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_technical(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=1,
                session=session,
            )

    assert len(cards) == 1
    assert cards[0].flashcard_type == "complexity"
    assert cards[0].bloom_level == 5


# ---------------------------------------------------------------------------
# AC6 integration — endpoint returns 201 with flashcard_type and bloom_level
# ---------------------------------------------------------------------------


async def test_generate_technical_endpoint_returns_201_with_type_fields(test_db):
    """AC6 integration: POST /flashcards/generate-technical returns 201 with typed cards."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    llm_json = json.dumps(
        [
            {
                "question": "What is the output of print(2 ** 3)?",
                "answer": "8",
                "source_excerpt": "2 ** 3",
                "flashcard_type": "trace",
                "bloom_level": 4,
            }
        ]
    )
    mock_llm = _MockLLMService(response=llm_json)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/flashcards/generate-technical",
                json={"document_id": doc_id, "scope": "full", "count": 1},
            )

    assert resp.status_code == 201
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["flashcard_type"] is not None
    assert data[0]["bloom_level"] is not None


# ---------------------------------------------------------------------------
# bloom_level string coercion
# ---------------------------------------------------------------------------


async def test_generate_technical_coerces_string_bloom_level(test_db):
    """generate_technical() coerces bloom_level string '4' to int 4."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    # LLM returns bloom_level as a string "4" instead of int 4
    llm_json = json.dumps(
        [
            {
                "question": "Apply the map function to double each element.",
                "answer": "list(map(lambda x: x * 2, items))",
                "source_excerpt": "map(lambda x: x * 2, items)",
                "flashcard_type": "code_completion",
                "bloom_level": "4",
            }
        ]
    )
    mock_llm = _MockLLMService(response=llm_json)

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            cards = await svc.generate_technical(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=1,
                session=session,
            )

    assert len(cards) == 1
    assert cards[0].bloom_level == 4
    assert isinstance(cards[0].bloom_level, int)


# ---------------------------------------------------------------------------
# Verify TECH_FLASHCARD_SYSTEM constant and usage in generate_technical
# ---------------------------------------------------------------------------


def test_tech_flashcard_system_constant_defined():
    """AC2: TECH_FLASHCARD_SYSTEM constant is defined in flashcard.py."""
    from app.services.flashcard import TECH_FLASHCARD_SYSTEM

    assert "Bloom's Taxonomy" in TECH_FLASHCARD_SYSTEM
    assert "bloom_level" in TECH_FLASHCARD_SYSTEM
    assert "trace" in TECH_FLASHCARD_SYSTEM
    assert "design_decision" in TECH_FLASHCARD_SYSTEM
    assert "code_completion" in TECH_FLASHCARD_SYSTEM


async def test_generate_technical_uses_tech_system_prompt_not_general(test_db):
    """AC2: generate_technical() passes TECH_FLASHCARD_SYSTEM, not FLASHCARD_SYSTEM."""
    from stubs import CapturingLLMService as _CapturingLLMService

    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_doc(doc_id))
        session.add(_make_chunk(chunk_id, doc_id=doc_id))
        await session.commit()

    mock_llm = _CapturingLLMService(response="[]")

    with patch("app.services.flashcard.get_llm_service", return_value=mock_llm):
        svc = FlashcardService()
        async with factory() as session:
            await svc.generate_technical(
                document_id=doc_id,
                scope="full",
                section_heading=None,
                count=1,
                session=session,
            )

    assert mock_llm.captured_systems, "LLM should have been called"
    system_used = mock_llm.captured_systems[0]
    assert "Bloom's Taxonomy" in system_used
    # Must NOT be the general literature system
    assert "characters" not in system_used
    assert "plot" not in system_used
