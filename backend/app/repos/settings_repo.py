"""Repository for `SettingsModel` rows that hold one flag each."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SettingsModel


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
        await self.session.merge(SettingsModel(key=key, value=bool(value)))
        await self.session.commit()
