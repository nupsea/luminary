"""Deferred section summaries must survive the app stopping.

0.7.7 made deferral the path every local-model ingest takes. It had been the
rare path (>40 sections), and two things about it were survivable while rare and
are not now:

- Ingestion keeps its own `_background_tasks` set, and shutdown only ever
  drained `main`'s. The deferred task ran on against a closing database:
  `(sqlite3.ProgrammingError) Cannot operate on a closed database`.
- Nothing recorded that summaries were owed. A cancelled task lost them, and no
  later run would notice a document that was complete and had none.
"""

import inspect
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app import main as main_module
from app.models import SectionSummaryModel
from app.services import section_summarizer
from tests.test_document_summary_fast_path import (
    _insert_document,
    _insert_section_summaries,
    _insert_sections,
)


def test_shutdown_drains_the_ingestion_task_set_too():
    """Asserted as registration, not as a name in `lifespan`'s source.

    This read `"_ingestion_background_tasks" in inspect.getsource(lifespan)`, which
    pinned the hand-maintained import that was the defect: naming registries one at
    a time is how shutdown came to drain two of the ten that existed. Shutdown now
    drains whatever registered itself, so what has to hold is that the ingestion
    set is one of them.
    """
    from app.services import background  # noqa: PLC0415
    from app.workflows.ingestion_nodes import _shared  # noqa: PLC0415

    assert any(
        registry is _shared._background_tasks for registry in background._REGISTRIES.values()
    ), (
        "the ingestion nodes' task set is not registered, so shutdown cannot see "
        "it and deferred summaries will run on against a closing database"
    )


def test_a_repair_exists_for_summaries_a_shutdown_lost():
    assert callable(section_summarizer.resummarize_documents_missing_summaries)


def test_the_repair_is_bounded_per_boot():
    """Each document is one LLM call per section. A library that has never been
    summarised must not turn startup into an hours-long job competing with the
    user's first question."""
    sig = inspect.signature(section_summarizer.resummarize_documents_missing_summaries)
    assert sig.parameters["limit"].default > 0


def test_startup_schedules_the_repair():
    assert "backfill_section_summaries" in inspect.getsource(main_module.lifespan)


async def _section_summary_rows(factory, doc_id: str) -> list[SectionSummaryModel]:
    async with factory() as session:
        result = await session.execute(
            select(SectionSummaryModel)
            .where(SectionSummaryModel.document_id == doc_id)
            .order_by(SectionSummaryModel.unit_index)
        )
        return list(result.scalars().all())


async def _repair(mock_llm) -> int:
    with (
        patch("app.services.llm_routing.refusal", return_value=None),
        patch("app.services.summarizer.get_llm_service", return_value=mock_llm),
        patch("app.services.section_summarizer.get_llm_service", return_value=mock_llm),
    ):
        return await section_summarizer.resummarize_documents_missing_summaries()


async def test_the_repair_finishes_a_document_its_seed_batch_was_left_on(test_db):
    """A shutdown after the progressive seed leaves 3 rows of 10. The repair once
    selected only documents with none, so these stayed partial forever and their
    key points could never reach past the opening sections."""
    _engine, factory, _ = test_db
    await _insert_document(factory, "doc-partial")
    await _insert_sections(factory, "doc-partial", count=10)
    async with factory() as session:
        for i in range(3):
            session.add(
                SectionSummaryModel(
                    id=f"seed-{i}",
                    document_id="doc-partial",
                    section_id=f"sec-{i}",
                    heading=f"Section {i}",
                    content=f"Seed summary {i}.",
                    unit_index=i,
                )
            )
        await session.commit()

    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(
        side_effect=lambda messages, **_: f"Summary of {messages[1]['content'][:10].strip()}."
    )
    mock_llm.generate = AsyncMock(return_value="Key points.")

    assert await _repair(mock_llm) == 1

    rows = await _section_summary_rows(factory, "doc-partial")
    assert [r.section_id for r in rows] == [f"sec-{i}" for i in range(10)], (
        "resumed summaries must keep their section's place in the document"
    )
    assert rows[0].content == "Seed summary 0.", "the seed rows were replaced, not kept"
    assert mock_llm.complete.call_count == 7
    assert "Section 9" in mock_llm.generate.call_args_list[-1].args[0], (
        "the key points were not rebuilt from the finished sections"
    )


async def test_the_repair_leaves_a_grouped_document_alone(test_db):
    """Grouped summaries carry no section_id and are fewer than the sections by
    design; treating that as unfinished would re-summarise them every boot."""
    _engine, factory, _ = test_db
    await _insert_document(factory, "doc-grouped")
    await _insert_sections(factory, "doc-grouped", count=10)
    await _insert_section_summaries(factory, "doc-grouped", count=5)

    mock_llm = AsyncMock()
    assert await _repair(mock_llm) == 0
    mock_llm.complete.assert_not_awaited()
