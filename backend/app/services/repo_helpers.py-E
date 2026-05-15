"""Generic repository helpers shared across routers.

`get_or_404(session, model, id, name)` collapses the recurring fetch +
`scalar_one_or_none()` + `if obj is None: raise HTTPException(404, ...)`
boilerplate (115+ sites pre-refactor) into a single call.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_or_404[T](
    session: AsyncSession,
    model: type[T],
    pk: object,
    *,
    name: str | None = None,
    pk_attr: str = "id",
) -> T:
    """Fetch a single row by primary key or raise HTTPException(404).

    `name` is interpolated into the detail (defaults to the model's class
    name). `pk_attr` overrides the primary-key column for the rare model
    that does not use `id`.
    """
    column = getattr(model, pk_attr)
    result = await session.execute(select(model).where(column == pk))
    obj = result.scalar_one_or_none()
    if obj is None:
        label = name or model.__name__
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return obj


def require_or_404[T](obj: T | None, name: str) -> T:
    """Raise HTTPException(404) if `obj` is None, else return it.

    For call sites that already have the row in hand (e.g. fetched as
    part of a join) but still need the not-found guard.
    """
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj
