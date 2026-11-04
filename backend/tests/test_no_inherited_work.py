"""A test starts with none of another test's queued work (#211): what a test leaves in the
shared database is settled before the next one, which a booting app would otherwise run."""

from __future__ import annotations

import shutil
import sqlite3

from inherited_work import settle_inherited_work


def _db(tmp_path, template):
    db = tmp_path / "luminary.db"
    shutil.copy(template, db)
    with sqlite3.connect(db) as con:
        for n, stage in enumerate(("complete", "error", "parsing", "embedding")):
            con.execute(
                "INSERT INTO documents (id, title, format, word_count, page_count, file_path, "
                "stage, tags, created_at, last_accessed_at) VALUES (?, 'Doc', 'txt', 0, 0, '/x', "
                "?, '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (f"d{n}", stage),
            )
        for n, status in enumerate(("done", "pending", "running", "skipped", "failed")):
            con.execute(
                "INSERT INTO enrichment_jobs (id, document_id, job_type, status, attempts, "
                "created_at) VALUES (?, 'd0', 'chapter_cards', ?, 0, CURRENT_TIMESTAMP)",
                (f"j{n}", status),
            )
    return db


def test_queued_jobs_and_stranded_ingestions_are_settled(tmp_path, _schema_template):
    db = _db(tmp_path, _schema_template)

    assert settle_inherited_work(db) == (4, 2)

    with sqlite3.connect(db) as con:
        jobs = [r[0] for r in con.execute("SELECT status FROM enrichment_jobs")]
        stages = dict(con.execute("SELECT id, stage FROM documents"))
    # `done` is history; every other status is one boot requeues (`requeue_for_boot`).
    assert jobs == ["done"]
    assert stages == {"d0": "complete", "d1": "error", "d2": "error", "d3": "error"}


def test_no_database_yet_is_nothing_to_settle(tmp_path):
    assert settle_inherited_work(tmp_path / "luminary.db") == (0, 0)


def test_a_database_without_its_schema_yet_is_nothing_to_settle(tmp_path):
    db = tmp_path / "luminary.db"
    sqlite3.connect(db).close()

    assert settle_inherited_work(db) == (0, 0)
