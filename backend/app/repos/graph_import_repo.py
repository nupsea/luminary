"""Reads and writes for the one-time Kuzu-to-SQLite graph import (`services/graph_import.py`)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GraphImportStateModel


class GraphImportRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def keys(self, *columns: Any) -> set:
        """Every value of one column, or every tuple of several."""
        result = await self.session.execute(select(*columns))
        if len(columns) == 1:
            return {row[0] for row in result}
        return {tuple(row) for row in result}

    async def count(self, model: type) -> int:
        return (await self.session.scalar(select(func.count()).select_from(model))) or 0

    async def insert_rows(self, model: type, rows: list[dict[str, Any]]) -> None:
        if rows:
            await self.session.execute(insert(model), rows)

    async def done_domains(self) -> set[str]:
        state = GraphImportStateModel
        result = await self.session.execute(select(state.domain).where(state.status == "done"))
        return {row[0] for row in result}

    async def record(
        self,
        domain: str,
        status: str,
        *,
        imported: dict | None = None,
        skipped: dict | None = None,
        error: str | None = None,
    ) -> None:
        row = await self.session.get(GraphImportStateModel, domain)
        if row is None:
            row = GraphImportStateModel(domain=domain, status=status)
            self.session.add(row)
        row.status = status
        row.attempted_at = datetime.now(UTC)
        row.imported_json = imported or {}
        row.skipped_json = skipped or {}
        row.error = error
