"""Tests for naming migration endpoints (S199)."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    CanonicalTagModel,
    CollectionModel,
    NoteModel,
    NoteTagIndexModel,
)

# ---------------------------------------------------------------------------
# Fixture
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
# Tag migration tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tag_migration_merges_duplicates(test_db):
    """POST /tags/migrate-naming merges 'Python' and 'python' into 'python' with combined notes."""
    _, factory, _ = test_db

    note1_id = str(uuid.uuid4())
    note2_id = str(uuid.uuid4())

    async with factory() as session:
        # Create two notes with different casing of same tag
        session.add(
            NoteModel(
                id=note1_id,
                content="Note 1",
                tags=["Python"],
                document_id=None,
                group_name="manual",
            )
        )
        session.add(
            NoteModel(
                id=note2_id,
                content="Note 2",
                tags=["python"],
                document_id=None,
                group_name="manual",
            )
        )

        # Create canonical tags
        session.add(
            CanonicalTagModel(
                id="Python",
                display_name="Python",
                parent_tag=None,
                note_count=1,
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            CanonicalTagModel(
                id="python",
                display_name="python",
                parent_tag=None,
                note_count=1,
                created_at=datetime.now(UTC),
            )
        )

        # Create tag index rows
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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/tags/migrate-naming")
        assert resp.status_code == 200
        data = resp.json()
        assert data["merged"] >= 1

    # Verify: only 'python' canonical tag remains
    async with factory() as session:
        tags = (await session.execute(select(CanonicalTagModel))).scalars().all()
        tag_ids = [t.id for t in tags]
        assert "python" in tag_ids
        assert "Python" not in tag_ids

        # Both notes should now have normalized tag
        for nid in [note1_id, note2_id]:
            note = (
                await session.execute(select(NoteModel).where(NoteModel.id == nid))
            ).scalar_one()
            assert "python" in note.tags


@pytest.mark.anyio
async def test_collection_migration_merges_duplicates(test_db):
    """POST /collections/migrate-naming merges 'My Notes' and 'MY-NOTES'."""
    _, factory, _ = test_db

    col1_id = str(uuid.uuid4())
    col2_id = str(uuid.uuid4())
    note1_id = str(uuid.uuid4())
    note2_id = str(uuid.uuid4())

    async with factory() as session:
        # Create two collections that normalize to the same name
        session.add(
            CollectionModel(
                id=col1_id,
                name="My Notes",
                color="#6366F1",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            CollectionModel(
                id=col2_id,
                name="MY-NOTES",
                color="#8B5CF6",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

        # Create notes
        session.add(
            NoteModel(
                id=note1_id,
                content="Note 1",
                tags=[],
                document_id=None,
                group_name="manual",
            )
        )
        session.add(
            NoteModel(
                id=note2_id,
                content="Note 2",
                tags=[],
                document_id=None,
                group_name="manual",
            )
        )

        # Add members: col1 has 2 notes (more members), col2 has 1 note
        await session.execute(
            text(
                "INSERT INTO collection_members"
                " (id, member_id, collection_id, added_at, member_type)"
                " VALUES (:id, :nid, :cid, :at, 'note')"
            ),
            {
                "id": str(uuid.uuid4()),
                "nid": note1_id,
                "cid": col1_id,
                "at": datetime.now(UTC).isoformat(),
            },
        )
        await session.execute(
            text(
                "INSERT INTO collection_members"
                " (id, member_id, collection_id, added_at, member_type)"
                " VALUES (:id, :nid, :cid, :at, 'note')"
            ),
            {
                "id": str(uuid.uuid4()),
                "nid": note2_id,
                "cid": col1_id,
                "at": datetime.now(UTC).isoformat(),
            },
        )
        await session.execute(
            text(
                "INSERT INTO collection_members"
                " (id, member_id, collection_id, added_at, member_type)"
                " VALUES (:id, :nid, :cid, :at, 'note')"
            ),
            {
                "id": str(uuid.uuid4()),
                "nid": note2_id,
                "cid": col2_id,
                "at": datetime.now(UTC).isoformat(),
            },
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/collections/migrate-naming")
        assert resp.status_code == 200
        data = resp.json()
        assert data["merged"] >= 1

    # Verify: only one collection remains, named 'MY-NOTES'
    async with factory() as session:
        cols = (await session.execute(select(CollectionModel))).scalars().all()
        assert len(cols) == 1
        assert cols[0].name == "MY-NOTES"
        # The keeper should have the col1_id (more members)
        assert cols[0].id == col1_id


@pytest.mark.anyio
async def test_create_collection_normalizes_name(test_db):
    """POST /collections normalizes the name field."""
    _, factory, _ = test_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/collections",
            json={"name": "my notes", "color": "#6366F1"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "MY-NOTES"


@pytest.mark.anyio
async def test_create_tag_normalizes_id(test_db):
    """POST /tags normalizes the id field."""
    _, factory, _ = test_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/tags",
            json={"id": "Science/Cell_Division", "display_name": "Cell Division"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "science/cell-division"


@pytest.mark.anyio
async def test_sync_tag_index_normalizes(test_db):
    """_sync_tag_index normalizes tag slugs before creating index rows."""
    _, factory, _ = test_db

    note_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            NoteModel(
                id=note_id,
                content="Test",
                tags=["Machine Learning"],
                document_id=None,
                group_name="manual",
            )
        )
        await session.commit()

    from app.routers.notes import _sync_tag_index

    async with factory() as session:
        await _sync_tag_index(note_id, ["Machine Learning"], session)
        await session.commit()

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(NoteTagIndexModel.tag_full).where(NoteTagIndexModel.note_id == note_id)
                )
            )
            .scalars()
            .all()
        )
        assert "machine-learning" in rows
        assert "Machine Learning" not in rows


@pytest.mark.anyio
async def test_autocomplete_normalizes_query(test_db):
    """GET /tags/autocomplete normalizes the query parameter."""
    _, factory, _ = test_db

    async with factory() as session:
        session.add(
            CanonicalTagModel(
                id="machine-learning",
                display_name="machine-learning",
                parent_tag=None,
                note_count=5,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/tags/autocomplete?q=Machine%20Learning")
        assert resp.status_code == 200
        data = resp.json()
        # Should find 'machine-learning' even though query was 'Machine Learning'
        assert len(data) > 0
        assert data[0]["id"] == "machine-learning"
