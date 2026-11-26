"""Which flashcards a due-queue request covers: explicit ids, a collection tree, a tag."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repos.collection_repo import CollectionRepo
from app.repos.document_repo import DocumentRepo
from app.repos.study_repo import DueScope, StudyRepo
from app.repos.tag_repo import TagRepo
from app.services.documents_service import safe_tags
from app.services.settings_service import get_new_cards_per_day


async def _documents_tagged(
    session: AsyncSession, tag: str, within: Sequence[str] | None
) -> list[str]:
    rows = await DocumentRepo(session).tags_by_id(within)
    return [doc_id for doc_id, tags in rows if tag in safe_tags(tags)]


async def due_scope(
    session: AsyncSession,
    *,
    document_ids: Sequence[str] | None = None,
    note_ids: Sequence[str] | None = None,
    collection_id: str | None = None,
    tag: str | None = None,
    section_id: str | None = None,
) -> DueScope:
    """Explicit ids override the collection; a tag narrows whichever applies."""
    pool: tuple[list[str], list[str]] | None = None
    if collection_id and not (document_ids or note_ids):
        doc_ids, member_note_ids = await CollectionRepo(session).member_ids_recursive(collection_id)
        if tag:
            doc_ids = await _documents_tagged(session, tag, doc_ids)
            tagged = set(await TagRepo(session).note_ids_with_tag(tag))
            member_note_ids = [n for n in member_note_ids if n in tagged]
        pool = (doc_ids, member_note_ids)
    elif tag:
        pool = (
            await _documents_tagged(session, tag, None),
            await TagRepo(session).note_ids_with_tag(tag),
        )
    return DueScope(
        document_ids=document_ids or (),
        note_ids=note_ids or (),
        section_id=section_id,
        pool=pool,
    )


@dataclass(frozen=True)
class NewCardBudget:
    per_day: int
    introduced_today: int

    @property
    def left(self) -> int:
        return max(0, self.per_day - self.introduced_today)


def local_day_start(tz_offset_minutes: int, now: datetime | None = None) -> datetime:
    """The user's local midnight as naive UTC; the offset is JS `getTimezoneOffset()`."""
    utc_now = (now or datetime.now(UTC)).replace(tzinfo=None)
    local_now = utc_now - timedelta(minutes=tz_offset_minutes)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight + timedelta(minutes=tz_offset_minutes)


async def new_card_budget(session: AsyncSession, tz_offset_minutes: int = 0) -> NewCardBudget:
    """How many unseen cards today's library-wide session may still introduce (I-83).

    Counted from first reviews, so it survives restarts and covers every surface that
    reviews a card, not only the daily session.
    """
    introduced = await StudyRepo(session).count_introduced_since(local_day_start(tz_offset_minutes))
    return NewCardBudget(per_day=await get_new_cards_per_day(session), introduced_today=introduced)


async def new_card_limit(
    session: AsyncSession, scope: DueScope, limit: int, tz_offset_minutes: int = 0
) -> int:
    """The budget governs the whole-library queue only: a chosen scope asked for its cards."""
    if not scope.is_everything:
        return limit
    return (await new_card_budget(session, tz_offset_minutes)).left
