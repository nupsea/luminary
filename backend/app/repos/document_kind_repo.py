"""Reads by document kind (#223): the label, filters and counts all compile one rule table."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentModel
from app.types import DEFAULT_KIND, KIND_RULES


def kind_expr() -> ColumnElement[str]:
    """`types.document_kind` as a SQL expression, so a kind filters and counts in the query."""
    return case(
        *[(getattr(DocumentModel, col).in_(values), kind) for col, values, kind in KIND_RULES],
        else_=DEFAULT_KIND,
    )


class DocumentKindRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def kind_counts(self) -> dict[str, int]:
        kind = kind_expr()
        rows = await self.session.execute(select(kind, func.count(DocumentModel.id)).group_by(kind))
        return {row[0]: row[1] for row in rows.all()}

    async def ids_of_kinds(self, kinds: Sequence[str]) -> list[str]:
        result = await self.session.execute(select(DocumentModel.id).where(kind_expr().in_(kinds)))
        return list(result.scalars())

    async def titles_and_kinds(self, document_ids: Sequence[str]) -> dict[str, tuple[str, str]]:
        """{id: (title, kind)} for search results."""
        result = await self.session.execute(
            select(DocumentModel.id, DocumentModel.title, kind_expr()).where(
                DocumentModel.id.in_(document_ids)
            )
        )
        return {i: (t or "Untitled", kind) for i, t, kind in result.all()}
