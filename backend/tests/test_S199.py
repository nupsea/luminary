"""Tests for S199: Naming conventions -- normalize functions, endpoint normalization, migration.

Unit tests for pure normalize functions + integration tests for API normalization and migration.
"""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.services.naming import normalize_collection_name, normalize_tag_slug

# ---------------------------------------------------------------------------
# Pure unit tests: normalize_collection_name
# ---------------------------------------------------------------------------


class TestNormalizeCollectionName:
    def test_basic_spaces(self):
        assert normalize_collection_name("my notes") == "MY-NOTES"

    def test_underscores(self):
        assert normalize_collection_name("machine_learning") == "MACHINE-LEARNING"

    def test_extra_whitespace(self):
        assert normalize_collection_name("  DDIA  Book  ") == "DDIA-BOOK"

    def test_empty_string(self):
        assert normalize_collection_name("") == ""

    def test_only_spaces(self):
        assert normalize_collection_name("   ") == ""

    def test_numbers(self):
        assert normalize_collection_name("chapter 42") == "CHAPTER-42"

    def test_trailing_hyphens(self):
        assert normalize_collection_name("--hello--") == "HELLO"

    def test_mixed_separators(self):
        assert normalize_collection_name("foo_bar baz") == "FOO-BAR-BAZ"

    def test_consecutive_hyphens(self):
        assert normalize_collection_name("a---b") == "A-B"

    def test_already_normalized(self):
        assert normalize_collection_name("MY-NOTES") == "MY-NOTES"

    def test_unicode_passthrough(self):
        # Non-ASCII characters pass through, only separators change
        assert normalize_collection_name("cafe latte") == "CAFE-LATTE"


# ---------------------------------------------------------------------------
# Pure unit tests: normalize_tag_slug
# ---------------------------------------------------------------------------


class TestNormalizeTagSlug:
    def test_mixed_case_hierarchy(self):
        assert normalize_tag_slug("Science/Biology") == "science/biology"

    def test_spaces_to_hyphens(self):
        assert normalize_tag_slug("Machine Learning") == "machine-learning"

    def test_underscores_hierarchy(self):
        assert normalize_tag_slug("science/Cell_Division") == "science/cell-division"

    def test_empty_string(self):
        assert normalize_tag_slug("") == ""

    def test_only_spaces(self):
        assert normalize_tag_slug("   ") == ""

    def test_multiple_segments(self):
        assert normalize_tag_slug("A/B/C") == "a/b/c"

    def test_empty_segments_stripped(self):
        assert normalize_tag_slug("a//b") == "a/b"

    def test_leading_trailing_slashes(self):
        # Edge case: leading/trailing slashes produce empty segments
        assert normalize_tag_slug("/science/") == "science"

    def test_preserves_hierarchy(self):
        result = normalize_tag_slug("science/biology/cell-division")
        assert result == "science/biology/cell-division"

    def test_mixed_separators_in_segment(self):
        assert normalize_tag_slug("my_topic name") == "my-topic-name"

    def test_already_normalized(self):
        assert normalize_tag_slug("machine-learning") == "machine-learning"


# ---------------------------------------------------------------------------
# Integration test fixture
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
# Integration tests: POST endpoints normalize before insert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_collection_normalizes_name(test_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/collections",
            json={"name": "my notes", "color": "#6366F1"},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "MY-NOTES"


