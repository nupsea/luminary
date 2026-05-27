"""GET /home/overview hub contract (plan 2E.8)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, FlashcardModel
from app.services.activity_service import ActivityService


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
    yield engine, factory
    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _doc(doc_id: str, title: str = "d") -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title=title,
        format="txt",
        content_type="book",
        word_count=1,
        page_count=0,
        file_path=f"/tmp/{doc_id}.txt",
        stage="complete",
        tags=[],
    )


@pytest.mark.anyio
async def test_overview_empty_state(test_db):
    """Fresh DB with nothing in it returns the expected zero-state shape."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/home/overview")).json()
        assert body["today_action"] is None
        assert body["recent_items"] == []
        assert body["active_collections"] == []
        assert body["recent_tags"] == []


@pytest.mark.anyio
async def test_recent_items_interleave_docs_and_notes_by_activity(test_db):
    _, factory = test_db
    d1, d2 = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(d1, "Doc One"))
        s.add(_doc(d2, "Doc Two"))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Create a note (auto-bumps activity).
        nr = await c.post("/notes", json={"content": "first note", "tags": [], "document_id": None})
        note_id = nr.json()["id"]
        # Let the real service create the activity rows, then rewrite all three
        # to explicit, well-separated timestamps so ordering is deterministic
        # regardless of system load. record_doc_read stamps wall-clock now();
        # under a busy full suite those stamps don't separate reliably, which
        # flaked this test (passed in isolation, failed under load).
        base = datetime(2026, 1, 1, tzinfo=UTC)
        async with factory() as s:
            await ActivityService(s).record_doc_read(d1)
            await ActivityService(s).record_doc_read(d2)
            for member_id, member_type, offset in (
                (note_id, "note", 0),
                (d1, "document", 1),
                (d2, "document", 2),
            ):
                await s.execute(
                    text(
                        "UPDATE content_activity SET last_meaningful_at = :t "
                        "WHERE member_type = :mt AND member_id = :i"
                    ),
                    {"t": base + timedelta(seconds=offset), "mt": member_type, "i": member_id},
                )
            await s.commit()

        body = (await c.get("/home/overview")).json()
        items = body["recent_items"]
        # d2 was bumped most recently, then d1, then the note (oldest).
        member_ids_in_order = [i["member_id"] for i in items]
        assert member_ids_in_order[0] == d2
        assert member_ids_in_order[1] == d1
        assert note_id in member_ids_in_order


@pytest.mark.anyio
async def test_today_action_is_review_when_cards_due(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    past_due = datetime.now(UTC) - timedelta(hours=1)
    async with factory() as s:
        s.add(_doc(doc_id))
        s.add(
            FlashcardModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                question="q",
                answer="a",
                source_excerpt="x",
                due_date=past_due,
            )
        )
        s.add(
            FlashcardModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                question="q2",
                answer="a2",
                source_excerpt="x",
                due_date=past_due,
            )
        )
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/home/overview")).json()
        action = body["today_action"]
        assert action is not None
        assert action["kind"] == "review_cards"
        assert action["count"] == 2


@pytest.mark.anyio
async def test_today_action_falls_back_to_continue_reading(test_db):
    """No due cards, no notes -- most-recent doc with incomplete reading wins."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id, "Algebra"))
        await s.commit()
        # Insert a section so the "progress < total" branch can be evaluated.
        await s.execute(
            text(
                "INSERT INTO sections (id, document_id, heading, level, section_order, "
                "page_start, page_end, preview, parent_section_id) "
                "VALUES (:id, :doc, 'Intro', 1, 0, 0, 1, 'text', NULL)"
            ),
            {"id": str(uuid.uuid4()), "doc": doc_id},
        )
        await s.commit()
        await ActivityService(s).record_doc_read(doc_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/home/overview")).json()
        action = body["today_action"]
        assert action is not None
        assert action["kind"] == "continue_reading"
        assert action["target_id"] == doc_id


@pytest.mark.anyio
async def test_active_collections_include_member_counts(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col = (await c.post("/collections", json={"name": "Reading list"})).json()
        col_id = col["id"]
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [doc_id], "member_type": "document"},
        )
        nr = await c.post("/notes", json={"content": "note", "tags": [], "document_id": None})
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [nr.json()["id"]], "member_type": "note"},
        )

        body = (await c.get("/home/overview")).json()
        active = body["active_collections"]
        ours = next(x for x in active if x["id"] == col_id)
        assert ours["document_count"] == 1
        assert ours["note_count"] == 1
        assert ours["flashcard_count"] == 0


@pytest.mark.anyio
async def test_recent_tags_carries_split_counts(test_db):
    """Hub chips show doc/note split per the plan."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["algebra"]})
        await c.post("/notes", json={"content": "n", "tags": ["algebra"], "document_id": None})

        body = (await c.get("/home/overview")).json()
        algebra = next(t for t in body["recent_tags"] if t["id"] == "algebra")
        assert algebra["document_count"] == 1
        assert algebra["note_count"] == 1


