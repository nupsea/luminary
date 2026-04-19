"""Tests for S207: naming normalization detection and application."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import CanonicalTagModel, CollectionModel, NoteTagIndexModel
from app.services.clustering_service import ClusteringService

# ---------------------------------------------------------------------------
# Isolated test DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# AC12: detect_naming_violations returns suggestions for violating tag + collection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_naming_violations_tag_and_collection(test_db):
    """detect_naming_violations returns rename suggestions for
    'machine_learning' tag and 'Skill_Issue' collection."""
    _, factory, _ = test_db
    svc = ClusteringService()

    async with factory() as session:
        # Insert a tag with underscore
        session.add(
            CanonicalTagModel(
                id="machine_learning",
                display_name="machine_learning",
                parent_tag=None,
                note_count=3,
                created_at=datetime.now(UTC),
            )
        )
        # Insert a collection with underscore and mixed case
        session.add(
            CollectionModel(
                id=str(uuid.uuid4()),
                name="Skill_Issue_Analysis",
                color="#6366F1",
                sort_order=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

        violations = await svc.detect_naming_violations(session)

    tag_violations = [v for v in violations if v["type"] == "tag"]
    coll_violations = [v for v in violations if v["type"] == "collection"]

    assert len(tag_violations) >= 1
    tag_v = next(v for v in tag_violations if v["current_name"] == "machine_learning")
    assert tag_v["suggested_name"] == "machine-learning"
    assert tag_v["action"] == "rename"

    assert len(coll_violations) >= 1
    coll_v = next(v for v in coll_violations if v["current_name"] == "Skill_Issue_Analysis")
    assert coll_v["suggested_name"] == "SKILL-ISSUE-ANALYSIS"
    assert coll_v["action"] == "rename"


# ---------------------------------------------------------------------------
# AC3: Duplicate tags that normalize to the same slug detected for merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_naming_violations_duplicate_tags_merge(test_db):
    """Two tags that normalize to the same slug should produce merge suggestions."""
    _, factory, _ = test_db
    svc = ClusteringService()

    async with factory() as session:
        session.add(
            CanonicalTagModel(
                id="Machine-Learning",
                display_name="Machine-Learning",
                parent_tag=None,
                note_count=2,
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            CanonicalTagModel(
                id="machine_learning",
                display_name="machine_learning",
                parent_tag=None,
                note_count=5,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

        violations = await svc.detect_naming_violations(session)

    # At least one merge suggestion should exist
    merge_violations = [v for v in violations if v["action"] == "merge"]
    assert len(merge_violations) >= 1
    # Both should normalize to "machine-learning"
    for mv in merge_violations:
        assert mv["suggested_name"] == "machine-learning"


# ---------------------------------------------------------------------------
# AC13: normalize-apply renames a tag and updates NoteTagIndexModel rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_naming_fixes_renames_tag_and_index(test_db):
    """apply_naming_fixes renames a tag and updates NoteTagIndexModel rows."""
    _, factory, _ = test_db
    svc = ClusteringService()
    note_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            CanonicalTagModel(
                id="machine_learning",
                display_name="machine_learning",
                parent_tag=None,
                note_count=1,
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            NoteTagIndexModel(
                note_id=note_id,
                tag_full="machine_learning",
                tag_root="machine_learning",
                tag_parent="",
            )
        )
        await session.commit()

        fixes = [
            {
                "type": "tag",
                "id": "machine_learning",
                "current_name": "machine_learning",
                "suggested_name": "machine-learning",
                "action": "rename",
            }
        ]
        result = await svc.apply_naming_fixes(fixes, session)

    assert result["tags_renamed"] == 1

    # Verify the canonical tag was renamed
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT id FROM canonical_tags WHERE id = 'machine-learning'")
            )
        ).fetchone()
        assert row is not None

        # Old slug should be gone
        old_row = (
            await session.execute(
                text("SELECT id FROM canonical_tags WHERE id = 'machine_learning'")
            )
        ).fetchone()
        assert old_row is None

        # NoteTagIndexModel should be updated
        idx_row = (
            await session.execute(
                text("SELECT tag_full FROM note_tag_index WHERE note_id = :nid"),
                {"nid": note_id},
            )
        ).fetchone()
        assert idx_row is not None
        assert idx_row[0] == "machine-learning"

        # Tag alias should be created
        alias_row = (
            await session.execute(
                text("SELECT canonical_tag_id FROM tag_aliases WHERE alias = 'machine_learning'")
            )
        ).fetchone()
        assert alias_row is not None
        assert alias_row[0] == "machine-learning"


# ---------------------------------------------------------------------------
# AC5: normalize-apply renames collection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_naming_fixes_renames_collection(test_db):
    """apply_naming_fixes renames a collection with underscores."""
    _, factory, _ = test_db
    svc = ClusteringService()
    coll_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            CollectionModel(
                id=coll_id,
                name="My_Cool_Notes",
                color="#6366F1",
                sort_order=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

        fixes = [
            {
                "type": "collection",
                "id": coll_id,
                "current_name": "My_Cool_Notes",
                "suggested_name": "MY-COOL-NOTES",
                "action": "rename",
            }
        ]
        result = await svc.apply_naming_fixes(fixes, session)

    assert result["collections_renamed"] == 1

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT name FROM collections WHERE id = :cid"),
                {"cid": coll_id},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "MY-COOL-NOTES"


# ---------------------------------------------------------------------------
# Startup migration: tags normalized on create_all_tables
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_migration_normalizes_tags(tmp_path, monkeypatch):
    """create_all_tables normalizes pre-existing tags with underscores."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")

    # First pass: create tables
    await create_all_tables(engine)

    # Insert a denormalized tag directly
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO canonical_tags (id, display_name, parent_tag, note_count, created_at) "
                "VALUES ('data_science', 'data_science', NULL, 2, datetime('now'))"
            )
        )
        await session.execute(
            text(
                "INSERT INTO note_tag_index (note_id, tag_full, tag_root, tag_parent) "
                "VALUES ('note-1', 'data_science', 'data_science', '')"
            )
        )
        await session.commit()

    # Re-run create_all_tables to trigger migration
    await create_all_tables(engine)

    async with factory() as session:
        # Old tag should be gone
        old = (
            await session.execute(text("SELECT id FROM canonical_tags WHERE id = 'data_science'"))
        ).fetchone()
        assert old is None

        # Normalized tag should exist
        new = (
            await session.execute(text("SELECT id FROM canonical_tags WHERE id = 'data-science'"))
        ).fetchone()
        assert new is not None

        # Tag index should be updated
        idx = (
            await session.execute(
                text("SELECT tag_full FROM note_tag_index WHERE note_id = 'note-1'")
            )
        ).fetchone()
        assert idx is not None
        assert idx[0] == "data-science"

    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Already-normalized tags should be skipped (idempotent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_no_violations_when_normalized(test_db):
    """No violations reported for already-normalized names."""
    _, factory, _ = test_db
    svc = ClusteringService()

    async with factory() as session:
        session.add(
            CanonicalTagModel(
                id="machine-learning",
                display_name="machine-learning",
                parent_tag=None,
                note_count=1,
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            CollectionModel(
                id=str(uuid.uuid4()),
                name="WELL-NAMED",
                color="#6366F1",
                sort_order=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

        violations = await svc.detect_naming_violations(session)

    assert len(violations) == 0
