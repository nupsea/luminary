"""Chat session persistence service.

CRUD over ChatSessionModel + ChatMessageModel, plus LLM-backed title inference.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessageModel, ChatSessionModel
from app.repos.chat_repo import ChatRepo
from app.services.llm import get_llm_service
from app.types import as_utc

logger = logging.getLogger(__name__)


def _new_id() -> str:
    return uuid.uuid4().hex


# Sessions


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
    repo = ChatRepo(db)
    if q and q.strip():
        sessions = await repo.matching(q.strip(), limit)
    else:
        sessions = await repo.recent(limit)
    latest = await repo.latest_messages([s.id for s in sessions])

    out: list[dict] = []
    for s in sessions:
        last = latest.get(s.id)
        preview = last.content[:140] if last else ""
        out.append(
            {
                "id": s.id,
                "title": s.title,
                "scope": s.scope,
                "document_ids": s.document_ids or [],
                "model": s.model,
                "title_auto": s.title_auto,
                "created_at": as_utc(s.created_at),
                "updated_at": as_utc(s.updated_at),
                "last_message_at": as_utc(s.last_message_at),
                "preview": preview,
            }
        )
    return out


async def get_session(db: AsyncSession, session_id: str) -> ChatSessionModel | None:
    return await ChatRepo(db).find(session_id)


async def get_messages(db: AsyncSession, session_id: str) -> list[ChatMessageModel]:
    return await ChatRepo(db).messages(session_id)


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
    await ChatRepo(db).retitle_index(sess.id, sess.title)
    await db.commit()
    return sess


async def update_session_model(
    db: AsyncSession,
    session_id: str,
    *,
    model: str | None,
) -> ChatSessionModel | None:
    sess = await get_session(db, session_id)
    if sess is None:
        return None
    sess.model = model
    sess.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(sess)
    return sess


async def delete_session(db: AsyncSession, session_id: str) -> bool:
    sess = await get_session(db, session_id)
    if sess is None:
        return False
    await ChatRepo(db).delete(session_id)
    await db.commit()
    return True


# Messages


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
    await ChatRepo(db).index_message(msg, sess.title)
    await db.commit()
    return msg


# Title inference


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
