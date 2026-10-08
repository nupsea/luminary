"""Repository for `DeviceModel` (paired devices)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DeviceModel
from app.repos._helpers import get_or_404


class DeviceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, name: str, token_hash: str) -> DeviceModel:
        device = DeviceModel(
            id=str(uuid.uuid4()), name=name, token_hash=token_hash, created_at=datetime.now(UTC)
        )
        self.session.add(device)
        await self.session.commit()
        await self.session.refresh(device)
        return device

    async def list(self) -> Sequence[DeviceModel]:
        result = await self.session.execute(
            select(DeviceModel).order_by(DeviceModel.created_at.desc())
        )
        return result.scalars().all()

    async def by_token_hash(self, token_hash: str) -> DeviceModel | None:
        result = await self.session.execute(
            select(DeviceModel).where(DeviceModel.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def touch(self, device: DeviceModel, at: datetime) -> None:
        device.last_seen_at = at
        await self.session.commit()

    async def revoke(self, device_id: str) -> DeviceModel:
        device = await get_or_404(self.session, DeviceModel, device_id, name="Device")
        if device.revoked_at is None:
            device.revoked_at = datetime.now(UTC)
            await self.session.commit()
            await self.session.refresh(device)
        return device


def get_device_repo(session: AsyncSession = Depends(get_db)) -> DeviceRepo:
    return DeviceRepo(session)
