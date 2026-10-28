"""What the learner lets unattended work do: write chapters ahead, and at what pace.

Cached because admission reads the pace on every background call; loaded when the process
first serves a library and written through on every change. Each library holds its own (#389).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.library import DEFAULT_LIBRARY, current_library
from app.repos.settings_repo import SettingsRepo
from app.storage import library_root

_BACKFILL = "chapter_backfill"
_QUIET = "quiet_background"

# The default library's; any other's in `_library_caches`, keyed by root.
_cache: dict[str, bool] = {}
_library_caches: dict[Path, dict[str, bool]] = {}


def _prefs() -> dict[str, bool]:
    library = current_library()
    if library == DEFAULT_LIBRARY:
        return _cache
    return _library_caches.setdefault(library_root(library=library), {})


def chapter_backfill() -> bool:
    """Whether chapters past the first ones are written in the background (#231)."""
    return _prefs().get(_BACKFILL, get_settings().CHAPTER_CARDS_BACKFILL)


def quiet_background() -> bool:
    """Whether unattended model calls are paced (`llm_admission.background_duty`)."""
    return _prefs().get(_QUIET, True)


async def load_background_prefs(session: AsyncSession) -> None:
    repo = SettingsRepo(session)
    for key in (_BACKFILL, _QUIET):
        value = await repo.get_flag(key)
        if value is not None:
            _prefs()[key] = value


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
            _prefs()[key] = value
