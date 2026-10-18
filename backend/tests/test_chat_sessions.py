"""Chat session persistence: the list's previews, search, rename and delete."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from app.models import ChatMessageModel
from app.services import chat_sessions as svc


async def _session_with(db, title: str, *messages: str):
    sess = await svc.create_session(db, title=title)
    for content in messages:
        await svc.append_message(db, sess.id, role="user", content=content)
    return sess


async def test_each_listed_session_previews_its_own_newest_message(memory_db):
    async with memory_db.factory() as db:
        a = await _session_with(db, "a", "first in a", "newest in a")
        b = await _session_with(db, "b", "only in b")
        empty = await svc.create_session(db, title="empty")
        # Same-second inserts would tie on created_at; spread them so "newest" is defined.
        rows = (await db.execute(select(ChatMessageModel))).scalars().all()
        base = datetime(2026, 1, 1, tzinfo=UTC)
        for i, m in enumerate(sorted(rows, key=lambda m: m.content.startswith("newest"))):
            m.created_at = base + timedelta(minutes=i)
        await db.commit()

        listed = {s["id"]: s["preview"] for s in await svc.list_sessions(db)}

    assert listed == {a.id: "newest in a", b.id: "only in b", empty.id: ""}


async def test_search_finds_a_session_by_message_text_or_title(memory_db):
    async with memory_db.factory() as db:
        by_body = await _session_with(db, "untitled", "photosynthesis converts light")
        by_title = await _session_with(db, "Photosynthesis notes", "unrelated words")
        await _session_with(db, "other", "nothing relevant")

        found = {s["id"] for s in await svc.list_sessions(db, q="photosynthesis")}

    assert found == {by_body.id, by_title.id}


async def test_rename_retitles_the_index_and_delete_removes_everything(memory_db):
    async with memory_db.factory() as db:
        sess = await _session_with(db, "old", "hello there")
        await svc.rename_session(db, sess.id, title="New title")
        titles = (
            (
                await db.execute(
                    text("SELECT title FROM chat_messages_fts WHERE session_id = :s"),
                    {"s": sess.id},
                )
            )
            .scalars()
            .all()
        )
        assert titles == ["New title"]

        assert await svc.delete_session(db, sess.id) is True
        left = (
            await db.execute(
                select(func.count())
                .select_from(ChatMessageModel)
                .where(ChatMessageModel.session_id == sess.id)
            )
        ).scalar_one()
        indexed = (
            await db.execute(
                text("SELECT count(*) FROM chat_messages_fts WHERE session_id = :s"),
                {"s": sess.id},
            )
        ).scalar_one()
        assert (left, indexed, await svc.get_session(db, sess.id)) == (0, 0, None)
