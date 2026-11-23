"""The change feed a paired client syncs from (#450).

Routes: GET /changes

Always registered, like `devices`: it is how a client other than the app keeps its cache.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repos.change_log_repo import ChangeLogRepo
from app.runtime.request_auth import device_scope
from app.services.change_feed import read_changes

router = APIRouter(prefix="/changes", tags=["changes"])


class Change(BaseModel):
    seq: int
    entity: Literal["document", "note"]
    entity_id: str
    op: Literal["upsert", "delete"]
    at: datetime


class ChangesResponse(BaseModel):
    epoch: str
    changes: list[Change]
    next: int
    more: bool
    resync: bool


@router.get("", response_model=ChangesResponse, dependencies=[device_scope("read")])
async def list_changes(
    epoch: str | None = Query(None, max_length=36),
    since: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
) -> ChangesResponse:
    """Changes after `since` in this library, oldest first. With `resync`, the client drops
    its cache: the page restarts from 0 and lists every live note and document."""
    page = await read_changes(ChangeLogRepo(session), epoch, since, limit)
    return ChangesResponse(
        epoch=page.epoch,
        changes=[
            Change(seq=c.seq, entity=c.entity, entity_id=c.entity_id, op=c.op, at=c.at)
            for c in page.changes
        ],
        next=page.next,
        more=page.more,
        resync=page.resync,
    )
