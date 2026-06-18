"""POST /study/assemble -- the Study Launcher backend (docs/study-launcher.md).

A concept scope with a due mapped card yields a valid Study Event: the card comes
back, a StudyEvent row is recorded, and the preview counts match reality.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ConceptModel, FlashcardModel, NoteModel, StudyEventModel


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


async def test_assemble_concept_scope_yields_event_and_due_card(test_db):
    factory = test_db
    past = datetime.now(UTC) - timedelta(days=1)
    async with factory() as s:
        s.add(ConceptModel(id="c1", slug="iceberg", label="Iceberg", kind="concept",
                           origin="document", status="confirmed", mastery=10.0))
        s.add(FlashcardModel(id="f1", document_id="d1", chunk_id=None, concept_id="c1",
                             mapping_status="mapped", source="document", question="Q",
                             answer="A", source_excerpt="e", due_date=past))
        # not due -> must be excluded
        s.add(FlashcardModel(id="f2", document_id="d1", chunk_id=None, concept_id="c1",
                             mapping_status="mapped", source="document", question="Q2",
                             answer="A2", source_excerpt="e",
                             due_date=datetime.now(UTC) + timedelta(days=5)))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post(
            "/study/assemble",
            json={
                "scope_type": "concept",
                "scope_ref": "c1",
                "mode": "quick_quiz",
                "length_min": 5,
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert [c["id"] for c in body["cards"]] == ["f1"]
    assert body["concept_ids"] == ["c1"]
    assert body["preview"]["due_count"] == 1 and body["preview"]["mapped_count"] == 1
    assert body["preview"]["unmapped_count"] == 0
    assert body["preview"]["topic_mix"] == ["Iceberg"]
    assert body["teachback_available"] is False  # feynman labs off by default

    # a StudyEvent row was recorded
    async with factory() as s:
        events = (await s.execute(select(StudyEventModel))).scalars().all()
    assert len(events) == 1
    assert events[0].kind == "quick_quiz" and events[0].scope_type == "concept"
    assert events[0].scope_ref == "c1" and events[0].id == body["event_id"]


async def test_assemble_empty_scope_is_valid_empty_event(test_db):
    factory = test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post(
            "/study/assemble",
            json={"scope_type": "daily", "mode": "quick_quiz", "length_min": 5},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["cards"] == [] and body["preview"]["due_count"] == 0
    async with factory() as s:
        events = (await s.execute(select(StudyEventModel))).scalars().all()
    assert len(events) == 1  # event still recorded


async def test_assemble_note_scope_generates_unmapped_cards_on_commit(test_db, monkeypatch):
    """Lane B: Start on a note scope generates new cards, tagged unmapped + scoped."""
    factory = test_db
    async with factory() as s:
        s.add(NoteModel(id="n1", content="Caching strategies.", title="Caching"))
        await s.commit()

    # mock the shipped generator: persist + return one fresh card (no concept)
    async def fake_gen(self, tag, note_ids, count, session, difficulty="medium"):
        card = FlashcardModel(
            id="genned", document_id=None, chunk_id=None, note_id=note_ids[0],
            source="note", question="GQ", answer="GA", source_excerpt="e",
        )
        session.add(card)
        await session.flush()
        return [card]

    monkeypatch.setattr(
        "app.services.flashcard.FlashcardService.generate_from_notes", fake_gen
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post(
            "/study/assemble",
            json={"scope_type": "note", "scope_ref": "n1", "want_generated": True},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "genned" in [c["id"] for c in body["cards"]]
    assert body["preview"]["generated_count"] == 1
    assert body["preview"]["unmapped_count"] == 1

    async with factory() as s:
        card = await s.get(FlashcardModel, "genned")
    assert card.mapping_status == "unmapped" and card.source_scope == "note:n1"


async def test_assemble_preview_does_not_record_event(test_db):
    factory = test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post(
            "/study/assemble",
            json={"scope_type": "daily", "mode": "quick_quiz", "length_min": 5, "commit": False},
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["event_id"] == ""
    async with factory() as s:
        events = (await s.execute(select(StudyEventModel))).scalars().all()
    assert len(events) == 0  # preview writes nothing
