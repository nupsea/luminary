"""Writes the chapters ingestion left, nearest the reader first, when the machine can spare it.

Work follows reading (#231): only documents read in the last RECENT_DAYS get chapters beyond
the ones ingestion writes, so a library of unopened books costs nothing.

- **Ahead**: the chapter being read and the next one. They are due within minutes, so they
  are written whenever the runtime is free; admission still yields every call to the user.
- **Later chapters**: only while the machine is idle -- on mains power, no question asked in
  the last QUIET_SECONDS, the processor not busy with other programs, no document ingesting.

Either way the model must already be loaded or fit with headroom to spare. Nothing here adds
a model or a serving slot: on the 16GB floor the one resident model and its one slot are all
there is (I-31), and one chapter at a time is the unit of work, so pausing costs nothing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import psutil

from app.config import get_settings
from app.database import get_session_factory
from app.repos.document_repo import DocumentRepo
from app.repos.flashcard_repo import FlashcardRepo
from app.services.chapter_cards import _known_names, write_chapter
from app.services.chapters import Chapter, chapters_for_document

logger = logging.getLogger(__name__)

TICK_SECONDS = 60.0
RECENT_DAYS = 14
# Chapters past the one being read that count as ahead.
AHEAD = 1
# A question within this long means the learner is at the machine and may ask another.
QUIET_SECONDS = 300.0
# Other programs above this share of the processor make later chapters wait.
BUSY_CPU_PERCENT = 50.0
# Ahead on battery only above this charge.
LOW_BATTERY_PERCENT = 30
# Free memory that must remain after loading the model to write a chapter: what lets a 16GB
# laptop keep its other programs in memory instead of swapping.
HEADROOM_BYTES = 2 * 1024**3


@dataclass(frozen=True)
class Pick:
    document_id: str
    title: str
    chapter: Chapter
    ahead: bool


def _reading_index(chapters: list[Chapter], section_id: str | None) -> int:
    for i, c in enumerate(chapters):
        if section_id in c.section_ids:
            return i
    return 0


async def next_chapter() -> Pick | None:
    """The unwritten chapter nearest a reader: any document's ahead chapters before later ones."""
    since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
    later: Pick | None = None
    async with get_session_factory()() as session:
        reading = await DocumentRepo(session).recently_read(since)
        for document_id, title, section_id in reading:
            chapters = await chapters_for_document(document_id, title, session)
            written = await FlashcardRepo(session).chapters_written(document_id)
            here = _reading_index(chapters, section_id)
            # Ahead first, then the rest of the book from the reader onward, then what was read.
            order = chapters[here:] + chapters[:here]
            for chapter in order:
                if chapter.id in written:
                    continue
                ahead = here <= chapter.order <= here + AHEAD
                if ahead:
                    return Pick(document_id, title, chapter, ahead=True)
                later = later or Pick(document_id, title, chapter, ahead=False)
                break
    return later


async def _model_fits() -> str | None:
    """Why loading the model now would crowd the machine, or None."""
    from app.services.model_router import resolve  # noqa: PLC0415

    choice = resolve("background")
    if not choice.is_local:
        return None
    name = choice.model.removeprefix("ollama/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{get_settings().OLLAMA_URL}/api/ps")
            loaded = {m.get("name") for m in resp.json().get("models") or []}
    except (httpx.HTTPError, ValueError):
        loaded = set()
    if loaded & {name, f"{name}:latest"}:
        return None
    needed = (choice.profile.resident_bytes if choice.profile else 0) + HEADROOM_BYTES
    if psutil.virtual_memory().available < needed:
        return "not enough free memory to load the model"
    return None


def _battery_reason(ahead: bool) -> str | None:
    battery = psutil.sensors_battery()
    if battery is None or battery.power_plugged:
        return None
    if not ahead:
        return "on battery"
    return "battery low" if battery.percent < LOW_BATTERY_PERCENT else None


async def _idle_reason() -> str | None:
    """Why later chapters must wait, or None when the machine is idle."""
    from app.services.llm_admission import current_state  # noqa: PLC0415

    state = current_state()
    if state is not None and state.interactive_inflight:
        return "in use"
    if state is not None and state.last_interactive_end > 0:
        if time.monotonic() - state.last_interactive_end < QUIET_SECONDS:
            return "in use"
    async with get_session_factory()() as session:
        since = datetime.now(UTC) - timedelta(days=1)
        if await DocumentRepo(session).enrichment_in_progress(since):
            return "a document is being enriched"
    cpu = await asyncio.to_thread(psutil.cpu_percent, 1.0)
    return "processor busy" if cpu >= BUSY_CPU_PERCENT else None


async def not_now(pick: Pick) -> str | None:
    """Why *pick* must wait, or None when it may be written now."""
    from app.services.llm_routing import refusal  # noqa: PLC0415

    reason = refusal("background") or _battery_reason(pick.ahead)
    if reason is None and not pick.ahead:
        reason = await _idle_reason()
    return reason or await _model_fits()


async def run_once() -> bool:
    """Write one chapter if one is waiting and the machine can spare it; whether it did."""
    pick = await next_chapter()
    if pick is None:
        return False
    reason = await not_now(pick)
    if reason is not None:
        logger.debug("chapter backfill waits (%s): %s", reason, pick.chapter.title[:60])
        return False
    async with get_session_factory()() as session:
        names = await _known_names(pick.document_id, session)
        await write_chapter(pick.document_id, pick.title, pick.chapter, names, session)
    return True


class ChapterBackfill:
    """One chapter at a time, checking the machine again before each."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if get_settings().CHAPTER_CARDS_BACKFILL and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="chapter-backfill")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        # Waits first: start-up already loads models and drains the enrichment queue.
        wrote = False
        while True:
            if not wrote:
                await asyncio.sleep(TICK_SECONDS)
            try:
                wrote = await run_once()
            except Exception:
                logger.exception("chapter backfill failed; retrying next tick")
                wrote = False
