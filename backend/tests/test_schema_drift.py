"""Guards that models.py and the Alembic revisions describe the same schema.

Fails when someone edits models.py without generating a revision. Runs against a
freshly built database on purpose: a long-lived dev database carries cosmetic
reflection noise (TEXT vs VARCHAR from the legacy ALTERs) and orphan tables from
removed features, which would drown the signal.
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.database import Base, make_engine
from app.db_init import alembic_include_name, create_all_tables


def _diff(sync_conn) -> list:
    ctx = MigrationContext.configure(
        sync_conn,
        opts={
            "target_metadata": Base.metadata,
            "include_name": alembic_include_name,
            "render_as_batch": True,
        },
    )
    return compare_metadata(ctx, Base.metadata)


async def _build(db_path):
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_all_tables(engine)
    return engine


async def _diff_for(db_path) -> list:
    engine = await _build(db_path)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(_diff)
    finally:
        await engine.dispose()


async def test_models_match_migrations(tmp_path):
    diffs = await _diff_for(tmp_path / "drift.db")

    assert diffs == [], (
        "models.py has drifted from the Alembic revisions. Generate a revision:\n"
        '  make db-revision m="describe your change"\n'
        f"Detected: {diffs}"
    )


async def test_drift_is_actually_detected(tmp_path):
    # A guard that cannot fail is not a guard. The column is added to the metadata
    # only AFTER the database is built, so it exists in one and not the other.
    from sqlalchemy import Column, String

    engine = await _build(tmp_path / "canary.db")
    table = Base.metadata.tables["documents"]
    col = Column("drift_canary", String())
    table.append_column(col)
    try:
        async with engine.connect() as conn:
            diffs = await conn.run_sync(_diff)
        assert any("drift_canary" in str(d) for d in diffs), (
            f"drift went undetected; got {diffs}"
        )
    finally:
        table._columns.remove(col)
        await engine.dispose()


async def test_fts_tables_are_not_dropped(tmp_path):
    # The FTS5 tables are absent from Base.metadata. Without the include_name filter
    # autogenerate proposes dropping them, which would silently destroy the search
    # index and the c0/c1/c2 shadow contract (I-4).
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'fts.db'}")
    try:
        await create_all_tables(engine)

        def _unfiltered(sync_conn) -> list:
            ctx = MigrationContext.configure(
                sync_conn, opts={"target_metadata": Base.metadata}
            )
            return compare_metadata(ctx, Base.metadata)

        async with engine.connect() as conn:
            unfiltered = await conn.run_sync(_unfiltered)
            filtered = await conn.run_sync(_diff)
    finally:
        await engine.dispose()

    assert any("_fts" in str(d) for d in unfiltered), (
        "expected unfiltered autogenerate to flag the FTS tables; if this fails the "
        "filter may no longer be load-bearing"
    )
    assert not any("_fts" in str(d) for d in filtered)
