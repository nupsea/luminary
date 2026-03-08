"""Tests for S82: metadata section filtering and executive prompt synthesis.

(a) test_metadata_section_filtered_in_generate:
    A metadata section (heading='Terms of Use', text contains 'Project Gutenberg')
    causes litellm.acompletion to NOT be called for that section.

(b) test_metadata_section_filtered_in_build_input:
    SectionSummaryModel rows including one with metadata content are filtered out;
    the returned string does not contain 'Project Gutenberg'.

(c) test_build_input_returns_none_when_only_metadata:
    When fewer than 3 non-metadata rows remain after filtering, returns None.

(d) test_executive_prompt_not_listing_summaries:
    The executive system prompt contains 'synthesise' or 'overarching'.

(e) test_is_metadata_section_true_for_gutenberg:
    _is_metadata_section returns True for a known Gutenberg section.

(f) test_is_metadata_section_false_for_content:
    _is_metadata_section returns False for ordinary content sections.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import DocumentModel, SectionModel, SectionSummaryModel
from app.services.section_summarizer import (
    MIN_PREVIEW_LEN,
    SectionSummarizerService,
    _is_metadata_section,
)
from app.services.summarizer import MODE_INSTRUCTIONS, SummarizationService

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
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test Doc",
                format="txt",
                content_type="book",
                word_count=1000,
                page_count=10,
                file_path="/tmp/test.txt",
                stage="complete",
                tags=[],
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# (e) test_is_metadata_section_true_for_gutenberg — pure function, no DB
# ---------------------------------------------------------------------------


def test_is_metadata_section_true_for_gutenberg():
    assert (
        _is_metadata_section(
            "Project Gutenberg License",
            "This eBook is for use of anyone anywhere in the United States...",
        )
        is True
    )


def test_is_metadata_section_true_for_terms_heading():
    assert _is_metadata_section("Terms of Use", "Project Gutenberg is a non-profit.") is True


def test_is_metadata_section_true_for_copyright_in_text():
    assert (
        _is_metadata_section(
            "Legal Notice",
            "Copyright 2024 by the author. All rights reserved." + "x" * 500,
        )
        is True
    )


# ---------------------------------------------------------------------------
# (f) test_is_metadata_section_false_for_content — pure function, no DB
# ---------------------------------------------------------------------------


def test_is_metadata_section_false_for_content():
    assert (
        _is_metadata_section("Chapter 1", "Holmes examined the room carefully...") is False
    )


def test_is_metadata_section_false_for_named_characters():
    assert (
        _is_metadata_section(
            "The Adventure Begins",
            "Sherlock Holmes sat in his armchair, fingers steepled.",
        )
        is False
    )


# ---------------------------------------------------------------------------
# (a) test_metadata_section_filtered_in_generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metadata_section_filtered_in_generate(test_db):
    """litellm.acompletion is NOT called for a metadata section."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)

    # 3 qualifying content sections + 1 metadata section (also long enough to qualify by length)
    long_preview = "A" * (MIN_PREVIEW_LEN + 50)
    metadata_preview = (
        "Project Gutenberg is a non-profit organization. "
        + "x" * (MIN_PREVIEW_LEN + 10)
    )

    async with factory() as session:
        for i in range(3):
            session.add(
                SectionModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    heading=f"Chapter {i + 1}",
                    level=1,
                    page_start=i,
                    page_end=i,
                    section_order=i,
                    preview=long_preview,
                )
            )
        # Metadata section — long enough to pass MIN_PREVIEW_LEN but should be skipped
        session.add(
            SectionModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                heading="Terms of Use",
                level=1,
                page_start=99,
                page_end=99,
                section_order=99,
                preview=metadata_preview,
            )
        )
        await session.commit()

    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = "Summary text."

    with patch("litellm.acompletion", return_value=mock_response) as mock_llm:
        svc = SectionSummarizerService()
        inserted = await svc.generate(doc_id, concurrency=5)

    # Only 3 non-metadata sections should have triggered LLM calls
    assert inserted == 3, f"Expected 3 summaries (metadata skipped), got {inserted}"
    assert mock_llm.call_count == 3, (
        f"Expected 3 LLM calls (not 4), got {mock_llm.call_count}"
    )


# ---------------------------------------------------------------------------
# (b) test_metadata_section_filtered_in_build_input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metadata_section_filtered_in_build_input(test_db):
    """_build_section_summary_input excludes rows where _is_metadata_section is True."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)

    async with factory() as session:
        # 4 content rows
        for i in range(4):
            session.add(
                SectionSummaryModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    section_id=None,
                    heading=f"Chapter {i + 1}",
                    content=f"Holmes investigated the case in chapter {i + 1}.",
                    unit_index=i,
                )
            )
        # 1 metadata row — should be excluded from the output
        session.add(
            SectionSummaryModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                section_id=None,
                heading="License",
                content="Project Gutenberg terms of use apply to this eBook.",
                unit_index=10,
            )
        )
        await session.commit()

    svc = SummarizationService()
    result = await svc._build_section_summary_input(doc_id)

    assert result is not None, "Expected non-None result with 4 qualifying rows"
    assert "Project Gutenberg" not in result, (
        "Metadata content should be filtered from _build_section_summary_input output"
    )
    assert "Holmes" in result, "Content rows should still appear in the output"


# ---------------------------------------------------------------------------
# (c) test_build_input_returns_none_when_only_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_input_returns_none_when_only_metadata(test_db):
    """Returns None when fewer than 3 non-metadata rows remain after filtering."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)

    async with factory() as session:
        # 2 content rows (below the 3-row threshold)
        for i in range(2):
            session.add(
                SectionSummaryModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    section_id=None,
                    heading=f"Chapter {i + 1}",
                    content=f"Story content chapter {i + 1}.",
                    unit_index=i,
                )
            )
        # 3 metadata rows
        for i in range(3):
            session.add(
                SectionSummaryModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    section_id=None,
                    heading="Terms of Use",
                    content=f"Project Gutenberg license terms row {i}.",
                    unit_index=10 + i,
                )
            )
        await session.commit()

    svc = SummarizationService()
    result = await svc._build_section_summary_input(doc_id)

    assert result is None, (
        "Expected None when fewer than 3 non-metadata rows remain after filtering"
    )


# ---------------------------------------------------------------------------
# (d) test_executive_prompt_not_listing_summaries
# ---------------------------------------------------------------------------


def test_executive_prompt_not_listing_summaries():
    """The executive mode instruction contains synthesis language, not listing language."""
    instruction = MODE_INSTRUCTIONS["executive"].lower()
    assert "synthesise" in instruction or "overarching" in instruction, (
        f"Executive prompt should instruct the LLM to synthesise, not list. Got: {instruction!r}"
    )
