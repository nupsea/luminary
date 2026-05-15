"""Chat session persistence service.

CRUD over ChatSessionModel + ChatMessageModel, plus LLM-backed title inference.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessageModel, ChatSessionModel
from app.services.llm import get_llm_service

logger = logging.getLogger(__name__)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _new_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


async def create_session(
    db: AsyncSession,
    *,
    scope: str = "all",
    document_ids: list[str] | None = None,
    model: str | None = None,
    title: str = "New chat",
) -> ChatSessionModel:
    now = datetime.now(UTC)
    row = ChatSessionModel(
        id=_new_id(),
        title=title,
        scope=scope,
        document_ids=document_ids or [],
        model=model,
        title_auto=True,
        created_at=now,
        updated_at=now,
        last_message_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_sessions(
    db: AsyncSession,
    *,
    q: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return sessions ordered by last_message_at desc.

    When q is supplied, results are filtered by FTS5 match across titles+message bodies.
    Each item carries a `preview` field with the most recent message snippet.
    """
    if q and q.strip():
        # SQLite restricts FTS MATCH to direct queries against the virtual table,
        # so we resolve matching session_ids in a subquery, then OR with title LIKE.
        sql = text(
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
        )
        rows = (
            await db.execute(sql, {"q": q.strip(), "like": f"%{q.strip()}%", "lim": limit})
        ).fetchall()
        ids = [r[0] for r in rows]
        if not ids:
            return []
        sess_rows = (
            await db.execute(select(ChatSessionModel).where(ChatSessionModel.id.in_(ids)))
        ).scalars().all()
        # preserve FTS ordering
        order = {sid: i for i, sid in enumerate(ids)}
        sessions = sorted(sess_rows, key=lambda s: order.get(s.id, 999))
    else:
        sessions = (
            await db.execute(
                select(ChatSessionModel)
                .order_by(ChatSessionModel.last_message_at.desc())
                .limit(limit)
            )
        ).scalars().all()

    out: list[dict] = []
    for s in sessions:
        last = (
            await db.execute(
                select(ChatMessageModel)
                .where(ChatMessageModel.session_id == s.id)
                .order_by(ChatMessageModel.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        preview = (last.content[:140] if last else "")
        out.append(
            {
                "id": s.id,
                "title": s.title,
                "scope": s.scope,
                "document_ids": s.document_ids or [],
                "model": s.model,
                "title_auto": s.title_auto,
                "created_at": _ensure_utc(s.created_at),
                "updated_at": _ensure_utc(s.updated_at),
                "last_message_at": _ensure_utc(s.last_message_at),
                "preview": preview,
            }
        )
    return out


async def get_session(db: AsyncSession, session_id: str) -> ChatSessionModel | None:
    return (
        await db.execute(
            select(ChatSessionModel).where(ChatSessionModel.id == session_id)
        )
    ).scalar_one_or_none()


async def get_messages(db: AsyncSession, session_id: str) -> list[ChatMessageModel]:
    return (
        await db.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at.asc())
        )
    ).scalars().all()


async def rename_session(
    db: AsyncSession,
    session_id: str,
    *,
    title: str,
    auto: bool = False,
) -> ChatSessionModel | None:
    sess = await get_session(db, session_id)
    if sess is None:
        return None
    sess.title = title.strip()[:120] or "New chat"
    sess.title_auto = auto
    sess.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(sess)
    # keep FTS title column in sync
    await db.execute(
        text(
            "UPDATE chat_messages_fts SET title = :t WHERE session_id = :sid"
        ),
        {"t": sess.title, "sid": sess.id},
    )
    await db.commit()
    return sess


async def delete_session(db: AsyncSession, session_id: str) -> bool:
    sess = await get_session(db, session_id)
    if sess is None:
        return False
    # Service-level cascade -- SQLite FKs may not enforce ON DELETE
    await db.execute(
        delete(ChatMessageModel).where(ChatMessageModel.session_id == session_id)
    )
    await db.execute(
        text("DELETE FROM chat_messages_fts WHERE session_id = :sid"),
        {"sid": session_id},
    )
    await db.execute(
        delete(ChatSessionModel).where(ChatSessionModel.id == session_id)
    )
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


async def append_message(
    db: AsyncSession,
    session_id: str,
    *,
    role: str,
    content: str,
    extra: dict | None = None,
) -> ChatMessageModel | None:
    sess = await get_session(db, session_id)
    if sess is None:
        return None
    now = datetime.now(UTC)
    msg = ChatMessageModel(
        id=_new_id(),
        session_id=session_id,
        role=role,
        content=content,
        extra=extra,
        created_at=now,
    )
    db.add(msg)
    sess.last_message_at = now
    sess.updated_at = now
    await db.commit()
    await db.refresh(msg)
    # mirror into FTS shadow
    await db.execute(
        text(
            "INSERT INTO chat_messages_fts (content, title, message_id, session_id) "
            "VALUES (:c, :t, :mid, :sid)"
        ),
        {"c": content, "t": sess.title, "mid": msg.id, "sid": session_id},
    )
    await db.commit()
    return msg


# ---------------------------------------------------------------------------
# Title inference
# ---------------------------------------------------------------------------


_TITLE_SYSTEM = (
    "You generate concise chat titles. Reply with a 3 to 6 word title only. "
    "No quotes, no punctuation at the end, no preamble."
)


def _fallback_title(first_message: str) -> str:
    text_only = " ".join(first_message.split())
    return (text_only[:48] + "...") if len(text_only) > 48 else (text_only or "New chat")


async def infer_title(first_user_message: str, *, model: str | None = None) -> str:
    """Generate a short chat title via the local LLM. Falls back to truncated text."""
    snippet = first_user_message.strip()[:600]
    if not snippet:
        return "New chat"
    try:
        svc = get_llm_service()
        result = await svc.generate(
            prompt=f"Conversation opener:\n{snippet}\n\nTitle:",
            system=_TITLE_SYSTEM,
            model=model,
            timeout=20.0,
            background=True,
        )
        title = (result or "").strip().strip('"').strip("'").splitlines()[0]
        title = title.rstrip(".!?:;")
        if not title:
            return _fallback_title(snippet)
        return title[:80]
    except Exception:
        logger.debug("Title inference failed; using fallback", exc_info=True)
        return _fallback_title(snippet)
