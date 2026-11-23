"""What a client's cursor gets from the change feed (#450).

A cursor is `(epoch, seq)`. The log holds one row per live note or document plus deletions, so
`since=0` lists the whole library. A cursor the feed can no longer answer faithfully is told to
resync and answered from 0: another epoch (a restored library), a seq past a pruned deletion, or
a seq this database never issued.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.database import get_session_factory
from app.models import ChangeLogModel
from app.repos.change_log_repo import ChangeLogRepo

TOMBSTONE_RETENTION = timedelta(days=180)


@dataclass(frozen=True)
class ChangePage:
    epoch: str
    changes: list[ChangeLogModel]
    next: int
    more: bool
    resync: bool


async def read_changes(
    repo: ChangeLogRepo, epoch: str | None, since: int, limit: int
) -> ChangePage:
    state = await repo.state()
    resync = since > 0 and (
        epoch != state.epoch or since < state.horizon_seq or since > await repo.high_water()
    )
    start = 0 if resync else since
    rows = list(await repo.after(start, limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return ChangePage(
        epoch=state.epoch,
        changes=rows,
        next=rows[-1].seq if rows else start,
        more=more,
        resync=resync,
    )


async def renew_epoch() -> str:
    """For a library whose database was replaced: every client's cursor resyncs."""
    async with get_session_factory()() as session:
        return await ChangeLogRepo(session).renew_epoch()


async def prune_tombstones(now: datetime | None = None) -> int:
    async with get_session_factory()() as session:
        cutoff = (now or datetime.now(UTC)) - TOMBSTONE_RETENTION
        return await ChangeLogRepo(session).prune_tombstones(cutoff.replace(tzinfo=None))
