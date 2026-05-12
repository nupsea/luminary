"""Repository for `StudySessionModel` lifecycle + the repeated read
patterns the study router needs (due / weak flashcards, chunk-heading
joins, per-session review events and teachback results).

Bespoke multi-table dashboard queries (e.g.
`get_collection_study_dashboard`, the tag-scoped filter logic inside
`get_due_count` / `get_due_cards`) stay inline in `routers/study.py`
because their join shapes are not reused elsewhere.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
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
from app.services.repo_helpers import get_or_404

# Gap-detection thresholds. Defined here so the repo is the single
# source of truth for "what counts as a weak card". `routers/study.py`
# re-exports these as `_GAP_STABILITY_THRESHOLD` / `_GAP_MIN_REPS` for
# back-compat with any callers that still reference them.
GAP_STABILITY_THRESHOLD = 2.0
GAP_MIN_REPS = 1


class StudyRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- StudySession lifecycle -------------------------------------------

    async def get_session_or_404(self, session_id: str) -> StudySessionModel:
        return await get_or_404(
            self.session, StudySessionModel, session_id, name="Session"
        )

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
            sa_delete(ReviewEventModel).where(
                ReviewEventModel.session_id == session_id
            )
        )
        await self.session.execute(
            sa_delete(TeachbackResultModel).where(
                TeachbackResultModel.session_id == session_id
            )
        )
        await self.session.delete(sess)
        await self.session.commit()

    # -- Review events / teachback results --------------------------------

    async def list_review_events(
        self, session_id: str
    ) -> Sequence[ReviewEventModel]:
        result = await self.session.execute(
            select(ReviewEventModel).where(
                ReviewEventModel.session_id == session_id
            )
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

    async def chunk_section_headings(
        self, chunk_ids: Sequence[str]
    ) -> dict[str, str | None]:
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
        return {cid: heading for cid, heading in result.all()}

    async def chunk_section_id_map(
        self, chunk_ids: Sequence[str]
    ) -> dict[str, str | None]:
        """Map chunk_id -> section_id (no heading join). Used by /due for
        the S138 SourcePanel."""
        if not chunk_ids:
            return {}
        result = await self.session.execute(
            select(ChunkModel.id, ChunkModel.section_id).where(
                ChunkModel.id.in_(chunk_ids)
            )
        )
        return {cid: sid for cid, sid in result.all()}


def get_study_repo(session: AsyncSession = Depends(get_db)) -> StudyRepo:
    return StudyRepo(session)
