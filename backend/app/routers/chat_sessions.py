"""REST endpoints for persisted chat sessions.

Routes:
    POST   /chat/sessions               -- create a new session
    GET    /chat/sessions                -- list sessions, optional ?q= search
    GET    /chat/sessions/{id}           -- session metadata + full message history
    PATCH  /chat/sessions/{id}           -- rename session (or trigger LLM auto-title)
    DELETE /chat/sessions/{id}           -- hard-delete session and its messages
    POST   /chat/sessions/{id}/messages  -- append a single message turn
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import chat_sessions as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat/sessions", tags=["chat-sessions"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SessionCreateRequest(BaseModel):
    scope: Literal["single", "all"] = "all"
    document_ids: list[str] = []
    model: str | None = None
    title: str | None = None  # optional explicit title; otherwise "New chat"


class SessionRenameRequest(BaseModel):
    title: str | None = None  # explicit user title
    auto_from_message: str | None = None  # if set, infer title via LLM from this text


class MessageAppendRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    extra: dict | None = None


class SessionListItem(BaseModel):
    id: str
    title: str
    scope: str
    document_ids: list[str]
    model: str | None
    title_auto: bool
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime
    preview: str


class MessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    extra: dict | None
    created_at: datetime


class SessionDetail(BaseModel):
    id: str
    title: str
    scope: str
    document_ids: list[str]
    model: str | None
    title_auto: bool
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime
    messages: list[MessageOut]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=SessionListItem)
async def create_session(
    req: SessionCreateRequest, db: AsyncSession = Depends(get_db)
) -> SessionListItem:
    sess = await svc.create_session(
        db,
        scope=req.scope,
        document_ids=req.document_ids,
        model=req.model,
        title=(req.title or "New chat"),
    )
    return SessionListItem(
        id=sess.id,
        title=sess.title,
        scope=sess.scope,
        document_ids=sess.document_ids or [],
        model=sess.model,
        title_auto=sess.title_auto,
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        last_message_at=sess.last_message_at,
        preview="",
    )


@router.get("", response_model=list[SessionListItem])
async def list_sessions(
    q: str | None = Query(default=None, description="FTS query over titles + message bodies"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[SessionListItem]:
    rows = await svc.list_sessions(db, q=q, limit=limit)
    return [SessionListItem(**r) for r in rows]


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str, db: AsyncSession = Depends(get_db)
) -> SessionDetail:
    sess = await svc.get_session(db, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")
    msgs = await svc.get_messages(db, session_id)
    return SessionDetail(
        id=sess.id,
        title=sess.title,
        scope=sess.scope,
        document_ids=sess.document_ids or [],
        model=sess.model,
        title_auto=sess.title_auto,
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        last_message_at=sess.last_message_at,
        messages=[
            MessageOut(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                extra=m.extra,
                created_at=m.created_at,
            )
            for m in msgs
        ],
    )


@router.patch("/{session_id}", response_model=SessionListItem)
async def rename_session(
    session_id: str,
    req: SessionRenameRequest,
    db: AsyncSession = Depends(get_db),
) -> SessionListItem:
    if req.auto_from_message is not None:
        new_title = await svc.infer_title(req.auto_from_message)
        sess = await svc.rename_session(db, session_id, title=new_title, auto=True)
    elif req.title is not None:
        sess = await svc.rename_session(db, session_id, title=req.title, auto=False)
    else:
        raise HTTPException(status_code=400, detail="Provide either title or auto_from_message")
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionListItem(
        id=sess.id,
        title=sess.title,
        scope=sess.scope,
        document_ids=sess.document_ids or [],
        model=sess.model,
        title_auto=sess.title_auto,
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        last_message_at=sess.last_message_at,
        preview="",
    )


@router.delete("/{session_id}")
async def delete_session(
    session_id: str, db: AsyncSession = Depends(get_db)
) -> dict[str, bool]:
    ok = await svc.delete_session(db, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


@router.post("/{session_id}/messages", response_model=MessageOut)
async def append_message(
    session_id: str,
    req: MessageAppendRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    msg = await svc.append_message(
        db, session_id, role=req.role, content=req.content, extra=req.extra
    )
    if msg is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return MessageOut(
        id=msg.id,
        session_id=msg.session_id,
        role=msg.role,
        content=msg.content,
        extra=msg.extra,
        created_at=msg.created_at,
    )
