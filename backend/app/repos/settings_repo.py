"""Repository for `SettingsModel` rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SettingsModel
from app.repos._helpers import upsert_insert


class SettingsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_flag(self, key: str) -> bool | None:
        """The stored flag, or None when unset or not a boolean."""
        row = (
            await self.session.execute(select(SettingsModel).where(SettingsModel.key == key))
        ).scalar_one_or_none()
        return row.value if row is not None and isinstance(row.value, bool) else None

    async def set_flag(self, key: str, value: bool) -> None:
        await self.put(key, bool(value))
        await self.session.commit()

    async def put(self, key: str, value: Any) -> None:
        """Write one setting. Not `session.merge`: that selects then inserts, so two
        writers of an absent key both insert and one fails on the primary key (#251)."""
        stmt = upsert_insert(self.session, SettingsModel).values(key=key, value=value)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[SettingsModel.key], set_={"value": stmt.excluded.value}
            )
        )
