"""Concept corrections + overrides (P2e): rename/reclassify/reject/merge record an
Override keyed by slug, and apply_overrides re-applies them after re-parse (I-22).
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ConceptModel, FlashcardModel, NoteModel, OverrideModel
from app.services.concept_service import get_concept_service


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
    orig_graph = graph_module._graph_service
    graph_module._graph_service = None
    yield factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    graph_module._graph_service = orig_graph


async def _add_concept(factory, cid, slug, label="L", kind="concept", status="proposed"):
    async with factory() as s:
        s.add(ConceptModel(id=cid, slug=slug, label=label, kind=kind,
                           origin="document", status=status, mastery=0.0))
        await s.commit()


async def test_rename_and_reject_record_overrides(test_db):
    factory = test_db
    await _add_concept(factory, "c1", "manifests", label="Manifest")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post("/concepts/c1/rename", json={"label": "Manifests"})
        assert r.status_code == 200 and r.json()["label"] == "Manifests"
        assert r.json()["slug"] == "manifests"  # slug stays stable on rename
        rej = await client.post("/concepts/c1/reject")
        assert rej.status_code == 204

    async with factory() as s:
        assert await s.get(ConceptModel, "c1") is None  # rejected -> gone
        ovs = (await s.execute(select(OverrideModel))).scalars().all()
    kinds = sorted(o.kind for o in ovs)
    assert kinds == ["reject_concept", "rename"]
    assert all(o.target_key == "manifests" for o in ovs)  # keyed by stable slug


async def test_merge_reassigns_cards_and_deletes_source(test_db):
    factory = test_db
    await _add_concept(factory, "src", "snapshots")
    await _add_concept(factory, "tgt", "manifests")
    async with factory() as s:
        s.add(FlashcardModel(id="f1", document_id="d1", chunk_id=None, concept_id="src",
                             mapping_status="mapped", source="document", question="Q",
                             answer="A", source_excerpt="e"))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post("/concepts/merge", json={"source_id": "src", "target_id": "tgt"})
    assert r.status_code == 200 and r.json()["id"] == "tgt"

    async with factory() as s:
        assert await s.get(ConceptModel, "src") is None
        card = await s.get(FlashcardModel, "f1")
        assert card.concept_id == "tgt"


async def test_concepts_for_note_unions_engagement_and_lexical(test_db):
    factory = test_db
    async with factory() as s:
        s.add(NoteModel(id="n1", content="We discuss caching strategies at length.",
                        title="Notes on caching"))
        # lexical: label appears in the note text
        s.add(ConceptModel(id="c_cache", slug="caching", label="caching", kind="concept",
                           origin="document", status="proposed", mastery=10.0))
        # engagement: mapped via a card, label NOT in the note text
        s.add(ConceptModel(id="c_snap", slug="snapshots", label="Snapshots", kind="concept",
                           origin="document", status="proposed", mastery=5.0))
        s.add(FlashcardModel(id="f1", document_id="d1", chunk_id=None, note_id="n1",
                             concept_id="c_snap", mapping_status="mapped", source="note",
                             question="Q", answer="A", source_excerpt="e"))
        # unrelated concept -- must NOT appear
        s.add(ConceptModel(id="c_other", slug="kafka", label="Kafka", kind="concept",
                           origin="document", status="proposed", mastery=0.0))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.get("/concepts/for-note/n1")
    assert r.status_code == 200, r.text
    ids = {c["id"] for c in r.json()}
    assert ids == {"c_cache", "c_snap"}  # lexical + engagement, not the unrelated one


async def test_apply_overrides_survives_reparse(test_db):
    """A rename + reject re-apply onto freshly re-created concepts with the same slug."""
    factory = test_db
    svc = get_concept_service()
    await _add_concept(factory, "c1", "caching", label="cache")
    await _add_concept(factory, "c2", "stale-thing", label="Stale")

    async with factory() as s:
        await svc.rename_concept(s, "c1", "Caching")
        await svc.reject_concept(s, "c2")  # records reject override for slug 'stale-thing'
        await s.commit()

    # simulate a re-parse: drop the concepts, recreate the same slugs fresh/proposed
    async with factory() as s:
        for cid in ("c1", "c2"):
            row = await s.get(ConceptModel, cid)
            if row:
                await s.delete(row)
        await s.commit()
    await _add_concept(factory, "n1", "caching", label="cache")        # fresh proposal
    await _add_concept(factory, "n2", "stale-thing", label="Stale")    # fresh proposal

    async with factory() as s:
        applied = await svc.apply_overrides(s)
        await s.commit()
    assert applied == 2

    async with factory() as s:
        caching = (await s.execute(
            select(ConceptModel).where(ConceptModel.slug == "caching")
        )).scalars().first()
        stale = (await s.execute(
            select(ConceptModel).where(ConceptModel.slug == "stale-thing")
        )).scalars().first()
    assert caching is not None and caching.label == "Caching"  # rename re-applied
    assert stale is None  # reject re-applied -> stays gone
