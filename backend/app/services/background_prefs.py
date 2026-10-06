"""What the learner lets unattended work do: write chapters ahead, and at what pace.

Cached because admission reads the pace on every background call; loaded at start-up and
written through on every change.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.repos.settings_repo import SettingsRepo

_BACKFILL = "chapter_backfill"
_QUIET = "quiet_background"

_cache: dict[str, bool] = {}


def chapter_backfill() -> bool:
    """Whether chapters past the first ones are written in the background (#231)."""
    return _cache.get(_BACKFILL, get_settings().CHAPTER_CARDS_BACKFILL)


def quiet_background() -> bool:
    """Whether unattended model calls are paced (`llm_admission.background_duty`)."""
    return _cache.get(_QUIET, True)


async def load_background_prefs(session: AsyncSession) -> None:
    repo = SettingsRepo(session)
    for key in (_BACKFILL, _QUIET):
        value = await repo.get_flag(key)
        if value is not None:
            _cache[key] = value


async def set_background_prefs(
    session: AsyncSession,
    *,
    chapter_backfill: bool | None = None,
    quiet_background: bool | None = None,
) -> None:
    repo = SettingsRepo(session)
    for key, value in ((_BACKFILL, chapter_backfill), (_QUIET, quiet_background)):
        if value is not None:
            await repo.set_flag(key, value)
            _cache[key] = value
