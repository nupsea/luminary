"""S210: LearningGoalsService -- typed learning goals + progress aggregation.

Goal types and progress semantics:
- studying -- minutes_focused = sum(focus_minutes) of every completed linked
              session, with surface breakdowns for analytics.
- read    -- minutes_focused = sum(focus_minutes) of completed linked sessions
             with surface='read' or surface='write' so website reading with
             note-taking still attributes to reading goals.
- recall  -- cards_reviewed = distinct flashcards reviewed within completed
             linked sessions with surface='recall'; avg_retention = mean of
             ReviewEventModel.is_correct.
- write   -- notes_created = NoteModel rows whose created_at falls inside any
             completed linked session window with surface='write'.
- explore -- turns = QAHistoryModel rows whose created_at falls inside any
             completed linked session window with surface='explore'.

Goalless Pomodoro sessions (goal_id NULL) still flow through pomodoro stats;
they simply do not attribute to any goal.

SQLite cannot ALTER ADD FK, so the goal_id -> learning_goals.id relationship is
enforced at the service layer: link_session validates the goal exists, and
delete_goal NULLs out linked sessions before deleting the goal row (equivalent
to ON DELETE SET NULL).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FlashcardModel,
    LearningGoalModel,
    NoteModel,
    PomodoroSessionModel,
    QAHistoryModel,
    ReviewEventModel,
)

logger = logging.getLogger(__name__)


VALID_GOAL_TYPES = {"studying", "read", "recall", "write", "explore"}
VALID_TARGET_UNITS = {"minutes", "pages", "cards", "notes", "turns"}
VALID_STATUSES = {"active", "paused", "completed", "archived"}


class GoalError(Exception):
    """Base for service-level goal errors."""


class GoalNotFound(GoalError):
    """Raised when a goal id is not in the database."""


class InvalidGoalType(GoalError):
    """Raised when goal_type is not in VALID_GOAL_TYPES."""


class InvalidTargetUnit(GoalError):
    """Raised when target_unit is set but not in VALID_TARGET_UNITS."""


class SessionNotFound(GoalError):
    """Raised when a referenced pomodoro session id does not exist."""


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(dt: datetime) -> datetime:
    """SQLite returns tz-naive datetimes; treat them as UTC for arithmetic."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class LearningGoalsService:
    """CRUD + progress aggregation for typed learning goals."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ helpers

    async def _get(self, goal_id: str) -> LearningGoalModel:
        result = await self._session.execute(
            select(LearningGoalModel).where(LearningGoalModel.id == goal_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise GoalNotFound(f"learning goal {goal_id} not found")
        return row

    # ------------------------------------------------------------------ CRUD

    async def create_goal(
        self,
        title: str,
        goal_type: str,
        target_value: int | None = None,
        target_unit: str | None = None,
        document_id: str | None = None,
        deck_id: str | None = None,
        collection_id: str | None = None,
        description: str | None = None,
    ) -> LearningGoalModel:
        if goal_type not in VALID_GOAL_TYPES:
            raise InvalidGoalType(f"invalid goal_type: {goal_type}")
        if target_unit is not None and target_unit not in VALID_TARGET_UNITS:
            raise InvalidTargetUnit(f"invalid target_unit: {target_unit}")
        title = (title or "").strip()
        if not title:
            raise ValueError("title must not be empty")

        row = LearningGoalModel(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            goal_type=goal_type,
            target_value=target_value,
            target_unit=target_unit,
            document_id=document_id,
            deck_id=deck_id,
            collection_id=collection_id,
            status="active",
            created_at=_now(),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        logger.info("Created learning goal %s type=%s", row.id, goal_type)
        return row

    async def get_goal(self, goal_id: str) -> LearningGoalModel | None:
        result = await self._session.execute(
            select(LearningGoalModel).where(LearningGoalModel.id == goal_id)
        )
        return result.scalar_one_or_none()

    async def list_goals(self, status_filter: str | None = None) -> list[LearningGoalModel]:
        stmt = select(LearningGoalModel).order_by(LearningGoalModel.created_at.desc())
        if status_filter is not None:
            if status_filter not in VALID_STATUSES:
                raise ValueError(f"invalid status filter: {status_filter}")
            stmt = stmt.where(LearningGoalModel.status == status_filter)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_goal(
        self,
        goal_id: str,
        title: str | None = None,
        description: str | None = None,
        target_value: int | None = None,
        target_unit: str | None = None,
    ) -> LearningGoalModel:
        """Patch the four mutable fields. goal_type and FK fields are immutable."""
        row = await self._get(goal_id)
        if title is not None:
            stripped = title.strip()
            if not stripped:
                raise ValueError("title must not be empty")
            row.title = stripped
        if description is not None:
            row.description = description
        if target_value is not None:
            row.target_value = target_value
        if target_unit is not None:
            if target_unit not in VALID_TARGET_UNITS:
                raise InvalidTargetUnit(f"invalid target_unit: {target_unit}")
            row.target_unit = target_unit
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def archive_goal(self, goal_id: str) -> LearningGoalModel:
        row = await self._get(goal_id)
        row.status = "archived"
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def complete_goal(self, goal_id: str) -> LearningGoalModel:
        row = await self._get(goal_id)
        row.status = "completed"
        row.completed_at = _now()
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def delete_goal(self, goal_id: str) -> bool:
        """Delete the goal; service-level ON DELETE SET NULL on linked sessions."""
        row = await self.get_goal(goal_id)
        if row is None:
            return False
        # Equivalent to ON DELETE SET NULL: clear goal_id on every linked session.
        await self._session.execute(
            update(PomodoroSessionModel)
            .where(PomodoroSessionModel.goal_id == goal_id)
            .values(goal_id=None)
        )
        await self._session.delete(row)
        await self._session.commit()
        logger.info("Deleted learning goal %s", goal_id)
        return True

    # ------------------------------------------------------------------ session linking

    async def link_session(self, goal_id: str, session_id: str) -> PomodoroSessionModel:
        # Verify the goal exists -- raises GoalNotFound otherwise.
        await self._get(goal_id)
        result = await self._session.execute(
            select(PomodoroSessionModel).where(PomodoroSessionModel.id == session_id)
        )
        sess = result.scalar_one_or_none()
        if sess is None:
            raise SessionNotFound(f"pomodoro session {session_id} not found")
        sess.goal_id = goal_id
        await self._session.commit()
        await self._session.refresh(sess)
        return sess

    async def unlink_session(self, goal_id: str, session_id: str) -> PomodoroSessionModel:
        result = await self._session.execute(
            select(PomodoroSessionModel).where(PomodoroSessionModel.id == session_id)
        )
        sess = result.scalar_one_or_none()
        if sess is None:
            raise SessionNotFound(f"pomodoro session {session_id} not found")
        if sess.goal_id == goal_id:
            sess.goal_id = None
            await self._session.commit()
            await self._session.refresh(sess)
        return sess

    async def list_linked_sessions(
        self, goal_id: str, limit: int = 20
    ) -> list[PomodoroSessionModel]:
        """Most-recent first, used by the S211 detail panel."""
        result = await self._session.execute(
            select(PomodoroSessionModel)
            .where(PomodoroSessionModel.goal_id == goal_id)
            .order_by(PomodoroSessionModel.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------ progress

    async def compute_progress(self, goal_id: str) -> dict[str, Any]:
        goal = await self._get(goal_id)
        if goal.goal_type == "studying":
            return await self._progress_studying(goal)
        if goal.goal_type == "read":
            return await self._progress_read(goal)
        if goal.goal_type == "recall":
            return await self._progress_recall(goal)
        if goal.goal_type == "write":
            return await self._progress_write(goal)
        if goal.goal_type == "explore":
            return await self._progress_explore(goal)
        raise InvalidGoalType(f"unknown goal_type: {goal.goal_type}")

    async def _completed_sessions(
        self, goal_id: str, surfaces: str | list[str]
    ) -> list[PomodoroSessionModel]:
        surface_values = [surfaces] if isinstance(surfaces, str) else surfaces
        result = await self._session.execute(
            select(PomodoroSessionModel).where(
                PomodoroSessionModel.goal_id == goal_id,
                PomodoroSessionModel.status == "completed",
                PomodoroSessionModel.surface.in_(surface_values),
            )
        )
        return list(result.scalars().all())

    async def _all_completed_sessions(self, goal_id: str) -> list[PomodoroSessionModel]:
        result = await self._session.execute(
            select(PomodoroSessionModel).where(
                PomodoroSessionModel.goal_id == goal_id,
                PomodoroSessionModel.status == "completed",
            )
        )
        return list(result.scalars().all())

    @staticmethod
    def _pct(numerator: float, target: int | None) -> float | None:
        if target is None or target <= 0:
            return None
        return round(min(100.0, (numerator / target) * 100.0), 2)

    def _goal_metadata(self, goal: LearningGoalModel) -> dict[str, str | None]:
        return {
            "document_id": goal.document_id,
            "deck_id": goal.deck_id,
            "collection_id": goal.collection_id,
        }

    async def _progress_studying(self, goal: LearningGoalModel) -> dict[str, Any]:
        sessions = await self._all_completed_sessions(goal.id)
        minutes_focused = sum(s.focus_minutes for s in sessions)
        surface_minutes: dict[str, int] = {}
        surface_sessions: dict[str, int] = {}
        for sess in sessions:
            surface = sess.surface or "none"
            surface_minutes[surface] = surface_minutes.get(surface, 0) + sess.focus_minutes
            surface_sessions[surface] = surface_sessions.get(surface, 0) + 1
        return {
            "minutes_focused": minutes_focused,
            "sessions_completed": len(sessions),
            "surface_minutes": surface_minutes,
            "surface_sessions": surface_sessions,
            "metadata": self._goal_metadata(goal),
            "completed_pct": self._pct(minutes_focused, goal.target_value),
        }

    async def _progress_read(self, goal: LearningGoalModel) -> dict[str, Any]:
        sessions = await self._completed_sessions(goal.id, ["read", "write"])
        minutes_focused = sum(s.focus_minutes for s in sessions)
        sessions_completed = len(sessions)
        completed_pct = self._pct(minutes_focused, goal.target_value)
        return {
            "minutes_focused": minutes_focused,
            "sessions_completed": sessions_completed,
            "completed_pct": completed_pct,
        }

    async def _progress_recall(self, goal: LearningGoalModel) -> dict[str, Any]:
        sessions = await self._completed_sessions(goal.id, "recall")
        sessions_completed = len(sessions)
        if not sessions:
            return {
                "cards_reviewed": 0,
                "avg_retention": None,
                "sessions_completed": 0,
                "completed_pct": self._pct(0, goal.target_value),
            }

        # Build OR conditions across session windows.
        unique_cards: set[str] = set()
        correct_count = 0
        total_events = 0
        for sess in sessions:
            window_start = (
                _as_utc(sess.started_at) if sess.started_at is not None else None
            )
            window_end = (
                _as_utc(sess.completed_at) if sess.completed_at is not None else None
            )
            if window_start is None or window_end is None:
                continue
            stmt = select(ReviewEventModel).where(
                ReviewEventModel.reviewed_at >= window_start,
                ReviewEventModel.reviewed_at <= window_end,
            )
            result = await self._session.execute(stmt)
            events = list(result.scalars().all())

            if goal.deck_id is not None:
                # Filter to flashcards belonging to the deck.
                deck_card_ids = await self._deck_flashcard_ids(goal.deck_id)
                events = [e for e in events if e.flashcard_id in deck_card_ids]

            for e in events:
                unique_cards.add(e.flashcard_id)
                total_events += 1
                if e.is_correct:
                    correct_count += 1

        cards_reviewed = len(unique_cards)
        avg_retention: float | None = None
        if total_events > 0:
            avg_retention = round(correct_count / total_events, 4)

        return {
            "cards_reviewed": cards_reviewed,
            "avg_retention": avg_retention,
            "sessions_completed": sessions_completed,
            "completed_pct": self._pct(cards_reviewed, goal.target_value),
        }

    async def _deck_flashcard_ids(self, deck_id: str) -> set[str]:
        result = await self._session.execute(
            select(FlashcardModel.id).where(FlashcardModel.deck == deck_id)
        )
        return set(result.scalars().all())

    async def _progress_write(self, goal: LearningGoalModel) -> dict[str, Any]:
        sessions = await self._completed_sessions(goal.id, "write")
        sessions_completed = len(sessions)
        notes_created = 0
        for sess in sessions:
            window_start = (
                _as_utc(sess.started_at) if sess.started_at is not None else None
            )
            window_end = (
                _as_utc(sess.completed_at) if sess.completed_at is not None else None
            )
            if window_start is None or window_end is None:
                continue
            cnt = (
                await self._session.execute(
                    select(func.count(NoteModel.id)).where(
                        NoteModel.created_at >= window_start,
                        NoteModel.created_at <= window_end,
                    )
                )
            ).scalar_one()
            notes_created += int(cnt)
        return {
            "notes_created": notes_created,
            "sessions_completed": sessions_completed,
            "completed_pct": self._pct(notes_created, goal.target_value),
        }

    async def _progress_explore(self, goal: LearningGoalModel) -> dict[str, Any]:
        sessions = await self._completed_sessions(goal.id, "explore")
        sessions_completed = len(sessions)
        turns = 0
        for sess in sessions:
            window_start = (
                _as_utc(sess.started_at) if sess.started_at is not None else None
            )
            window_end = (
                _as_utc(sess.completed_at) if sess.completed_at is not None else None
            )
            if window_start is None or window_end is None:
                continue
            cnt = (
                await self._session.execute(
                    select(func.count(QAHistoryModel.id)).where(
                        QAHistoryModel.created_at >= window_start,
                        QAHistoryModel.created_at <= window_end,
                    )
                )
            ).scalar_one()
            turns += int(cnt)
        return {
            "turns": turns,
            "sessions_completed": sessions_completed,
            "completed_pct": self._pct(turns, goal.target_value),
        }


def get_learning_goals_service(session: AsyncSession) -> LearningGoalsService:
    return LearningGoalsService(session)
