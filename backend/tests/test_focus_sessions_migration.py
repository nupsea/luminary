"""focus_sessions was a second record of focus intervals that no UI wrote; the timer writes
pomodoro_sessions. Revision 5b7e0c2d9a41 copies any rows across and 1822f085552e drops it."""

import sqlite3

from app.database import make_engine
from app.db_init import _alembic_config, init_database


def _rows(db, sql: str) -> list[tuple]:
    c = sqlite3.connect(db)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


async def test_the_upgrade_moves_focus_sessions_into_pomodoros_then_drops_the_table(tmp_path):
    db = tmp_path / "lib.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await init_database(engine)
        async with engine.begin() as conn:

            def _downgrade(sync_conn) -> None:
                from alembic import command  # noqa: PLC0415

                command.downgrade(_alembic_config(sync_conn), "fd3501237c3a")

            await conn.run_sync(_downgrade)

        c = sqlite3.connect(db)
        c.executemany(
            "INSERT INTO focus_sessions (id, started_at, ended_at, planned_duration_minutes, "
            "session_type, completed, xp_awarded, created_at) "
            "VALUES (?, ?, ?, ?, 'study', ?, ?, ?)",
            [
                ("done", "2026-03-01 09:00", "2026-03-01 09:25", 25, 1, 20, "2026-03-01 09:00"),
                ("dropped", "2026-03-02 09:00", "2026-03-02 09:05", 25, 0, 0, "2026-03-02 09:00"),
                ("never-ended", "2026-03-03 09:00", None, 50, 0, 0, "2026-03-03 09:00"),
            ],
        )
        c.commit()
        c.close()

        await init_database(engine)

        assert _rows(
            db, "SELECT id, status, completed_at, focus_minutes FROM pomodoro_sessions ORDER BY id"
        ) == [
            ("done", "completed", "2026-03-01 09:25", 25),
            ("dropped", "abandoned", None, 25),
            ("never-ended", "abandoned", None, 50),
        ]
        assert not _rows(db, "SELECT name FROM sqlite_master WHERE name = 'focus_sessions'")
    finally:
        await engine.dispose()
