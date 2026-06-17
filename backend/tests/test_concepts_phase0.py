"""Phase 0 Concept foundation: schema, concept_service, scope_resolver, backfill.

Covers the studyable-atom primitive (docs/concepts.md): a Concept persisted across
SQLite (state) + Kuzu (topology) + LanceDB (derived centroid), scope resolution, and
the idempotent Entity->Concept backfill with mastery parity (I-19).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, ConceptModel, FlashcardModel
from app.scripts.backfill_concepts import backfill
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


async def _seed_doc_entity_chunk(factory):
    g = get_graph_service()
    g.upsert_document("d1", "Doc", "book")
    g.upsert_entity("e1", "Iceberg", "concept")
    g.add_mention("e1", "d1")
    get_lancedb_service().upsert_chunks(
        [
            {
                "chunk_id": "ch1", "document_id": "d1", "content_type": "text",
                "section_heading": "", "page": 0, "chunk_index": 0, "speaker": "",
                "text": "iceberg manifests", "vector": [1.0] * 384,
            }
        ]
    )
    async with factory() as s:
        s.add(ChunkModel(id="ch1", document_id="d1", section_id=None,
                         text="The iceberg manifests pattern.", chunk_index=0))
        s.add(FlashcardModel(id="f1", document_id="d1", chunk_id="ch1", source="document",
                             question="Q", answer="A", source_excerpt="e",
                             fsrs_stability=21.0, last_review=datetime.now(UTC)))
        s.add(FlashcardModel(id="f2", document_id="d1", chunk_id=None, source="note",
                             question="Q2", answer="A2", source_excerpt="e"))
        await s.commit()


async def test_create_concept_spans_three_stores_and_resolves(test_db):
    _engine, factory = test_db
    get_lancedb_service().upsert_chunks(
        [{"chunk_id": "ch1", "document_id": "d1", "content_type": "text",
          "section_heading": "", "page": 0, "chunk_index": 0, "speaker": "",
          "text": "iceberg", "vector": [2.0] * 384}]
    )
    g = get_graph_service()
    g.upsert_document("d1", "Doc", "book")
    g.upsert_entity("e1", "Iceberg", "concept")
    svc = get_concept_service()
    async with factory() as s:
        c = await svc.create_concept(
            s, label="Iceberg Manifests", origin="document", status="proposed",
            evidence=[{"document_id": "d1", "chunk_id": "ch1", "quote": "an iceberg"}],
            document_ids=["d1"], entity_ids=["e1"],
        )
        await svc.set_learning_state(s, c.id, mastery=42.0, stability=5.0)
        await s.commit()
        cid, slug = c.id, c.slug

    assert slug == "iceberg-manifests"
    # Kuzu topology
    assert g.get_concept_ids_for_documents(["d1"]) == [cid]
    # LanceDB derived centroid
    assert get_lancedb_service().search_concepts([2.0] * 384, k=3)[0]["concept_id"] == cid
    # SQLite state + scope resolution
    async with factory() as s:
        row = await s.get(ConceptModel, cid)
        assert row.mastery == 42.0 and row.status == "proposed"
        assert await resolve_scope(s, "doc", "d1") == [cid]
        assert await resolve_daily(s) == [cid]
        assert await resolve_scope(s, "tag", "x") == []  # not-yet-wired scope


async def test_backfill_creates_concepts_maps_cards_and_preserves_mastery(test_db):
    _engine, factory = test_db
    await _seed_doc_entity_chunk(factory)

    async with factory() as s:
        stats = await backfill(s)
    assert stats["concepts_created"] == 1 and stats["cards_mapped"] == 1

    async with factory() as s:
        concepts = (await s.execute(select(ConceptModel))).scalars().all()
        f1 = await s.get(FlashcardModel, "f1")
        f2 = await s.get(FlashcardModel, "f2")
    assert len(concepts) == 1
    c = concepts[0]
    assert f1.concept_id == c.id and f1.mapping_status == "mapped"
    # the note card matched no concept -> unmapped
    assert f2.concept_id is None and f2.mapping_status == "unmapped"
    # mastery parity: stability 21 -> capped 1.0 -> 100.0 (legacy formula preserved)
    assert abs(c.mastery - 100.0) < 1e-6


async def test_backfill_is_idempotent(test_db):
    _engine, factory = test_db
    await _seed_doc_entity_chunk(factory)
    async with factory() as s:
        await backfill(s)
    async with factory() as s:
        stats2 = await backfill(s)
    assert stats2["concepts_created"] == 0 and stats2["concepts_skipped"] == 1
    assert stats2["cards_mapped"] == 0
    async with factory() as s:
        concepts = (await s.execute(select(ConceptModel))).scalars().all()
    assert len(concepts) == 1
