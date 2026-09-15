from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base
from app.db_init import create_all_tables


@pytest.mark.asyncio
async def test_db_init_normalization_collision():
    # Use an in-memory database for testing
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        # Step 1: Create schema (normally create_all_tables does this)
        await conn.run_sync(Base.metadata.create_all)

        # Step 2: Seed data that will cause a collision during normalization
        # Note 1 has both 'andrej_karpathy' and 'andrej-karpathy'
        now = datetime.now(UTC)
        await conn.execute(
            text(
                "INSERT INTO note_tag_index (note_id, tag_full, tag_root, tag_parent) "
                "VALUES (:nid, :tf, :tr, :tp)"
            ),
            {"nid": "note-1", "tf": "andrej_karpathy", "tr": "andrej_karpathy", "tp": ""},
        )
        await conn.execute(
            text(
                "INSERT INTO note_tag_index (note_id, tag_full, tag_root, tag_parent) "
                "VALUES (:nid, :tf, :tr, :tp)"
            ),
            {"nid": "note-1", "tf": "andrej-karpathy", "tr": "andrej-karpathy", "tp": ""},
        )

        await conn.execute(
            text(
                "INSERT INTO canonical_tags"
                "(id, display_name, parent_tag, usage_count, created_at) "
                "VALUES (:id, :dn, :pt, :nc, :ca)"
            ),
            {"id": "andrej_karpathy", "dn": "andrej_karpathy", "pt": None, "nc": 1, "ca": now},
        )
        await conn.execute(
            text(
                "INSERT INTO canonical_tags"
                "(id, display_name, parent_tag, usage_count, created_at) "
                "VALUES (:id, :dn, :pt, :nc, :ca)"
            ),
            {"id": "andrej-karpathy", "dn": "andrej-karpathy", "pt": None, "nc": 1, "ca": now},
        )

    # Step 3: Run create_all_tables (which includes the normalization migration)
    # It should not raise IntegrityError
    await create_all_tables(engine)

    # Step 4: Verify the result
    async with engine.begin() as conn:
        res = (await conn.execute(text("SELECT note_id, tag_full FROM note_tag_index"))).fetchall()
        # Should only have one row now
        assert len(res) == 1
        assert res[0][1] == "andrej-karpathy"

        # Canonical tag for old slug should be deleted
        old_tag = (
            await conn.execute(text("SELECT id FROM canonical_tags WHERE id = 'andrej_karpathy'"))
        ).fetchone()
        assert old_tag is None

        # New tag should have correct count (1, as it merged)
        new_tag = (
            await conn.execute(
                text("SELECT id, usage_count FROM canonical_tags WHERE id = 'andrej-karpathy'")
            )
        ).fetchone()
        assert new_tag is not None
        assert new_tag[1] == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_upgrade_head_recovers_from_unknown_branch_revision(tmp_path):
    from app.db_init import init_database

    db_path = tmp_path / "test.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    # Initialize DB normally first
    await init_database(test_engine)

    # Inject an unknown future revision into alembic_version
    async with test_engine.begin() as conn:
        await conn.execute(
            text("UPDATE alembic_version SET version_num = 'unknown_future_rev'")
        )

    # Running init_database again should not crash with CommandError;
    # it should recover and reset alembic_version to the current head.
    await init_database(test_engine)

    async with test_engine.begin() as conn:
        row = (
            await conn.execute(text("SELECT version_num FROM alembic_version"))
        ).fetchone()
        assert row is not None
        assert row[0] != "unknown_future_rev"

    await test_engine.dispose()
