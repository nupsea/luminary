"""Sole writer of the content_activity table (plan 2E.8).

All bump rules live here; callers (notes, flashcards, the doc-read endpoint)
go through this service so the "recently touched" hub feed has a single,
auditable source of truth.

The why behind the debouncing: pure clicks must NOT bump (last_accessed_at
already does that and it's deliberately a different signal). Scroll-spam on
a doc shouldn't write 60 rows in a minute; rapid note keystrokes shouldn't
write per character. We coalesce writes within a debounce window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ActivityService:
    DOC_READ_DEBOUNCE = timedelta(seconds=5)
    NOTE_EDIT_DEBOUNCE = timedelta(seconds=30)

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_doc_read(self, document_id: str) -> bool:
        """Bump when a doc has been opened AND scrolled past 10%. Caller is
        expected to gate on the 10% threshold; this only handles debouncing.
        Returns True if a write actually happened."""
        return await self._bump_if_stale(
            "document", document_id, self.DOC_READ_DEBOUNCE
        )

    async def record_note_edit(self, note_id: str) -> bool:
        """Bump on a meaningful note edit (content change, not a pure open)."""
        return await self._bump_if_stale("note", note_id, self.NOTE_EDIT_DEBOUNCE)

    async def record_flashcard_event(
        self, *, document_id: str | None, note_id: str | None
    ) -> bool:
        """Bump on flashcard create or grade. No debounce: review cadence is
        slow enough that every event is meaningful. document_id wins when both
        are set (note-sourced cards still attach to the doc activity if linked).
        Returns True when a row was written."""
        if document_id:
            await self._bump_unconditional("document", document_id)
            return True
        if note_id:
            await self._bump_unconditional("note", note_id)
            return True
        return False

    # -- internals ---------------------------------------------------------

    async def _bump_if_stale(
        self, member_type: str, member_id: str, debounce: timedelta
    ) -> bool:
        cutoff = datetime.now(UTC) - debounce
        existing = (
            await self.session.execute(
                text(
                    "SELECT last_meaningful_at FROM content_activity "
                    "WHERE member_type = :t AND member_id = :i"
                ),
                {"t": member_type, "i": member_id},
            )
        ).first()
        if existing is not None:
            last_at = existing[0]
            # text() SELECTs return TIMESTAMP columns as ISO strings under
            # aiosqlite; ORM-backed selects would decode automatically. Parse
            # here so this helper can be called from raw-SQL paths too.
            if isinstance(last_at, str):
                last_at = datetime.fromisoformat(last_at)
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=UTC)
            if last_at >= cutoff:
                return False
        await self._bump_unconditional(member_type, member_id)
        return True

    async def _bump_unconditional(self, member_type: str, member_id: str) -> None:
        await self.session.execute(
            text(
                "INSERT INTO content_activity (member_type, member_id, last_meaningful_at) "
                "VALUES (:t, :i, :now) "
                "ON CONFLICT(member_type, member_id) DO UPDATE SET "
                "last_meaningful_at = excluded.last_meaningful_at"
            ),
            {
                "t": member_type,
                "i": member_id,
                "now": datetime.now(UTC),
            },
        )
        await self.session.commit()


def get_activity_service(session: AsyncSession) -> ActivityService:
    return ActivityService(session)