# -- Coach-shape additions ---------------------------------------------------


async def _set_activity_age(factory, member_type: str, member_id: str, days_ago: int) -> None:
    """Bump activity, then rewind the stored timestamp so we can simulate a
    doc/note last touched N days ago without waiting wall-clock time."""
    past = datetime.now(UTC) - timedelta(days=days_ago)
    async with factory() as s:
        if member_type == "document":
            await ActivityService(s).record_doc_read(member_id)
        else:
            await ActivityService(s).record_note_edit(member_id)
        await s.execute(
            text(
                "UPDATE content_activity SET last_meaningful_at = :p "
                "WHERE member_type = :t AND member_id = :i"
            ),
            {"p": past, "t": member_type, "i": member_id},
        )
        await s.commit()


@pytest.mark.anyio
async def test_continue_reading_skips_unfinished_and_unstarted(test_db):
    """Three docs:
      - started + not finished -> appears
      - started + finished       -> filtered
      - never started (0% read)  -> filtered (need read_count > 0)."""
    _, factory = test_db
    started_id, done_id, untouched_id = (str(uuid.uuid4()) for _ in range(3))
    async with factory() as s:
        for did in (started_id, done_id, untouched_id):
            s.add(_doc(did, title=did[:6]))
            for n in range(3):
                await s.execute(
                    text(
                        "INSERT INTO sections (id, document_id, heading, level, "
                        "section_order, page_start, page_end, preview) "
                        "VALUES (:id, :doc, 'h', 1, :n, 0, 1, '')"
                    ),
                    {"id": str(uuid.uuid4()), "doc": did, "n": n},
                )
        # started_id: 1 of 3 sections read
        await s.execute(
            text(
                "INSERT INTO reading_progress (id, document_id, section_id, "
                "first_seen_at, last_seen_at, view_count) "
                "VALUES (:id, :doc, :sec, datetime('now'), datetime('now'), 1)"
            ),
            {"id": str(uuid.uuid4()), "doc": started_id, "sec": str(uuid.uuid4())},
        )
        # done_id: 3 of 3 sections read
        for _ in range(3):
            await s.execute(
                text(
                    "INSERT INTO reading_progress (id, document_id, section_id, "
                    "first_seen_at, last_seen_at, view_count) "
                    "VALUES (:id, :doc, :sec, datetime('now'), datetime('now'), 1)"
                ),
                {"id": str(uuid.uuid4()), "doc": done_id, "sec": str(uuid.uuid4())},
            )
        await s.commit()
        await ActivityService(s).record_doc_read(started_id)
        await ActivityService(s).record_doc_read(done_id)
        await ActivityService(s).record_doc_read(untouched_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/home/overview")).json()
        ids = {item["document_id"] for item in body["continue_reading"]}
        assert started_id in ids
        assert done_id not in ids
        assert untouched_id not in ids
        started = next(i for i in body["continue_reading"] if i["document_id"] == started_id)
        assert 0 < started["reading_progress_pct"] < 1


@pytest.mark.anyio
async def test_fading_window_only_touches_old_enough(test_db):
    """3 days ago = inside fresh window (skip). 12 days = fading (keep).
    25 days = beyond max window (skip, user has moved on)."""
    _, factory = test_db
    fresh, fading, stale = (str(uuid.uuid4()) for _ in range(3))
    async with factory() as s:
        for did, title in [(fresh, "fresh"), (fading, "fading"), (stale, "stale")]:
            s.add(_doc(did, title=title))
        await s.commit()
    await _set_activity_age(factory, "document", fresh, 3)
    await _set_activity_age(factory, "document", fading, 12)
    await _set_activity_age(factory, "document", stale, 25)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/home/overview")).json()
        ids = {f["member_id"] for f in body["fading_items"]}
        assert fading in ids
        assert fresh not in ids
        assert stale not in ids
        fading_row = next(f for f in body["fading_items"] if f["member_id"] == fading)
        assert fading_row["days_since"] >= 7


@pytest.mark.anyio
async def test_weekly_stats_count_recent_activity(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/notes", json={"content": "n1", "tags": [], "document_id": None})
        await c.post("/notes", json={"content": "n2", "tags": [], "document_id": None})
        async with factory() as s:
            await ActivityService(s).record_doc_read(doc_id)

        body = (await c.get("/home/overview")).json()
        stats = body["weekly_stats"]
        assert stats is not None
        assert stats["notes_written"] >= 2
        assert stats["docs_touched"] >= 1
        # Cards and minutes should be zero in a fresh DB.
        assert stats["cards_reviewed"] == 0
        assert stats["minutes_studied"] == 0
