"""Statements on `idempotency_keys` (#451)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdempotencyKeyModel


class IdempotencyRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve(
        self, principal: str, key: str, request_hash: str
    ) -> IdempotencyKeyModel | None:
        """Claim *key* for this request. None when claimed now; else the row that holds it."""
        result = await self.session.execute(
            insert(IdempotencyKeyModel)
            .values(
                principal=principal,
                key=key,
                request_hash=request_hash,
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing()
        )
        await self.session.commit()
        if result.rowcount == 1:
            return None
        return await self.session.scalar(
            select(IdempotencyKeyModel).where(
                IdempotencyKeyModel.principal == principal, IdempotencyKeyModel.key == key
            )
        )

    async def complete(self, principal: str, key: str, status_code: int, body: str) -> None:
        await self.session.execute(
            update(IdempotencyKeyModel)
            .where(IdempotencyKeyModel.principal == principal, IdempotencyKeyModel.key == key)
            .values(status_code=status_code, body=body)
        )
        await self.session.commit()

    async def release(self, principal: str, key: str) -> None:
        await self.session.execute(
            delete(IdempotencyKeyModel).where(
                IdempotencyKeyModel.principal == principal, IdempotencyKeyModel.key == key
            )
        )
        await self.session.commit()

    async def prune(self, older_than: datetime) -> int:
        result = await self.session.execute(
            delete(IdempotencyKeyModel).where(IdempotencyKeyModel.created_at < older_than)
        )
        await self.session.commit()
        return result.rowcount
