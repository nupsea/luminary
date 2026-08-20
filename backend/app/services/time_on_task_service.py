"""Accrual of foreground time from client heartbeats.

**What a heartbeat proves is narrow.** It says the surface was mounted and the
tab was visible when the sample fired. It is not proof that anyone was reading,
and nothing built on this may call it "time studied" without saying so — the
Progress surface reports it as time with the page open, per `docs/metrics.md`.

The server cannot measure this on its own. It sees requests, and a reader who
opens a document and reads for twenty minutes issues one. So the client samples,
and the accrual rule here decides what those samples are worth.

Time is credited *between* consecutive beats, never for a beat itself. A gap
larger than `MAX_CREDITED_GAP_SECONDS` is not credited at all: the surface was
hidden, the machine was asleep, or the user left, and crediting it would invent
attention that the product would then report as measured.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TimeOnTaskModel

# What the client aims for between samples. The server does not depend on it
# holding -- the credited amount is always the measured gap -- but the ceiling
# below is derived from it.
HEARTBEAT_SECONDS = 15

# The largest gap still treated as one continuous stretch. Bracketing cases: a
# 20s gap is one slow round trip on a busy machine and is real time on task, so
# the ceiling must sit above it; a 60s gap means the tab was hidden or the user
# walked away, and crediting it would report attention nobody paid.
MAX_CREDITED_GAP_SECONDS = 45

# The activities the pie on the hub splits a week into.
ACTIVITIES = ("document", "note", "review", "study")


class TimeOnTaskService:
    """Sole writer of `time_on_task`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def beat(self, activity: str, member_id: str | None = None) -> int:
        """Record a heartbeat. Returns the seconds credited by *this* beat.

        Zero is the honest answer twice over: for the first beat of a stretch,
        which has nothing to measure from, and for a beat arriving after a gap
        too long to be continuous.
        """
        if activity not in ACTIVITIES:
            raise ValueError(f"unknown activity {activity!r}")

        now = datetime.now(UTC)
        row = (
            await self._session.execute(
                select(TimeOnTaskModel)
                .where(
                    TimeOnTaskModel.activity == activity,
                    TimeOnTaskModel.member_id.is_(None)
                    if member_id is None
                    else TimeOnTaskModel.member_id == member_id,
                )
                .order_by(TimeOnTaskModel.last_beat_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        credited = 0
        if row is not None:
            last = row.last_beat_at
            # Rows are written as UTC; a naive value read back is still UTC.
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            gap = (now - last).total_seconds()
            if 0 <= gap <= MAX_CREDITED_GAP_SECONDS:
                credited = round(gap)
                row.seconds += credited
                row.last_beat_at = now
                await self._session.commit()
                return credited

        self._session.add(
            TimeOnTaskModel(
                id=str(uuid.uuid4()),
                activity=activity,
                member_id=member_id,
                started_at=now,
                last_beat_at=now,
                seconds=0,
            )
        )
        await self._session.commit()
        return credited

    async def seconds_by_activity(self, days: int = 7) -> dict[str, int]:
        """Seconds per activity over the trailing window, zero-filled.

        Every activity appears even at zero: a slice missing from the hub's week
        is indistinguishable from one the user genuinely spent no time on, and
        the reader cannot tell "nothing recorded" from "not measured".

        Intervals are attributed to the day they began, which is the same
        approximation EngagementService makes at a local midnight.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        rows = (
            await self._session.execute(
                select(TimeOnTaskModel.activity, TimeOnTaskModel.seconds).where(
                    TimeOnTaskModel.started_at >= cutoff
                )
            )
        ).all()

        totals = dict.fromkeys(ACTIVITIES, 0)
        for activity, seconds in rows:
            if activity in totals:
                totals[activity] += int(seconds or 0)
        return totals
