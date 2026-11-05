"""Work a test leaves in the session's shared database must not reach the next test.

Every `TestClient(app)` boots the default library on that one file, and boot returns running jobs
to the queue (`requeue_for_boot`) and resumes unfinished ingestions, so a stranded job ran in
whichever test booted next: beside its writers, answering its mocks (#211, #485). Measured over
the suite, 881 of 5,067 tests began with a stranded `chapter_cards` job.

A module of its own, as `task_drain` is: a test importing `conftest` would load a second copy of
it and re-patch the loop class (see `test_testclient_teardown_is_bounded`).
"""

import sqlite3
from pathlib import Path

_UNFINISHED_INGESTION = "left unfinished by an earlier test"


def settle_inherited_work(db: Path) -> tuple[int, int]:
    """Drop queued jobs and fail stranded ingestions in `db`: (jobs, documents)."""
    if not db.is_file():
        return 0, 0
    con = sqlite3.connect(db, timeout=30)
    try:
        # The file can exist before the schema does (a worker's first tests).
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        jobs = docs = 0
        if "enrichment_jobs" in tables:
            jobs = con.execute("DELETE FROM enrichment_jobs WHERE status != 'done'").rowcount
        if "documents" in tables:
            docs = con.execute(
                "UPDATE documents SET stage = 'error', error_message = ? "
                "WHERE stage NOT IN ('complete', 'error')",
                (_UNFINISHED_INGESTION,),
            ).rowcount
        con.commit()
    finally:
        con.close()
    return jobs, docs
