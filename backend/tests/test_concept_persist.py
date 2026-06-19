"""persist_concepts node (NW5): writes the named galaxy/constellation/concept hierarchy
to SQLite with parent_id chains + stable slug identity (docs/concept-model-design.md §6)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ConceptModel
from app.workflows.concept_nodes.persist import persist_concepts


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_e, orig_f = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    orig_g = graph_module._graph_service
    graph_module._graph_service = None
    yield factory
    db_module._engine, db_module._session_factory = orig_e, orig_f
    graph_module._graph_service = orig_g


def _state():
    cen = [0.1] * 384
    return {
        "dry_run": False,
        "entity_chunks": {"iceberg": ["ch1"], "parquet": ["ch2"]},
        "lateral_edges": [(0, 1, 0.6)],
        "galaxy_edges": [],
        "hierarchy": {
            "galaxies": [{
                "label": "Data Engineering", "entities": ["iceberg", "parquet", "spark"],
                "document_ids": ["d1"], "salience": 10.0, "constellation_idxs": [0],
            }],
            "constellations": [{
                "label": "Storage Formats", "entities": ["iceberg", "parquet"],
                "document_ids": ["d1"], "salience": 8.0, "concept_idxs": [0, 1], "parent_idx": 0,
            }],
            "concepts": [
                {"label": "iceberg", "sun": "iceberg", "entities": ["iceberg", "parquet"],
                 "document_ids": ["d1"], "salience": 5.0, "parent_idx": 0, "centroid": cen},
                {"label": "spark", "sun": "spark", "entities": ["spark"],
                 "document_ids": ["d1"], "salience": 3.0, "parent_idx": 0, "centroid": cen},
            ],
        },
    }


async def test_persist_writes_nested_hierarchy(test_db):
    factory = test_db
    async with factory() as s:
        await persist_concepts(_state())  # opens its own session via the factory
        rows = (await s.execute(select(ConceptModel))).scalars().all()

    by_level = {0: [], 1: [], 2: []}
    for r in rows:
        by_level[r.level].append(r)
    assert len(by_level[0]) == 1 and len(by_level[1]) == 1 and len(by_level[2]) == 2

    galaxy = by_level[0][0]
    constellation = by_level[1][0]
    assert galaxy.label == "Data Engineering" and galaxy.parent_id is None
    assert galaxy.slug.startswith("g-")
    assert constellation.parent_id == galaxy.id and constellation.slug.startswith("k-")
    for c in by_level[2]:
        assert c.parent_id == constellation.id and c.slug.startswith("c-")
    # stable identity: slug is a hash of the member signature, deterministic
    assert {c.label for c in by_level[2]} == {"iceberg", "spark"}


async def test_universe_drilldown(test_db):
    from app.routers.concepts import get_universe

    factory = test_db
    await persist_concepts(_state())
    async with factory() as s:
        sky = await get_universe(parent=None, session=s)
        assert len(sky.stars) == 1 and sky.parent is None
        galaxy = sky.stars[0]
        assert galaxy.level == 0 and galaxy.child_count == 1  # one constellation inside

        inside_galaxy = await get_universe(parent=galaxy.id, session=s)
        assert inside_galaxy.parent == galaxy.id
        assert len(inside_galaxy.stars) == 1
        constellation = inside_galaxy.stars[0]
        assert constellation.level == 1 and constellation.child_count == 2

        inside_con = await get_universe(parent=constellation.id, session=s)
        assert len(inside_con.stars) == 2  # the two concepts
        assert all(c.level == 2 and c.child_count == 0 for c in inside_con.stars)


async def test_persist_dry_run_writes_nothing(test_db):
    factory = test_db
    st = _state()
    st["dry_run"] = True
    async with factory() as s:
        await persist_concepts(st)
        rows = (await s.execute(select(ConceptModel))).scalars().all()
    assert rows == []
