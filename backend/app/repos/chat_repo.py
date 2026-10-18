"""Chat sessions, their messages, and the chat_messages_fts index. Nothing here commits."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessageModel, ChatSessionModel


class ChatRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find(self, session_id: str) -> ChatSessionModel | None:
        return await self.session.get(ChatSessionModel, session_id)

    async def recent(self, limit: int) -> list[ChatSessionModel]:
        result = await self.session.execute(
            select(ChatSessionModel).order_by(ChatSessionModel.last_message_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def matching(self, q: str, limit: int) -> list[ChatSessionModel]:
        """Sessions whose messages match `q` in FTS or whose title contains it, newest first."""
        # SQLite allows MATCH only against the virtual table itself, hence the subquery.
        rows = await self.session.execute(
            text(
                """
                SELECT cs.id
                FROM chat_sessions cs
                WHERE cs.id IN (
                    SELECT session_id FROM chat_messages_fts
                    WHERE chat_messages_fts MATCH :q
                )
                   OR cs.title LIKE :like
                ORDER BY cs.last_message_at DESC
                LIMIT :lim
                """
            ),
            {"q": q, "like": f"%{q}%", "lim": limit},
        )
        ids = [r[0] for r in rows.fetchall()]
        if not ids:
            return []
        found = await self.session.execute(
            select(ChatSessionModel).where(ChatSessionModel.id.in_(ids))
        )
        order = {sid: i for i, sid in enumerate(ids)}
        return sorted(found.scalars().all(), key=lambda s: order[s.id])

    async def latest_messages(self, session_ids: Sequence[str]) -> dict[str, ChatMessageModel]:
        """{session id: its newest message} for the sessions that have one."""
        if not session_ids:
            return {}
        newest = (
            select(
                ChatMessageModel.session_id,
                func.max(ChatMessageModel.created_at).label("at"),
            )
            .where(ChatMessageModel.session_id.in_(list(session_ids)))
            .group_by(ChatMessageModel.session_id)
            .subquery()
        )
        result = await self.session.execute(
            select(ChatMessageModel).join(
                newest,
                and_(
                    ChatMessageModel.session_id == newest.c.session_id,
                    ChatMessageModel.created_at == newest.c.at,
                ),
            )
        )
        return {m.session_id: m for m in result.scalars().all()}

    async def messages(self, session_id: str) -> list[ChatMessageModel]:
        result = await self.session.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at.asc())
        )
        return list(result.scalars().all())

    async def index_message(self, message: ChatMessageModel, title: str) -> None:
        await self.session.execute(
            text(
                "INSERT INTO chat_messages_fts (content, title, message_id, session_id) "
                "VALUES (:c, :t, :mid, :sid)"
            ),
            {"c": message.content, "t": title, "mid": message.id, "sid": message.session_id},
        )

    async def retitle_index(self, session_id: str, title: str) -> None:
        await self.session.execute(
            text("UPDATE chat_messages_fts SET title = :t WHERE session_id = :sid"),
            {"t": title, "sid": session_id},
        )

    async def delete(self, session_id: str) -> None:
        """The session, its messages and their index rows; SQLite may not enforce the FK."""
        await self.session.execute(
            delete(ChatMessageModel).where(ChatMessageModel.session_id == session_id)
        )
        await self.session.execute(
            text("DELETE FROM chat_messages_fts WHERE session_id = :sid"), {"sid": session_id}
        )
        await self.session.execute(
            delete(ChatSessionModel).where(ChatSessionModel.id == session_id)
        )
