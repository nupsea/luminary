"""Repository for `StudySessionModel` lifecycle + the repeated read
patterns the study router needs (due / weak flashcards, chunk-heading
joins, per-session review events and teachback results).

Which cards a due-queue request covers is resolved in
`services/study_queue.py`; this module only runs the resulting `DueScope`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    ChunkModel,
    FlashcardModel,
    ReviewEventModel,
    SectionModel,
    StudySessionModel,
    TeachbackResultModel,
)
from app.repos._helpers import get_or_404
from app.types import CARD_HELD

# Gap-detection thresholds. Defined here so the repo is the single
# source of truth for "what counts as a weak card". `routers/study.py`
# re-exports these as `_GAP_STABILITY_THRESHOLD` / `_GAP_MIN_REPS` for
# back-compat with any callers that still reference them.
GAP_STABILITY_THRESHOLD = 2.0
GAP_MIN_REPS = 1


@dataclass(frozen=True)
class DueScope:
    """Filters on the due queue. Every non-empty field narrows it.

    `pool` is (document ids, note ids): a card sourced from either is in scope,
    which is how a collection or a tag selects cards.
    """

    document_ids: Sequence[str] = ()
    note_ids: Sequence[str] = ()
    section_id: str | None = None
    pool: tuple[Sequence[str], Sequence[str]] | None = None

    def apply(self, stmt):  # type: ignore[no-untyped-def]
        stmt = stmt.where(FlashcardModel.due_date <= datetime.now(UTC))
        if self.section_id:
            stmt = stmt.where(
                FlashcardModel.chunk_id.in_(
                    select(ChunkModel.id).where(ChunkModel.section_id == self.section_id)
                )
            )
        if self.document_ids:
            stmt = stmt.where(FlashcardModel.document_id.in_(list(self.document_ids)))
        if self.note_ids:
            stmt = stmt.where(FlashcardModel.note_id.in_(list(self.note_ids)))
        if self.pool is not None:
            pool_docs, pool_notes = self.pool
            stmt = stmt.where(
                or_(
                    FlashcardModel.document_id.in_(list(pool_docs)),
                    FlashcardModel.note_id.in_(list(pool_notes)),
                )
            )
        return stmt


class StudyRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- StudySession lifecycle -------------------------------------------

    async def get_session_or_404(self, session_id: str) -> StudySessionModel:
        return await get_or_404(self.session, StudySessionModel, session_id, name="Session")

    async def find_session(self, session_id: str) -> StudySessionModel | None:
        return await self.session.get(StudySessionModel, session_id)

    async def find_open_session(
        self,
        *,
        mode: str,
        document_id: str | None,
        collection_id: str | None,
    ) -> StudySessionModel | None:
        """Most recent still-open session matching this scope. Scope
        match is exact: a null filter only matches null on that column."""
        stmt = select(StudySessionModel).where(
            StudySessionModel.ended_at.is_(None),
            StudySessionModel.mode == mode,
        )
        stmt = (
            stmt.where(StudySessionModel.document_id == document_id)
            if document_id is not None
            else stmt.where(StudySessionModel.document_id.is_(None))
        )
        stmt = (
            stmt.where(StudySessionModel.collection_id == collection_id)
            if collection_id is not None
            else stmt.where(StudySessionModel.collection_id.is_(None))
        )
        stmt = stmt.order_by(StudySessionModel.started_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_session(
        self,
        *,
        document_id: str | None,
        collection_id: str | None,
        mode: str,
        planned_card_ids: list[str] | None,
    ) -> StudySessionModel:
        sess = StudySessionModel(
            id=str(uuid.uuid4()),
            document_id=document_id,
            collection_id=collection_id,
            started_at=datetime.now(UTC),
            cards_reviewed=0,
            cards_correct=0,
            mode=mode,
            planned_card_ids=planned_card_ids or None,
        )
        self.session.add(sess)
        await self.session.commit()
        await self.session.refresh(sess)
        return sess

    def append_planned_cards(self, sess: StudySessionModel, card_ids: list[str]) -> int:
        """Add cards to a session's planned queue. Returns how many were new.

        Order is preserved and existing members are skipped, so a card already
        answered in this session is not queued a second time. The list is
        reassigned rather than mutated in place: `planned_card_ids` is a JSON
        column, and SQLAlchemy does not see an append to the Python list.
        """
        planned: list[str] = list(sess.planned_card_ids or [])
        seen = set(planned)
        added: list[str] = []
        for card_id in card_ids:
            if card_id in seen:
                continue
            seen.add(card_id)
            added.append(card_id)
        if not added:
            return 0
        sess.planned_card_ids = planned + added
        return len(added)

    async def commit_session(self, sess: StudySessionModel) -> StudySessionModel:
        """Persist mutations to a session row that the caller has already fetched
        and edited in place (used by /end, /reopen)."""
        await self.session.commit()
        await self.session.refresh(sess)
        return sess

    async def delete_session_cascade(self, session_id: str) -> None:
        """Delete a session plus its review events and teachback results in
        a single transaction. Used by DELETE /sessions/{id}."""
        sess = await self.get_session_or_404(session_id)
        await self.session.execute(
            sa_delete(ReviewEventModel).where(ReviewEventModel.session_id == session_id)
        )
        await self.session.execute(
            sa_delete(TeachbackResultModel).where(TeachbackResultModel.session_id == session_id)
        )
        await self.session.delete(sess)
        await self.session.commit()

    async def discard_session_if_unused(self, session_id: str) -> bool:
        """Delete a session that holds no review and no teach-back attempt.

        A run opened and left without an answer is not practice, and kept open it
        sits in the history beside the run the learner actually did. A pending
        teach-back row counts as an attempt, so a run left mid-grading survives.
        """
        sess = await self.get_session_or_404(session_id)
        for model in (ReviewEventModel, TeachbackResultModel):
            used = await self.session.execute(
                select(model.id).where(model.session_id == session_id).limit(1)
            )
            if used.first() is not None:
                return False
        await self.session.delete(sess)
        await self.session.commit()
        return True

    async def purge_runs_without_live_cards(
        self,
        *,
        document_ids: Sequence[str] = (),
        collection_ids: Sequence[str] = (),
        deleted_card_ids: Sequence[str] = (),
    ) -> int:
        """Delete runs in these scopes whose plan names no card that still exists.

        Emptying a deck -- replaced or deleted -- takes the cards its runs were
        practising. What is left can never be practised again: I-47 counts only
        planned cards that still exist, so the run reports nothing planned and
        nothing outstanding, and the results it holds render against a blank
        question because the join to the card is outer. It is a row in the
        history that cannot be entered.

        Review events are NOT touched. An event records a review that happened,
        streaks and per-day accuracy read them, and the learner record outlives
        the cards it was earned against -- the same rule
        `flashcard_repo._CARD_CHILD_TABLES` and
        `document_deletion_service._LEARNER_RECORD_TABLES` already follow.

        Two different questions decide what is reconsidered. The scopes clear the
        list the caller just emptied, including rows an earlier delete had
        already killed. `deleted_card_ids` catches the spill: a collection-scoped
        run plans cards from several documents at once, so replacing one
        document's deck can empty it without ever naming the collection. Only a
        run that planned one of these cards is reconsidered that way, so a run
        that was dead before this call and belongs to nobody's list here is left
        where it is.
        """
        scopes = []
        if document_ids:
            scopes.append(StudySessionModel.document_id.in_(list(document_ids)))
        if collection_ids:
            scopes.append(StudySessionModel.collection_id.in_(list(collection_ids)))
        if not scopes and not deleted_card_ids:
            return 0

        rows = (
            (await self.session.execute(select(StudySessionModel).where(or_(*scopes))))
            .scalars()
            .all()
            if scopes
            else []
        )
        # A run with no plan at all was never built on these cards, so a
        # replacement does not make it dead.
        planned_runs = [(s, list(s.planned_card_ids or [])) for s in rows]
        planned_runs = [(s, plan) for s, plan in planned_runs if plan]

        if deleted_card_ids:
            gone = set(deleted_card_ids)
            seen = {s.id for s, _plan in planned_runs}
            spill = (
                (
                    await self.session.execute(
                        select(StudySessionModel).where(
                            StudySessionModel.collection_id.is_not(None),
                            StudySessionModel.document_id.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            planned_runs += [
                (s, plan)
                for s, plan in ((s, list(s.planned_card_ids or [])) for s in spill)
                if plan and s.id not in seen and gone.intersection(plan)
            ]

        if not planned_runs:
            return 0

        every_planned = {cid for _s, plan in planned_runs for cid in plan}
        live = set(
            (
                await self.session.execute(
                    select(FlashcardModel.id).where(FlashcardModel.id.in_(every_planned))
                )
            )
            .scalars()
            .all()
        )
        dead_ids = [s.id for s, plan in planned_runs if not any(c in live for c in plan)]
        if not dead_ids:
            return 0

        await self.session.execute(
            sa_delete(TeachbackResultModel).where(TeachbackResultModel.session_id.in_(dead_ids))
        )
        await self.session.execute(
            sa_delete(StudySessionModel).where(StudySessionModel.id.in_(dead_ids))
        )
        await self.session.commit()
        return len(dead_ids)

    async def list_sessions(
        self,
        *,
        document_id: str | None,
        collection_id: str | None,
        mode: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> tuple[int, Sequence[StudySessionModel]]:
        """(total matching, one page newest first). status is incomplete | complete."""
        stmt = select(StudySessionModel)
        if document_id:
            stmt = stmt.where(StudySessionModel.document_id == document_id)
        if collection_id:
            stmt = stmt.where(StudySessionModel.collection_id == collection_id)
        if mode:
            stmt = stmt.where(StudySessionModel.mode == mode)
        if status == "incomplete":
            stmt = stmt.where(StudySessionModel.ended_at.is_(None))
        elif status == "complete":
            stmt = stmt.where(StudySessionModel.ended_at.is_not(None))
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        page = await self.session.execute(
            stmt.order_by(StudySessionModel.started_at.desc()).offset(offset).limit(limit)
        )
        return total, page.scalars().all()

    async def list_sessions_for_document(self, document_id: str) -> Sequence[StudySessionModel]:
        result = await self.session.execute(
            select(StudySessionModel).where(StudySessionModel.document_id == document_id)
        )
        return result.scalars().all()

    async def list_ended_sessions_since(
        self, cutoff: datetime, *, document_id: str | None = None
    ) -> Sequence[StudySessionModel]:
        stmt = select(StudySessionModel).where(
            StudySessionModel.started_at >= cutoff,
            StudySessionModel.ended_at.is_not(None),
        )
        if document_id:
            stmt = stmt.where(StudySessionModel.document_id == document_id)
        return (await self.session.execute(stmt)).scalars().all()

    # -- Review events / teachback results --------------------------------

    async def predictions_since(self, cutoff: datetime) -> list[tuple[str, str, datetime]]:
        """(predicted rating, actual rating, reviewed at) for reviews made with a prediction."""
        result = await self.session.execute(
            select(
                ReviewEventModel.predicted_rating,
                ReviewEventModel.rating,
                ReviewEventModel.reviewed_at,
            ).where(
                ReviewEventModel.predicted_rating.is_not(None),
                ReviewEventModel.reviewed_at >= cutoff,
            )
        )
        return [(predicted, actual, at) for predicted, actual, at in result.all()]

    async def find_teachback(self, teachback_id: str) -> TeachbackResultModel | None:
        return await self.session.get(TeachbackResultModel, teachback_id)

    async def has_earlier_attempt(self, row: TeachbackResultModel) -> bool:
        """Whether this card was already answered earlier in the same session."""
        result = await self.session.execute(
            select(TeachbackResultModel.id)
            .where(
                TeachbackResultModel.session_id == row.session_id,
                TeachbackResultModel.flashcard_id == row.flashcard_id,
                TeachbackResultModel.created_at < row.created_at,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def teachback_results_with_cards(
        self, *, ids: Sequence[str] | None = None, session_id: str | None = None
    ) -> list[tuple[TeachbackResultModel, str | None, str | None]]:
        """(result, card question, card answer) by result ids or for a session, oldest first.

        Outer join: a result whose card was deleted still comes back, with no text.
        """
        stmt = select(TeachbackResultModel, FlashcardModel.question, FlashcardModel.answer).join(
            FlashcardModel,
            TeachbackResultModel.flashcard_id == FlashcardModel.id,
            isouter=True,
        )
        if ids is not None:
            stmt = stmt.where(TeachbackResultModel.id.in_(list(ids)))
        if session_id is not None:
            stmt = stmt.where(TeachbackResultModel.session_id == session_id).order_by(
                TeachbackResultModel.created_at
            )
        return [(tb, q, a) for tb, q, a in (await self.session.execute(stmt)).all()]

    async def pending_teachback_counts(self, session_ids: Sequence[str]) -> dict[str, int]:
        if not session_ids:
            return {}
        result = await self.session.execute(
            select(TeachbackResultModel.session_id, func.count())
            .where(
                TeachbackResultModel.session_id.in_(list(session_ids)),
                TeachbackResultModel.status == "pending",
            )
            .group_by(TeachbackResultModel.session_id)
        )
        return {sid: n for sid, n in result.all() if sid is not None}

    async def list_review_events_with_cards(
        self, session_id: str
    ) -> list[tuple[ReviewEventModel, FlashcardModel]]:
        """Events in review order, each with its card. Events of deleted cards drop out."""
        result = await self.session.execute(
            select(ReviewEventModel, FlashcardModel)
            .join(FlashcardModel, ReviewEventModel.flashcard_id == FlashcardModel.id)
            .where(ReviewEventModel.session_id == session_id)
            .order_by(ReviewEventModel.reviewed_at)
        )
        return [(event, card) for event, card in result.all()]

    async def answered_card_ids(self, session_id: str) -> set[str]:
        """Cards with a teach-back result or a review event in this session."""
        answered = set(
            (
                await self.session.execute(
                    select(TeachbackResultModel.flashcard_id).where(
                        TeachbackResultModel.session_id == session_id
                    )
                )
            ).scalars()
        )
        answered.update(
            (
                await self.session.execute(
                    select(ReviewEventModel.flashcard_id).where(
                        ReviewEventModel.session_id == session_id
                    )
                )
            ).scalars()
        )
        return answered

    async def list_review_events(self, session_id: str) -> Sequence[ReviewEventModel]:
        result = await self.session.execute(
            select(ReviewEventModel).where(ReviewEventModel.session_id == session_id)
        )
        return result.scalars().all()

    async def list_teachback_results(
        self,
        session_id: str,
        *,
        status: str | None = None,
    ) -> Sequence[TeachbackResultModel]:
        stmt = select(TeachbackResultModel).where(
            TeachbackResultModel.session_id == session_id,
        )
        if status is not None:
            stmt = stmt.where(TeachbackResultModel.status == status)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # -- Flashcard read patterns ------------------------------------------

    async def due_or_unscheduled_for_document(self, document_id: str) -> list[FlashcardModel]:
        stmt = (
            select(FlashcardModel)
            .where(
                FlashcardModel.document_id == document_id,
                FlashcardModel.fsrs_state != CARD_HELD,
                or_(
                    FlashcardModel.due_date <= datetime.now(UTC),
                    FlashcardModel.due_date.is_(None),
                ),
            )
            .order_by(FlashcardModel.due_date.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_due(self, scope: DueScope) -> int:
        stmt = scope.apply(select(func.count()).select_from(FlashcardModel))
        return (await self.session.execute(stmt)).scalar_one()

    async def list_due(self, scope: DueScope, *, limit: int) -> list[FlashcardModel]:
        stmt = scope.apply(select(FlashcardModel)).order_by(FlashcardModel.due_date.asc())
        return list((await self.session.execute(stmt.limit(limit))).scalars().all())

    async def list_weak_flashcards(
        self,
        *,
        document_id: str | None = None,
    ) -> Sequence[FlashcardModel]:
        """Seen-but-fragile flashcards (low FSRS stability after at least one
        rep). Used by /gaps/{document_id} (with document filter) and by the
        global session-plan (no filter)."""
        stmt = (
            select(FlashcardModel)
            .where(FlashcardModel.fsrs_stability < GAP_STABILITY_THRESHOLD)
            .where(FlashcardModel.reps > GAP_MIN_REPS)
        )
        if document_id is not None:
            stmt = stmt.where(FlashcardModel.document_id == document_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def chunk_section_headings(self, chunk_ids: Sequence[str]) -> dict[str, str | None]:
        """Map chunk_id -> section heading. Used for source-panel context
        in /due, /session-plan, and /gaps."""
        if not chunk_ids:
            return {}
        stmt = (
            select(ChunkModel.id, SectionModel.heading)
            .outerjoin(SectionModel, ChunkModel.section_id == SectionModel.id)
            .where(ChunkModel.id.in_(chunk_ids))
        )
        result = await self.session.execute(stmt)
        return dict(result.all())

    async def chunk_section_id_map(self, chunk_ids: Sequence[str]) -> dict[str, str | None]:
        """Map chunk_id -> section_id (no heading join). Used by /due for
        the SourcePanel."""
        if not chunk_ids:
            return {}
        result = await self.session.execute(
            select(ChunkModel.id, ChunkModel.section_id).where(ChunkModel.id.in_(chunk_ids))
        )
        return dict(result.all())


def get_study_repo(session: AsyncSession = Depends(get_db)) -> StudyRepo:
    return StudyRepo(session)
