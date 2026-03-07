"""V2 ingestion performance benchmarks (S80).

Skipped unless LUMINARY_PERF_TESTS=1 is set.

Run:
    LUMINARY_PERF_TESTS=1 cd backend && \
        uv run pytest tests/test_v2_ingestion_perf.py -v -m slow --timeout=1200

Tests use the all_books_ingested fixture from conftest_books.py.
"""

import os
import time

import pytest
from sqlalchemy import delete, select

import app.database as db_module
from app.models import SectionSummaryModel, SummaryModel

pytest_plugins = ["tests.conftest_books"]
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not os.environ.get("LUMINARY_PERF_TESTS"),
        reason="Set LUMINARY_PERF_TESTS=1 to run performance benchmarks",
    ),
]


# ---------------------------------------------------------------------------
# (a) test_section_summarize_node_under_5_minutes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_summarize_node_under_5_minutes(all_books_ingested):
    """SectionSummarizerService.generate() for The Odyssey completes under 300 seconds."""
    doc_id = all_books_ingested["The Odyssey"]["doc_id"]

    # Delete existing section summaries to force regeneration
    async with db_module._session_factory() as session:
        await session.execute(
            delete(SectionSummaryModel).where(
                SectionSummaryModel.document_id == doc_id
            )
        )
        await session.commit()

    from app.services.section_summarizer import SectionSummarizerService

    service = SectionSummarizerService()
    t0 = time.monotonic()
    count = await service.generate(doc_id)
    elapsed = time.monotonic() - t0

    assert elapsed <= 300, (
        f"SectionSummarizerService.generate() took {elapsed:.0f}s for The Odyssey "
        f"(budget 300s). Generated {count} summaries."
    )
    assert count >= 10, f"Expected >= 10 section summaries, got {count}"


# ---------------------------------------------------------------------------
# (b) test_pregenerate_fast_path_under_3_minutes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pregenerate_fast_path_under_3_minutes(all_books_ingested):
    """pregenerate() with fast path for The Odyssey completes under 180 seconds."""
    doc_id = all_books_ingested["The Odyssey"]["doc_id"]

    # Ensure section summaries exist
    async with db_module._session_factory() as session:
        count_row = await session.execute(
            select(SectionSummaryModel.id).where(
                SectionSummaryModel.document_id == doc_id
            ).limit(1)
        )
        has_sections = count_row.scalar_one_or_none() is not None

    if not has_sections:
        pytest.skip("No section summaries for The Odyssey — run S75 tests first")

    # Delete existing summary rows to force regeneration
    async with db_module._session_factory() as session:
        await session.execute(
            delete(SummaryModel).where(SummaryModel.document_id == doc_id)
        )
        await session.commit()

    from app.services.summarizer import get_summarization_service

    svc = get_summarization_service()
    t0 = time.monotonic()
    await svc.pregenerate(doc_id)
    elapsed = time.monotonic() - t0

    assert elapsed <= 180, (
        f"pregenerate() took {elapsed:.0f}s for The Odyssey (budget 180s). "
        f"Fast path may not be active — check section summaries."
    )

    # Verify fast path was used: _section_reduce row should exist
    async with db_module._session_factory() as session:
        reduce_row = await session.execute(
            select(SummaryModel).where(
                SummaryModel.document_id == doc_id,
                SummaryModel.mode == "_section_reduce",
            )
        )
        assert reduce_row.scalar_one_or_none() is not None, (
            "_section_reduce row missing — fast path did not run"
        )
