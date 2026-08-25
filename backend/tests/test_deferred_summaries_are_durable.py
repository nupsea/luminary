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

from app import main as main_module
from app.services import section_summarizer


def test_shutdown_drains_the_ingestion_task_set_too():
    source = inspect.getsource(main_module.lifespan)
    assert "_ingestion_background_tasks" in source, (
        "shutdown cancelled only main's tasks; ingestion keeps a separate set"
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
