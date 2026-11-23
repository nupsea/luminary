"""Reads of the change feed (#450); its rows are written by triggers, never from here."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChangeFeedStateModel, ChangeLogModel


class ChangeLogRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def state(self) -> ChangeFeedStateModel:
        """The one state row; a database built from the models rather than the migration gets
        it on first read."""
        row = await self.session.get(ChangeFeedStateModel, 1)
        if row is None:
            await self.session.execute(
                insert(ChangeFeedStateModel)
                .values(id=1, epoch=str(uuid.uuid4()), horizon_seq=0)
                .on_conflict_do_nothing()
            )
            await self.session.commit()
            row = await self.session.get(ChangeFeedStateModel, 1)
        return row  # type: ignore[return-value]  -- inserted just above

    async def renew_epoch(self) -> str:
        await self.state()
        epoch = str(uuid.uuid4())
        await self.session.execute(
            update(ChangeFeedStateModel).where(ChangeFeedStateModel.id == 1).values(epoch=epoch)
        )
        await self.session.commit()
        return epoch

    async def high_water(self) -> int:
        """The largest `seq` ever issued. AUTOINCREMENT never reuses one, though the row that
        held it may since have been replaced."""
        result = await self.session.execute(
            text("SELECT seq FROM sqlite_sequence WHERE name = 'change_log'")
        )
        return result.scalar() or 0

    async def after(self, seq: int, limit: int) -> Sequence[ChangeLogModel]:
        result = await self.session.execute(
            select(ChangeLogModel)
            .where(ChangeLogModel.seq > seq)
            .order_by(ChangeLogModel.seq)
            .limit(limit)
        )
        return result.scalars().all()

    async def prune_tombstones(self, older_than: datetime) -> int:
        """Drop deletions recorded before *older_than*, and raise the horizon past them: a
        cursor below it may have missed a deletion, so it resyncs."""
        newest = (
            await self.session.execute(
                select(func.max(ChangeLogModel.seq)).where(
                    ChangeLogModel.op == "delete", ChangeLogModel.at < older_than
                )
            )
        ).scalar()
        if newest is None:
            return 0
        state = await self.state()
        result = await self.session.execute(
            delete(ChangeLogModel).where(
                ChangeLogModel.op == "delete", ChangeLogModel.seq <= newest
            )
        )
        await self.session.execute(
            update(ChangeFeedStateModel)
            .where(ChangeFeedStateModel.id == 1)
            .values(horizon_seq=max(state.horizon_seq, newest))
        )
        await self.session.commit()
        return result.rowcount
