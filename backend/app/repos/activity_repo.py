"""When each document or note last saw meaningful activity."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ActivityRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def last_meaningful_at(self, member_type: str, member_id: str) -> datetime | None:
        row = (
            await self.session.execute(
                text(
                    "SELECT last_meaningful_at FROM content_activity "
                    "WHERE member_type = :t AND member_id = :i"
                ),
                {"t": member_type, "i": member_id},
            )
        ).first()
        if row is None:
            return None
        # A text() SELECT hands TIMESTAMP back as an ISO string under aiosqlite.
        last = datetime.fromisoformat(row[0]) if isinstance(row[0], str) else row[0]
        return last if last.tzinfo else last.replace(tzinfo=UTC)

    async def touch(self, member_type: str, member_id: str, at: datetime) -> None:
        """Uncommitted."""
        await self.session.execute(
            text(
                "INSERT INTO content_activity (member_type, member_id, last_meaningful_at) "
                "VALUES (:t, :i, :now) "
                "ON CONFLICT(member_type, member_id) DO UPDATE SET "
                "last_meaningful_at = excluded.last_meaningful_at"
            ),
            {"t": member_type, "i": member_id, "now": at},
        )
