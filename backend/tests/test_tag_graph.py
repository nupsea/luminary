"""Tests for TagGraphService co-occurrence computation and cache (S167)."""

import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import CanonicalTagModel, NoteTagIndexModel
from app.services.tag_graph import (
    build_tag_graph,
    invalidate_tag_graph_cache,
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


def _make_canonical_tag(
    tag_id: str, display_name: str, note_count: int, parent_tag: str | None = None
) -> CanonicalTagModel:
    return CanonicalTagModel(
        id=tag_id,
        display_name=display_name,
        parent_tag=parent_tag,
        note_count=note_count,
    )


def _make_index_row(note_id: str, tag_full: str) -> NoteTagIndexModel:
    segments = tag_full.split("/")
    return NoteTagIndexModel(
        note_id=note_id,
        tag_full=tag_full,
        tag_root=segments[0],
        tag_parent="/".join(segments[:-1]) if len(segments) > 1 else "",
    )


# ---------------------------------------------------------------------------
# Tests: co-occurrence weight correctness
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cooccurrence_weight(test_db):
    """Edge weights match expected co-occurrence counts for a known fixture."""
    engine, factory, _ = test_db

    # Setup:
    # note1: [python, rust]
    # note2: [python, rust]
    # note3: [python, go]
    # Expected edges: python-rust weight=2, python-go weight=1 (filtered out, < MIN_WEIGHT)
    note1 = str(uuid.uuid4())
    note2 = str(uuid.uuid4())
    note3 = str(uuid.uuid4())

    async with factory() as session:
        # Canonical tags (note_count values set for ordering)
        session.add_all(
            [
                _make_canonical_tag("python", "python", 3),
                _make_canonical_tag("rust", "rust", 2),
                _make_canonical_tag("go", "go", 1),
            ]
        )
        # note_tag_index rows
        session.add_all(
            [
                _make_index_row(note1, "python"),
                _make_index_row(note1, "rust"),
                _make_index_row(note2, "python"),
                _make_index_row(note2, "rust"),
                _make_index_row(note3, "python"),
                _make_index_row(note3, "go"),
            ]
        )
        await session.commit()

    # Ensure cache is empty before calling
    invalidate_tag_graph_cache()

    async with factory() as session:
        result = await build_tag_graph(session)

    # Should have 3 nodes
    node_ids = {n.id for n in result.nodes}
    assert "python" in node_ids
    assert "rust" in node_ids
    assert "go" in node_ids

    # Only python-rust edge should survive (weight=2 >= MIN_EDGE_WEIGHT=2)
    assert len(result.edges) == 1
    edge = result.edges[0]
    # Canonical ordering: tag_a < tag_b alphabetically
    assert frozenset([edge.tag_a, edge.tag_b]) == frozenset(["python", "rust"])
    assert edge.weight == 2

    # python-go pair has weight=1 and must be excluded
    edge_pairs = {frozenset([e.tag_a, e.tag_b]) for e in result.edges}
    assert frozenset(["python", "go"]) not in edge_pairs


@pytest.mark.anyio
async def test_cooccurrence_multiple_edges(test_db):
    """Multiple edges are returned when multiple pairs meet the weight threshold."""
    engine, factory, _ = test_db

    notes = [str(uuid.uuid4()) for _ in range(3)]

    async with factory() as session:
        session.add_all(
            [
                _make_canonical_tag("a", "a", 3),
                _make_canonical_tag("b", "b", 3),
                _make_canonical_tag("c", "c", 3),
            ]
        )
        for note_id in notes:
            for tag in ["a", "b", "c"]:
                session.add(_make_index_row(note_id, tag))
        await session.commit()

    invalidate_tag_graph_cache()

    async with factory() as session:
        result = await build_tag_graph(session)

    # All 3 pairs have weight=3 (>= 2), so 3 edges
    assert len(result.edges) == 3
    pairs = {frozenset([e.tag_a, e.tag_b]) for e in result.edges}
    assert frozenset(["a", "b"]) in pairs
    assert frozenset(["a", "c"]) in pairs
    assert frozenset(["b", "c"]) in pairs


# ---------------------------------------------------------------------------
# Tests: cache invalidation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cache_invalidation(test_db):
    """Generated_at changes after invalidate_tag_graph_cache() is called."""
    engine, factory, _ = test_db

    # Ensure cache is empty
    invalidate_tag_graph_cache()

    async with factory() as session:
        result1 = await build_tag_graph(session)

    ts1 = result1.generated_at

    # Slight sleep to ensure time.time() advances (it usually does, but just in case)
    time.sleep(0.01)

    # Second call without invalidation should return same cached result
    async with factory() as session:
        result2 = await build_tag_graph(session)

    assert result2.generated_at == ts1, "Second call should return cached result"

    # Invalidate and rebuild
    invalidate_tag_graph_cache()
    time.sleep(0.01)

    async with factory() as session:
        result3 = await build_tag_graph(session)

    assert result3.generated_at != ts1, "After invalidation, generated_at should change"


# ---------------------------------------------------------------------------
# Tests: GET /tags/graph HTTP endpoint
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_tag_graph_endpoint(test_db):
    """GET /tags/graph returns correct schema with nodes, edges, generated_at."""
    engine, factory, _ = test_db

    note1 = str(uuid.uuid4())
    note2 = str(uuid.uuid4())

    async with factory() as session:
        session.add_all(
            [
                _make_canonical_tag("x", "x", 2),
                _make_canonical_tag("y", "y", 2),
            ]
        )
        session.add_all(
            [
                _make_index_row(note1, "x"),
                _make_index_row(note1, "y"),
                _make_index_row(note2, "x"),
                _make_index_row(note2, "y"),
            ]
        )
        await session.commit()

    invalidate_tag_graph_cache()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/tags/graph")

    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert "generated_at" in data
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)
    assert isinstance(data["generated_at"], float)


@pytest.mark.anyio
async def test_get_tag_graph_endpoint_cache(test_db):
    """Two consecutive GET /tags/graph calls return the same generated_at (cache hit)."""
    engine, factory, _ = test_db

    invalidate_tag_graph_cache()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.get("/tags/graph")
        resp2 = await client.get("/tags/graph")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    ts1 = resp1.json()["generated_at"]
    ts2 = resp2.json()["generated_at"]
    assert ts1 == ts2, "Back-to-back calls should return the same cached generated_at"
