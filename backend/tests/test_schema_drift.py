"""Guards that models.py and the Alembic revisions describe the same schema.

Fails when someone edits models.py without generating a revision -- I-23's
failure mode, where the feature works on the author's machine and aborts boot on
every machine that already has data.

**The database under test is built by running the migrations**, which is the
whole point: a database built from `models.py` and then compared against
`models.py` agrees with itself no matter what the revisions say. It does not
use the dev database either -- a long-lived one carries cosmetic reflection
noise (TEXT vs VARCHAR from the legacy ALTERs) and orphan tables from removed
features, which would drown the signal. Same throwaway-database construction as
`make db-revision`, so the gate and the generator see the same diff.
"""

import os
import subprocess
import sys
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.database import Base, make_engine
from app.db_init import alembic_include_name, create_all_tables

BACKEND_DIR = Path(__file__).resolve().parents[1]


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


def _migrate(data_dir: Path) -> None:
    """Build a database by running every revision, as a real upgrade does.

    `alembic/env.py` takes its URL from `DATA_DIR` rather than from the config,
    so the directory is the only way to point a run at a throwaway database.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATA_DIR": str(data_dir)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr}"


async def _diff_for_migrated(data_dir: Path) -> list:
    _migrate(data_dir)
    engine = make_engine(f"sqlite+aiosqlite:///{data_dir / 'luminary.db'}")
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(_diff)
    finally:
        await engine.dispose()


async def test_models_match_migrations(tmp_path):
    diffs = await _diff_for_migrated(tmp_path / "migrated")

    assert diffs == [], (
        "models.py has drifted from the Alembic revisions. Generate a revision:\n"
        '  make db-revision m="describe your change"\n'
        f"Detected: {diffs}"
    )


async def test_a_model_change_with_no_revision_is_detected(tmp_path):
    """Fire the gate on purpose: a model column no revision creates must fail it.

    This is the case the gate exists for, and the version that built its
    database from `models.py` passed it -- the column was in both sides.
    """
    from sqlalchemy import Column, String

    table = Base.metadata.tables["documents"]
    col = Column("drift_canary", String())
    table.append_column(col)
    try:
        diffs = await _diff_for_migrated(tmp_path / "canary")
        assert any("drift_canary" in str(d) for d in diffs), (
            f"drift went undetected; got {diffs}"
        )
    finally:
        table._columns.remove(col)


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
