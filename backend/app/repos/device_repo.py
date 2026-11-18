"""Repository for `DeviceModel` (paired devices)."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.library import DEFAULT_LIBRARY, use_library
from app.models import DeviceModel
from app.repos._helpers import get_or_404


class DeviceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, name: str, token_hash: str, library: str) -> DeviceModel:
        device = DeviceModel(
            id=str(uuid.uuid4()),
            name=name,
            token_hash=token_hash,
            library=library,
            created_at=datetime.now(UTC),
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

    async def count_in(self, library: str) -> int:
        """Devices still paired into *library*."""
        result = await self.session.execute(
            select(func.count())
            .select_from(DeviceModel)
            .where(DeviceModel.library == library, DeviceModel.revoked_at.is_(None))
        )
        return int(result.scalar_one())

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


@contextlib.asynccontextmanager
async def device_registry() -> AsyncIterator[DeviceRepo]:
    # The registry is the machine's, in the default library whichever library the app has open.
    with use_library(DEFAULT_LIBRARY):
        factory = get_session_factory()
    async with factory() as session:
        yield DeviceRepo(session)


async def get_device_repo() -> AsyncIterator[DeviceRepo]:
    async with device_registry() as repo:
        yield repo
