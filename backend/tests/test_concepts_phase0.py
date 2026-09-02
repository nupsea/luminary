"""Phase 0 Concept foundation: schema, concept_service, scope_resolver.

Covers the studyable-atom primitive (docs/concepts.md): a Concept persisted across
SQLite (state) + Kuzu (topology) + LanceDB (derived centroid), scope resolution,
and mastery recompute (I-19).
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ConceptModel, FlashcardModel
from app.services.concept_service import get_concept_service
from app.services.graph import get_graph_service
from app.services.scope_resolver import resolve_daily, resolve_scope
from app.services.vector_store import get_lancedb_service


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    # fresh Kuzu under tmp_path (singleton is otherwise suite-wide)
    orig_graph = graph_module._graph_service
    graph_module._graph_service = None
    yield engine, factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    graph_module._graph_service = orig_graph


# LanceDB predicates are interpolated, so ids are shape-checked before they reach
# one (#95). These were "ch1"/"d1", which no ingest produces -- the check refused
# them and the centroid came back empty, which is the right answer for an id the
# process could not have generated.
_CH1 = "3f1c2b7a-8d94-4e2b-9c31-5a7e6b0d4f28"
_D1 = "c4a91e05-7b23-4d68-8f1a-2e9c3b5d7a64"


async def test_create_concept_spans_three_stores_and_resolves(test_db):
    _engine, factory = test_db
    get_lancedb_service().upsert_chunks(
        [{"chunk_id": _CH1, "document_id": _D1, "content_type": "text",
          "section_heading": "", "page": 0, "chunk_index": 0, "speaker": "",
          "text": "iceberg", "vector": [2.0] * 384}]
    )
    g = get_graph_service()
    g.upsert_document(_D1, "Doc", "book")
    g.upsert_entity("e1", "Iceberg", "concept")
    svc = get_concept_service()
    async with factory() as s:
        c = await svc.create_concept(
            s, label="Iceberg Manifests", origin="document", status="proposed",
            evidence=[{"document_id": _D1, "chunk_id": _CH1, "quote": "an iceberg"}],
            document_ids=[_D1], entity_ids=["e1"],
        )
        await svc.set_learning_state(s, c.id, mastery=42.0, stability=5.0)
        await s.commit()
        cid, slug = c.id, c.slug

    assert slug == "iceberg-manifests"
    # Kuzu topology
    assert g.get_concept_ids_for_documents([_D1]) == [cid]
    # LanceDB derived centroid
    assert get_lancedb_service().search_concepts([2.0] * 384, k=3)[0]["concept_id"] == cid
    # SQLite state + scope resolution
    async with factory() as s:
        row = await s.get(ConceptModel, cid)
        assert row.mastery == 42.0 and row.status == "proposed"
        assert await resolve_scope(s, "doc", _D1) == [cid]
        assert await resolve_daily(s) == [cid]
        assert await resolve_scope(s, "tag", "x") == []  # not-yet-wired scope


async def test_recompute_for_concepts_writes_grounded_mastery(test_db):
    """The assessment pipeline writes by-concept_id mastery to the row (I-19)."""
    from app.services.mastery_service import get_mastery_service

    _engine, factory = test_db
    async with factory() as s:
        s.add(ConceptModel(id="c9", slug="caching", label="Caching", kind="concept",
                           origin="document", status="confirmed", mastery=0.0))
        for i in range(2):
            s.add(FlashcardModel(id=f"fc{i}", document_id="d1", chunk_id=None, concept_id="c9",
                                 mapping_status="mapped", source="document", question="Q",
                                 answer="A", source_excerpt="e", fsrs_stability=21.0))
        await s.commit()

    async with factory() as s:
        await get_mastery_service().recompute_for_concepts(s, ["c9"])
        await s.commit()

    async with factory() as s:
        row = await s.get(ConceptModel, "c9")
    # stability 21 -> capped weighted 1.0 -> 100.0; mean stability 21
    assert abs(row.mastery - 100.0) < 1e-6
    assert abs(row.stability - 21.0) < 1e-6

