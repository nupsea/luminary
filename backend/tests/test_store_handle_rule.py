"""A store handle opens only where the current library resolves (#388, `tools/layer_linter.py`)."""

import ast

import pytest

from tools.layer_linter import APP_DIR, check_file, check_store_handles


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("services/notes_service.py", "db = lancedb.connect(path)"),
        ("routers/documents.py", "engine = make_engine()"),
        ("services/qa.py", "factory = async_sessionmaker(engine)"),
        ("repos/note_repo.py", "con = sqlite3.connect(path)"),
        ("workflows/ingestion.py", "svc = LanceDBService('default')"),
        ("db_init.py", "engine = sqlalchemy.ext.asyncio.create_async_engine(url)"),
    ],
)
def test_a_handle_opened_outside_its_owner_is_refused(relative, source):
    violations = check_store_handles(relative, ast.parse(source))
    assert len(violations) == 1
    assert f"app/{relative}:1" in violations[0]


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("database.py", "engine = make_engine()"),
        ("services/vector_store.py", "db = lancedb.connect(path)"),
        ("services/notes_service.py", "svc = get_lancedb_service()"),
    ],
)
def test_the_owner_may_open_it(relative, source):
    assert check_store_handles(relative, ast.parse(source)) == []


def test_the_app_opens_no_handle_outside_its_owners():
    violations = [
        v
        for path in sorted(APP_DIR.rglob("*.py"))
        for v in check_file(path)
        if v.startswith("Store handle")
    ]
    assert violations == []