@pytest.mark.asyncio
async def test_post_tag_normalizes_id(test_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/tags",
            json={
                "id": "Science/Cell_Division",
                "display_name": "Cell Division",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["id"] == "science/cell-division"


@pytest.mark.asyncio
async def test_autocomplete_normalizes_query(test_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Create a tag first
        await client.post(
            "/tags",
            json={"id": "machine-learning", "display_name": "Machine Learning"},
        )
        # Query with un-normalized form
        resp = await client.get("/tags/autocomplete?q=Machine Learning")
        assert resp.status_code == 200
        results = resp.json()
        assert any(r["id"] == "machine-learning" for r in results)


# ---------------------------------------------------------------------------
# Integration tests: migration endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_tags_merges_duplicates(test_db):
    """Two tags 'Python' and 'python' should merge into 'python' with combined note count."""
    engine, factory, _ = test_db
    async with factory() as session:
        # Seed two canonical tags that normalize to the same slug
        now = "2026-01-01T00:00:00"
        await session.execute(
            text(
                "INSERT INTO canonical_tags (id, display_name, parent_tag, note_count, created_at)"
                " VALUES (:id, :dn, NULL, :nc, :ca)"
            ),
            {"id": "Python", "dn": "Python", "nc": 3, "ca": now},
        )
        await session.execute(
            text(
                "INSERT INTO canonical_tags (id, display_name, parent_tag, note_count, created_at)"
                " VALUES (:id, :dn, NULL, :nc, :ca)"
            ),
            {"id": "python", "dn": "python", "nc": 2, "ca": now},
        )

        # Seed notes with these tags and their index rows
        note1_id = str(uuid.uuid4())
        note2_id = str(uuid.uuid4())
        await session.execute(
            text(
                "INSERT INTO notes (id, content, tags, created_at, updated_at)"
                " VALUES (:id, :c, :tags, :ca, :ua)"
            ),
            {
                "id": note1_id,
                "c": "Note about Python",
                "tags": json.dumps(["Python"]),
                "ca": now,
                "ua": now,
            },
        )
        await session.execute(
            text(
                "INSERT INTO notes (id, content, tags, created_at, updated_at)"
                " VALUES (:id, :c, :tags, :ca, :ua)"
            ),
            {
                "id": note2_id,
                "c": "Another python note",
                "tags": json.dumps(["python"]),
                "ca": now,
                "ua": now,
            },
        )
        # Index rows
        await session.execute(
            text(
                "INSERT INTO note_tag_index (note_id, tag_full, tag_root, tag_parent)"
                " VALUES (:nid, :tf, :tr, :tp)"
            ),
            {"nid": note1_id, "tf": "Python", "tr": "Python", "tp": ""},
        )
        await session.execute(
            text(
                "INSERT INTO note_tag_index (note_id, tag_full, tag_root, tag_parent)"
                " VALUES (:nid, :tf, :tr, :tp)"
            ),
            {"nid": note2_id, "tf": "python", "tr": "python", "tp": ""},
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post("/tags/migrate-naming")
        assert resp.status_code == 200
        data = resp.json()
        assert data["merged"] >= 1

    # Verify: only 'python' canonical tag remains
    async with factory() as session:
        result = await session.execute(text("SELECT id, note_count FROM canonical_tags"))
        rows = result.all()
        tag_map = {r[0]: r[1] for r in rows}
        assert "python" in tag_map
        assert "Python" not in tag_map
        # Combined note count: both notes should be counted
        assert tag_map["python"] >= 2


@pytest.mark.asyncio
async def test_migrate_collections_merges_duplicates(test_db):
    """Two collections 'My Notes' and 'MY-NOTES' should merge, keeping the one with more members."""
    engine, factory, _ = test_db
    now = "2026-01-01T00:00:00"
    col_a_id = str(uuid.uuid4())
    col_b_id = str(uuid.uuid4())

    async with factory() as session:
        # Collection A: 'My Notes' with 3 members
        await session.execute(
            text(
                "INSERT INTO note_collections (id, name, color, sort_order, created_at, updated_at)"
                " VALUES (:id, :name, :color, 0, :ca, :ua)"
            ),
            {"id": col_a_id, "name": "My Notes", "color": "#6366F1", "ca": now, "ua": now},
        )
        # Collection B: 'MY-NOTES' with 1 member
        await session.execute(
            text(
                "INSERT INTO note_collections (id, name, color, sort_order, created_at, updated_at)"
                " VALUES (:id, :name, :color, 0, :ca, :ua)"
            ),
            {"id": col_b_id, "name": "MY-NOTES", "color": "#6366F1", "ca": now, "ua": now},
        )

        # Add members: 3 notes to A, 1 note to B
        for i in range(3):
            note_id = str(uuid.uuid4())
            await session.execute(
                text(
                    "INSERT INTO notes (id, content, tags, created_at, updated_at)"
                    " VALUES (:id, :c, '[]', :ca, :ua)"
                ),
                {"id": note_id, "c": f"Note A{i}", "ca": now, "ua": now},
            )
            await session.execute(
                text(
                    "INSERT INTO note_collection_members (id, note_id, collection_id, added_at)"
                    " VALUES (:id, :nid, :cid, :aa)"
                ),
                {"id": str(uuid.uuid4()), "nid": note_id, "cid": col_a_id, "aa": now},
            )

        note_b = str(uuid.uuid4())
        await session.execute(
            text(
                "INSERT INTO notes (id, content, tags, created_at, updated_at)"
                " VALUES (:id, :c, '[]', :ca, :ua)"
            ),
            {"id": note_b, "c": "Note B0", "ca": now, "ua": now},
        )
        await session.execute(
            text(
                "INSERT INTO note_collection_members (id, note_id, collection_id, added_at)"
                " VALUES (:id, :nid, :cid, :aa)"
            ),
            {"id": str(uuid.uuid4()), "nid": note_b, "cid": col_b_id, "aa": now},
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post("/collections/migrate-naming")
        assert resp.status_code == 200
        data = resp.json()
        assert data["merged"] >= 1

    # Verify: only one collection remains, named 'MY-NOTES', with all 4 members
    async with factory() as session:
        result = await session.execute(text("SELECT id, name FROM note_collections"))
        rows = result.all()
        assert len(rows) == 1
        assert rows[0][1] == "MY-NOTES"
        winner_id = rows[0][0]

        # The winner should be col_a (more members)
        assert winner_id == col_a_id

        # Count members
        member_result = await session.execute(
            text(
                "SELECT COUNT(*) FROM note_collection_members WHERE collection_id = :cid"
            ),
            {"cid": winner_id},
        )
        assert member_result.scalar() == 4
