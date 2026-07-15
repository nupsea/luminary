"""Guards init_database's three boot states, on real files rather than :memory:.

The bridge path is the one that runs against every existing user database exactly
once, so its failure mode is silent and permanent.
"""

import sqlite3

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.database import make_engine
from app.db_init import _alembic_config, create_all_tables, init_database


def _revisions() -> tuple[str, str]:
    script = ScriptDirectory.from_config(_alembic_config(None))
    return script.get_base(), script.get_current_head()


def _version(db_path) -> str | None:
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = c.execute("select version_num from alembic_version").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        c.close()


async def test_fresh_database_is_built_and_stamped_at_head(tmp_path):
    db = tmp_path / "fresh.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await init_database(engine)
    finally:
        await engine.dispose()

    _, head = _revisions()
    assert _version(db) == head


async def test_legacy_database_is_bridged_then_migrated_to_head(tmp_path):
    # A pre-Alembic database: the ORM schema exists, nothing is stamped. This is the
    # state every existing user is in.
    db = tmp_path / "legacy.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await create_all_tables(engine)
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        assert _version(db) is None

        await init_database(engine)
    finally:
        await engine.dispose()

    base, head = _revisions()
    # Must land on HEAD, not on the baseline. Stamping the bridge at `head` instead of
    # at the baseline would mark every post-cutover revision as already-applied, and a
    # legacy database would skip all of them forever -- silently.
    assert _version(db) == head, (
        "legacy database did not reach head; post-baseline revisions were skipped"
    )
    if base != head:
        assert _version(db) != base


async def test_boot_is_idempotent(tmp_path):
    db = tmp_path / "twice.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await init_database(engine)
        first = _version(db)
        await init_database(engine)
        assert _version(db) == first
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "table",
    ["curricula", "curriculum_nodes", "glossary_terms", "assessment_events", "note_collections"],
)
async def test_orphan_tables_absent_after_boot(tmp_path, table):
    db = tmp_path / f"orphan_{table}.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await init_database(engine)
    finally:
        await engine.dispose()

    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        found = c.execute(
            "select name from sqlite_master where type='table' and name=?", (table,)
        ).fetchone()
    finally:
        c.close()
    assert found is None, f"{table} should not exist after migrations"
