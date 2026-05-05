"""Tests for ClusteringService (S166)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import (
    ClusterSuggestionModel,
    CollectionMemberModel,
    CollectionModel,
    NoteModel,
)
from app.services.clustering_service import ClusteringService

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


def _make_note(content: str, note_id: str | None = None) -> NoteModel:
    now = datetime.now(UTC)
    return NoteModel(
        id=note_id or str(uuid.uuid4()),
        content=content,
        tags=[],
        created_at=now,
        updated_at=now,
    )


def _make_suggestion(
    status: str = "pending",
    created_at: datetime | None = None,
) -> ClusterSuggestionModel:
    return ClusterSuggestionModel(
        id=str(uuid.uuid4()),
        suggested_name="Test Cluster",
        note_ids=[str(uuid.uuid4())],
        confidence_score=0.9,
        status=status,
        created_at=created_at or datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Tests: cluster_notes
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cluster_notes_basic(test_db):
    """6-vector fixture: 3 closely similar + 3 noise -> exactly 1 cluster; noise notes excluded."""
    _engine, factory, _ = test_db

    # Group A: 3 very similar vectors (close to [1, 0.01, 0]) -- form 1 cluster
    group_a_ids = [str(uuid.uuid4()) for _ in range(3)]
    group_a_vecs = [
        np.array([1.0, 0.01, 0.00], dtype=np.float32),
        np.array([0.999, 0.012, 0.001], dtype=np.float32),
        np.array([0.998, 0.009, 0.002], dtype=np.float32),
    ]
    # Noise: 3 orthogonal (dissimilar) vectors -- HDBSCAN should label these -1
    noise_ids = [str(uuid.uuid4()) for _ in range(3)]
    noise_vecs = [
        np.array([0.0, 1.0, 0.0], dtype=np.float32),
        np.array([0.0, 0.0, 1.0], dtype=np.float32),
        np.array([0.5, 0.5, 0.7], dtype=np.float32),
    ]

    # Insert NoteModel rows so the service can fetch excerpts for LLM naming
    async with factory() as session:
        for nid in group_a_ids:
            session.add(_make_note("Quantum mechanics and wave functions", nid))
        for nid in noise_ids:
            session.add(_make_note("Random unrelated content", nid))
        await session.commit()

    all_ids = group_a_ids + noise_ids
    all_vecs = group_a_vecs + noise_vecs

    import pandas as pd

    mock_df = pd.DataFrame({"note_id": all_ids, "vector": all_vecs})
    mock_table = MagicMock()
    mock_table.to_pandas.return_value = mock_df

    # Mock HDBSCAN to return deterministic labels:
    # first 3 = cluster 0 (group A), last 3 = noise (-1)
    expected_labels = np.array([0, 0, 0, -1, -1, -1])
    mock_hdbscan_instance = MagicMock()
    mock_hdbscan_instance.fit_predict.return_value = expected_labels

    with (
        patch("app.services.vector_store.get_lancedb_service") as mock_lancedb,
        patch(
            "app.services.llm.litellm.acompletion",
            new_callable=AsyncMock,
        ) as mock_llm,
        patch("sklearn.cluster.HDBSCAN", return_value=mock_hdbscan_instance),
    ):
        mock_lancedb.return_value._get_or_create_note_table.return_value = mock_table
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Quantum Physics"
        mock_llm.return_value = mock_response

        svc = ClusteringService()
        async with factory() as session:
            count = await svc.cluster_notes(session)

    # Exactly 1 cluster (group A), noise notes excluded
    assert count == 1

    async with factory() as session:
        result = await session.execute(select(ClusterSuggestionModel))
        suggestions = list(result.scalars().all())

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.status == "pending"

    # Cluster members must be group_a_ids (noise notes with label=-1 are excluded)
    assert set(suggestion.note_ids) == set(group_a_ids), (
        f"Expected cluster members {set(group_a_ids)}, got {set(suggestion.note_ids)}"
    )
    # None of the noise note ids should appear in the suggestion
    for nid in noise_ids:
        assert nid not in suggestion.note_ids, f"Noise note {nid} should be excluded"


@pytest.mark.anyio
async def test_cluster_notes_rate_limited(test_db):
    """cluster_notes returns -1 and creates no new rows when rate-limited."""
    _engine, factory, _ = test_db

    # Insert a pending suggestion created just now
    async with factory() as session:
        session.add(_make_suggestion(status="pending"))
        await session.commit()

    svc = ClusteringService()
    async with factory() as session:
        result = await svc.cluster_notes(session)

    assert result == -1

    # Confirm no additional rows were inserted
    async with factory() as session:
        count = (await session.execute(select(ClusterSuggestionModel))).scalars().all()
    assert len(count) == 1  # Only the original suggestion


@pytest.mark.anyio
async def test_cluster_notes_too_few_vectors(test_db):
    """cluster_notes returns 0 when LanceDB has fewer than 3 note vectors."""
    _engine, factory, _ = test_db

    import pandas as pd

    mock_df = pd.DataFrame({"note_id": ["n1", "n2"], "vector": [np.zeros(3), np.ones(3)]})
    mock_table = MagicMock()
    mock_table.to_pandas.return_value = mock_df

    with patch("app.services.vector_store.get_lancedb_service") as mock_lancedb:
        mock_lancedb.return_value._get_or_create_note_table.return_value = mock_table
        svc = ClusteringService()
        async with factory() as session:
            result = await svc.cluster_notes(session)

    assert result == 0

    async with factory() as session:
        count = (await session.execute(select(ClusterSuggestionModel))).scalars().all()
    assert len(count) == 0


@pytest.mark.anyio
async def test_accept_creates_collection(test_db):
    """accept_suggestion creates NoteCollection and NoteCollectionMember rows."""
    _engine, factory, _ = test_db

    note_ids = [str(uuid.uuid4()) for _ in range(4)]

    # Insert NoteModel rows
    async with factory() as session:
        for nid in note_ids:
            session.add(_make_note("Some content", nid))
        await session.commit()

    # Insert a ClusterSuggestionModel
    suggestion_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            ClusterSuggestionModel(
                id=suggestion_id,
                suggested_name="My Cluster",
                note_ids=note_ids,
                confidence_score=0.85,
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    svc = ClusteringService()
    async with factory() as session:
        collection_id = await svc.accept_suggestion(suggestion_id, session)

    assert collection_id is not None

    async with factory() as session:
        # Collection created
        col = (
            await session.execute(
                select(CollectionModel).where(CollectionModel.id == collection_id)
            )
        ).scalar_one_or_none()
        assert col is not None
        assert col.name == "MY-CLUSTER"  # S201: normalize_collection_name applied

        # All 4 members created
        members = (
            (
                await session.execute(
                    select(CollectionMemberModel).where(
                        CollectionMemberModel.collection_id == collection_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(members) == 4
        assert {m.member_id for m in members} == set(note_ids)

        # Suggestion status updated
        suggestion = (
            await session.execute(
                select(ClusterSuggestionModel).where(ClusterSuggestionModel.id == suggestion_id)
            )
        ).scalar_one()
        assert suggestion.status == "accepted"


@pytest.mark.anyio
async def test_reject_sets_status(test_db):
    """reject_suggestion sets status=rejected."""
    _engine, factory, _ = test_db

    suggestion_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            ClusterSuggestionModel(
                id=suggestion_id,
                suggested_name="Test",
                note_ids=["n1"],
                confidence_score=0.7,
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    svc = ClusteringService()
    async with factory() as session:
        ok = await svc.reject_suggestion(suggestion_id, session)

    assert ok is True

    async with factory() as session:
        suggestion = (
            await session.execute(
                select(ClusterSuggestionModel).where(ClusterSuggestionModel.id == suggestion_id)
            )
        ).scalar_one()
        assert suggestion.status == "rejected"


@pytest.mark.anyio
async def test_accept_not_found(test_db):
    """accept_suggestion returns None for missing suggestion."""
    _engine, factory, _ = test_db

    svc = ClusteringService()
    async with factory() as session:
        result = await svc.accept_suggestion("nonexistent-id", session)
    assert result is None


@pytest.mark.anyio
async def test_reject_not_found(test_db):
    """reject_suggestion returns False for missing suggestion."""
    _engine, factory, _ = test_db

    svc = ClusteringService()
    async with factory() as session:
        result = await svc.reject_suggestion("nonexistent-id", session)
    assert result is False


# ---------------------------------------------------------------------------
# Tests: HTTP endpoints
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_post_cluster_endpoint(test_db):
    """POST /notes/cluster returns 202 with {queued: true}."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    # Patch the clustering service so the background task doesn't hit real LanceDB
    mock_svc = MagicMock()
    mock_svc.get_pending_last_run = AsyncMock(return_value=None)
    mock_svc.cluster_notes = AsyncMock(return_value=0)

    with patch(
        "app.services.clustering_service.get_clustering_service",
        return_value=mock_svc,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/notes/cluster")

    assert response.status_code == 202
    data = response.json()
    assert "queued" in data or "cached" in data


@pytest.mark.anyio
async def test_get_cluster_suggestions_empty(test_db):
    """GET /notes/cluster/suggestions returns [] when no pending suggestions."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/notes/cluster/suggestions")

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# Tests: batch_accept_suggestions (S189)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_batch_accept_creates_collections(test_db):
    """batch_accept_suggestions creates N collections with correct memberships."""
    _engine, factory, _ = test_db

    # Create notes
    note_ids_a = [str(uuid.uuid4()) for _ in range(3)]
    note_ids_b = [str(uuid.uuid4()) for _ in range(2)]

    async with factory() as session:
        for nid in note_ids_a + note_ids_b:
            session.add(_make_note("Content", nid))
        await session.commit()

    # Create two pending suggestions
    sid_a = str(uuid.uuid4())
    sid_b = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            ClusterSuggestionModel(
                id=sid_a,
                suggested_name="Group A",
                note_ids=note_ids_a,
                confidence_score=0.9,
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            ClusterSuggestionModel(
                id=sid_b,
                suggested_name="Group B",
                note_ids=note_ids_b,
                confidence_score=0.8,
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    svc = ClusteringService()
    async with factory() as session:
        created_ids = await svc.batch_accept_suggestions(
            [
                {"suggestion_id": sid_a, "name_override": None},
                {"suggestion_id": sid_b, "name_override": None},
            ],
            session,
        )

    assert len(created_ids) == 2

    # Verify collections and memberships
    async with factory() as session:
        for i, (cid, expected_note_ids) in enumerate(zip(created_ids, [note_ids_a, note_ids_b])):
            col = (
                await session.execute(
                    select(CollectionModel).where(CollectionModel.id == cid)
                )
            ).scalar_one()
            assert col is not None

            members = (
                (
                    await session.execute(
                        select(CollectionMemberModel).where(
                            CollectionMemberModel.collection_id == cid
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {m.member_id for m in members} == set(expected_note_ids)

        # Suggestions marked as accepted
        for sid in [sid_a, sid_b]:
            suggestion = (
                await session.execute(
                    select(ClusterSuggestionModel).where(ClusterSuggestionModel.id == sid)
                )
            ).scalar_one()
            assert suggestion.status == "accepted"


@pytest.mark.anyio
async def test_batch_accept_with_name_override(test_db):
    """batch_accept with name_override uses the override instead of suggested name."""
    _engine, factory, _ = test_db

    note_ids = [str(uuid.uuid4()) for _ in range(3)]
    async with factory() as session:
        for nid in note_ids:
            session.add(_make_note("Content", nid))
        await session.commit()

    sid = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            ClusterSuggestionModel(
                id=sid,
                suggested_name="Original Name",
                note_ids=note_ids,
                confidence_score=0.85,
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    svc = ClusteringService()
    async with factory() as session:
        created_ids = await svc.batch_accept_suggestions(
            [{"suggestion_id": sid, "name_override": "My Custom Name"}],
            session,
        )

    assert len(created_ids) == 1

    async with factory() as session:
        col = (
            await session.execute(
                select(CollectionModel).where(CollectionModel.id == created_ids[0])
            )
        ).scalar_one()
        assert col.name == "MY-CUSTOM-NAME"  # S201: normalize_collection_name applied


@pytest.mark.anyio
async def test_batch_accept_endpoint(test_db):
    """POST /notes/cluster/suggestions/batch-accept creates collections via HTTP."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    _engine, factory, _ = test_db

    note_ids = [str(uuid.uuid4()) for _ in range(3)]
    async with factory() as session:
        for nid in note_ids:
            session.add(_make_note("Content", nid))
        await session.commit()

    sid = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            ClusterSuggestionModel(
                id=sid,
                suggested_name="HTTP Test",
                note_ids=note_ids,
                confidence_score=0.9,
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/notes/cluster/suggestions/batch-accept",
            json={"items": [{"suggestion_id": sid, "name_override": "Renamed"}]},
        )

    assert response.status_code == 200
    data = response.json()
    assert "collection_ids" in data
    assert len(data["collection_ids"]) == 1

    # Verify collection name
    async with factory() as session:
        col = (
            await session.execute(
                select(CollectionModel).where(
                    CollectionModel.id == data["collection_ids"][0]
                )
            )
        ).scalar_one()
        assert col.name == "RENAMED"  # S201: normalize_collection_name applied
