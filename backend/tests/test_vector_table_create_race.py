"""Two first writers of a LanceDB table both get it, and it is created once (#195).

`POST /notes` embeds in a background task, so two notes on a fresh library reach
`_get_or_create_note_table` together. Both saw the table missing; on Windows the loser's
`create_table` said it existed and its `open_table` then said it did not.
"""

import threading

import lancedb
import pytest

from app.services.vector_store import NOTE_SCHEMA, NOTE_TABLE_NAME, LanceDBService


class _BothPastTheCheck:
    """A LanceDB connection whose first `list_tables` per thread waits for the other thread."""

    def __init__(self, db, barrier: threading.Barrier) -> None:
        self._db = db
        self._barrier = barrier
        self._seen = threading.local()
        self.creates = 0

    def list_tables(self):
        if not getattr(self._seen, "listed", False):
            self._seen.listed = True
            self._barrier.wait(timeout=5)
        return self._db.list_tables()

    def create_table(self, *args, **kwargs):
        self.creates += 1
        return self._db.create_table(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._db, name)


@pytest.mark.parametrize(
    "get_table",
    [
        LanceDBService._get_or_create_note_table,
        LanceDBService._get_table,
        LanceDBService._get_image_table,
        LanceDBService._get_or_create_concept_table,
    ],
)
def test_two_first_writers_of_a_table_both_get_it(tmp_path, get_table) -> None:
    svc = LanceDBService()
    db = _BothPastTheCheck(lancedb.connect(str(tmp_path)), threading.Barrier(2))
    svc._db = db
    tables, errors = [], []

    def open_it() -> None:
        try:
            tables.append(get_table(svc))
        except Exception as exc:  # noqa: BLE001 -- the assertion reports it
            errors.append(exc)

    workers = [threading.Thread(target=open_it) for _ in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=10)

    assert errors == []
    assert len(tables) == 2
    assert db.creates == 1


def test_note_table_keeps_its_schema(tmp_path) -> None:
    svc = LanceDBService()
    svc._db = lancedb.connect(str(tmp_path))
    assert svc._get_or_create_note_table().schema == NOTE_SCHEMA
    assert NOTE_TABLE_NAME in svc._db.list_tables().tables
