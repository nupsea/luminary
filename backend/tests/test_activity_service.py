"""ActivityService bump rules and debouncing (plan 2E.8)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.services.activity_service import ActivityService


@pytest.fixture
async def factory():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    f = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = f
    yield f
    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    await engine.dispose()


async def _last_at(session, member_type: str, member_id: str):
    row = (
        await session.execute(
            text(
                "SELECT last_meaningful_at FROM content_activity "
                "WHERE member_type=:t AND member_id=:i"
            ),
            {"t": member_type, "i": member_id},
        )
    ).first()
    if row is None:
        return None
    val = row[0]
    if isinstance(val, str):
        return datetime.fromisoformat(val)
    return val


@pytest.mark.asyncio
async def test_first_call_writes_row(factory):
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        wrote = await ActivityService(s).record_doc_read(doc_id)
        assert wrote is True
        assert (await _last_at(s, "document", doc_id)) is not None


@pytest.mark.asyncio
async def test_doc_read_debounced_within_5s(factory):
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        assert await ActivityService(s).record_doc_read(doc_id) is True
        first = await _last_at(s, "document", doc_id)
        # Second call within the 5s window must not overwrite.
        assert await ActivityService(s).record_doc_read(doc_id) is False
        assert (await _last_at(s, "document", doc_id)) == first


@pytest.mark.asyncio
async def test_doc_read_bumps_after_window(factory):
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        await ActivityService(s).record_doc_read(doc_id)
        # Simulate elapsed time by rewinding the stored timestamp.
        past = datetime.now(UTC) - timedelta(seconds=10)
        await s.execute(
            text(
                "UPDATE content_activity SET last_meaningful_at = :p "
                "WHERE member_type='document' AND member_id=:i"
            ),
            {"p": past, "i": doc_id},
        )
        await s.commit()
        assert await ActivityService(s).record_doc_read(doc_id) is True
        new_last = await _last_at(s, "document", doc_id)
        # Normalize both sides to naive UTC for comparison (SQLite drops tz).
        new_naive = new_last.replace(tzinfo=None) if new_last.tzinfo else new_last
        assert new_naive > past.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_note_edit_uses_30s_debounce(factory):
    note_id = str(uuid.uuid4())
    async with factory() as s:
        await ActivityService(s).record_note_edit(note_id)
        # 10s back is still inside the 30s window; must not bump.
        ten_ago = datetime.now(UTC) - timedelta(seconds=10)
        await s.execute(
            text(
                "UPDATE content_activity SET last_meaningful_at = :p "
                "WHERE member_type='note' AND member_id=:i"
            ),
            {"p": ten_ago, "i": note_id},
        )
        await s.commit()
        assert await ActivityService(s).record_note_edit(note_id) is False


@pytest.mark.asyncio
async def test_flashcard_event_has_no_debounce(factory):
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        assert (
            await ActivityService(s).record_flashcard_event(
                document_id=doc_id, note_id=None
            )
            is True
        )
        first = await _last_at(s, "document", doc_id)
        await asyncio.sleep(0.01)
        assert (
            await ActivityService(s).record_flashcard_event(
                document_id=doc_id, note_id=None
            )
            is True
        )
        second = await _last_at(s, "document", doc_id)
        assert second >= first


@pytest.mark.asyncio
async def test_flashcard_event_prefers_document_when_both_set(factory):
    doc_id = str(uuid.uuid4())
    note_id = str(uuid.uuid4())
    async with factory() as s:
        await ActivityService(s).record_flashcard_event(
            document_id=doc_id, note_id=note_id
        )
        assert (await _last_at(s, "document", doc_id)) is not None
        assert (await _last_at(s, "note", note_id)) is None


@pytest.mark.asyncio
async def test_flashcard_event_returns_false_when_both_none(factory):
    async with factory() as s:
        assert (
            await ActivityService(s).record_flashcard_event(
                document_id=None, note_id=None
            )
            is False
        )
