"""Generic repository helpers.

`get_or_404` keeps its name -- the established idiom across ~90 call sites --
but raises `NotFound`, which main.py maps to a 404 response.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFound


async def get_or_404[T](
    session: AsyncSession,
    model: type[T],
    pk: object,
    *,
    name: str | None = None,
    pk_attr: str = "id",
) -> T:
    """Fetch a single row by primary key or raise `NotFound`.

    `name` is interpolated into the detail (defaults to the model's class
    name). `pk_attr` overrides the primary-key column for the rare model
    that does not use `id`.
    """
    column = getattr(model, pk_attr)
    result = await session.execute(select(model).where(column == pk))
    obj = result.scalar_one_or_none()
    if obj is None:
        label = name or model.__name__
        raise NotFound(f"{label} not found")
    return obj


def require_or_404[T](obj: T | None, name: str) -> T:
    """Raise `NotFound` if `obj` is None, else return it.

    For call sites that already have the row in hand (e.g. fetched as
    part of a join) but still need the not-found guard.
    """
    if obj is None:
        raise NotFound(f"{name} not found")
    return obj
