"""persist_concepts node (NW5): writes the flat concept layer to SQLite with stable slug
identity + RELATED_TO edges, status honoured from score_concepts (concept-model-design.md §6)."""

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
        "hierarchy": {
            "concepts": [
                {"label": "iceberg", "sun": "iceberg", "entities": ["iceberg", "parquet"],
                 "document_ids": ["d1"], "salience": 5.0, "centroid": cen},
                {"label": "spark", "sun": "spark", "entities": ["spark"],
                 "document_ids": ["d1"], "salience": 3.0, "centroid": cen,
                 "status": "candidate"},
            ],
        },
    }


async def test_persist_writes_flat_concepts(test_db):
    factory = test_db
    async with factory() as s:
        await persist_concepts(_state())  # opens its own session via the factory
        rows = (await s.execute(select(ConceptModel))).scalars().all()

    # flat: every persisted node is a level-2 concept with no parent
    assert len(rows) == 2
    assert all(r.level == 2 and r.parent_id is None and r.slug.startswith("c-") for r in rows)
    # stable identity: slug is a hash of the member signature, deterministic
    assert {r.label for r in rows} == {"iceberg", "spark"}
    # score_concepts status is honoured (the second concept was flagged candidate)
    status_by_label = {r.label: r.status for r in rows}
    assert status_by_label["iceberg"] == "proposed"
    assert status_by_label["spark"] == "candidate"


async def test_persist_dry_run_writes_nothing(test_db):
    factory = test_db
    st = _state()
    st["dry_run"] = True
    async with factory() as s:
        await persist_concepts(st)
        rows = (await s.execute(select(ConceptModel))).scalars().all()
    assert rows == []
