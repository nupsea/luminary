"""ProgressService -- the numbers the Progress page renders, with their provenance.

Every metric returns a `Metric`, and a metric that cannot be computed returns
`value=None` rather than zero. The distinction is the whole point: "you have
reviewed nothing" and "retention is 0%" are opposite statements, and the page used
to print the second when it meant the first.

Where a formula already exists in this codebase, it is reused rather than
re-derived. Mastery is `MasteryService._compute_weighted_mastery` -- the same
function the assessment pipeline writes to `concepts.mastery` (I-19) -- so the
library headline and the per-concept numbers cannot disagree by construction.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DocumentModel,
    FlashcardModel,
    NoteModel,
    ReviewEventModel,
    TimeOnTaskModel,
)
from app.schemas.progress import (
    Metric,
    NotesTimelinePoint,
    NotesTimelineResponse,
    ProgressSummaryResponse,
)
from app.services.engagement_service import EngagementService
from app.services.mastery_service import get_mastery_service
from app.services.misconceptions import get_stats as get_misconception_stats
from app.services.time_on_task_service import TimeOnTaskService

logger = logging.getLogger(__name__)

_RETENTION_WINDOW_DAYS = 30

# Below this many graded reviews, a retention percentage is noise dressed as a
# measurement. Bracketing cases: at 5 reviews one lapse swings the number 20
# points, which is why the old page could read 90% off a single session; at 20 a
# single lapse moves it 5, which is a signal a learner can act on.
_MIN_REVIEWS_FOR_RETENTION = 20

# Below this many *reviewed* cards, FSRS stability has not had enough evidence to
# describe a library. Bracketing cases: one card at 30 days' stability is not a
# mastered library; ten reviewed cards is the smallest set where the weighted mean
# stops tracking a single card.
_MIN_CARDS_FOR_MASTERY = 10

# FSRS stability, in days, at which a card counts as mature. This is
# `mastery_service._MASTERY_FULL_DAYS` -- the same bar the concept-level formula
# caps at, kept identical so "mature" and "mastery 1.0" mean the same thing.
# Bracketing cases: a card answered correctly once sits at ~2-4 days and is not
# mature; a card at 21 days is one that survives a three-week gap.
_MATURE_STABILITY_DAYS = 21.0

# Window for the two activity metrics below. Shorter than the 30-day retention
# window on purpose: "am I showing up" is a question about now, and a 30-day
# count hides a fortnight away behind a busy fortnight before it.
_ACTIVITY_WINDOW_DAYS = 7


def _absent(unit: str, definition: str, basis: str, sample_size: int = 0) -> Metric:
    """A metric that could not be computed. Never a zero standing in for one."""
    return Metric(
        value=None, unit=unit, sample_size=sample_size, definition=definition, basis=basis
    )


class ProgressService:
    def __init__(self, session: AsyncSession, tz_offset_minutes: int = 0) -> None:
        self._session = session
        self._tz_offset_minutes = tz_offset_minutes

    def _naive_cutoff(self, days: int) -> datetime:
        """Window start as a tz-naive UTC datetime.

        aiosqlite hands back DateTime columns tz-naive regardless of how they were
        written, so a tz-aware cutoff compares wrong (see docs/patterns.md).
        """
        return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)

    async def _scalar(self, stmt) -> int:
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    # -- individual metrics --------------------------------------------------

    async def _retention(self) -> Metric:
        definition = (
            f"Share of your flashcard answers graded correct in the last "
            f"{_RETENTION_WINDOW_DAYS} days."
        )
        cutoff = self._naive_cutoff(_RETENTION_WINDOW_DAYS)
        row = (
            await self._session.execute(
                select(
                    func.count(ReviewEventModel.id),
                    func.sum(func.cast(ReviewEventModel.is_correct, Integer)),
                ).where(ReviewEventModel.reviewed_at >= cutoff)
            )
        ).one()
        total = int(row[0] or 0)
        correct = int(row[1] or 0)
        if total < _MIN_REVIEWS_FOR_RETENTION:
            return _absent(
                "percent",
                definition,
                f"Needs {_MIN_REVIEWS_FOR_RETENTION} reviews in the last "
                f"{_RETENTION_WINDOW_DAYS} days; you have {total}.",
                sample_size=total,
            )
        return Metric(
            value=round(correct / total * 100.0, 1),
            unit="percent",
            sample_size=total,
            definition=definition,
            basis=f"{correct} correct of {total} reviews, last {_RETENTION_WINDOW_DAYS} days.",
        )

    async def _mastery(self) -> Metric:
        definition = (
            "How well your reviewed cards are retained, from each card's FSRS "
            f"stability capped at {_MATURE_STABILITY_DAYS:.0f} days and weighted "
            "toward cards that ask you to analyse rather than recall."
        )
        # reps > 0 is load-bearing: a generated-but-never-reviewed card has
        # stability 0.0, so counting new cards would turn this into "share of my
        # library I have got round to", which is not mastery.
        cards = list(
            (
                await self._session.execute(
                    select(FlashcardModel).where(FlashcardModel.reps > 0)
                )
            )
            .scalars()
            .all()
        )
        if len(cards) < _MIN_CARDS_FOR_MASTERY:
            return _absent(
                "percent",
                definition,
                f"Needs {_MIN_CARDS_FOR_MASTERY} reviewed cards; you have {len(cards)}.",
                sample_size=len(cards),
            )
        # No prediction-error penalty here. The concept-level formula subtracts one,
        # but it is capped at 0.20 and counts errors within a single concept -- applied
        # across a whole library any four errors would max it out, so it would say more
        # about library size than about the learner.
        weighted = get_mastery_service()._compute_weighted_mastery(cards)
        return Metric(
            value=round(weighted * 100.0, 1),
            unit="percent",
            sample_size=len(cards),
            definition=definition,
            basis=f"Across {len(cards)} cards you have reviewed at least once.",
        )

    async def _mature_cards(self) -> Metric:
        definition = (
            f"Cards whose FSRS stability has reached {_MATURE_STABILITY_DAYS:.0f} days "
            "-- ones you would still be likely to recall after three weeks away."
        )
        reviewed = await self._scalar(
            select(func.count()).select_from(FlashcardModel).where(FlashcardModel.reps > 0)
        )
        mature = await self._scalar(
            select(func.count())
            .select_from(FlashcardModel)
            .where(
                FlashcardModel.fsrs_state == "review",
                FlashcardModel.fsrs_stability >= _MATURE_STABILITY_DAYS,
            )
        )
        # Zero is a real answer here, not a missing one: it means no card has got
        # there yet. Only report it once there is something to have got there from.
        if reviewed == 0:
            return _absent(
                "count", definition, "No cards reviewed yet.", sample_size=0
            )
        return Metric(
            value=float(mature),
            unit="count",
            sample_size=reviewed,
            definition=definition,
            basis=f"{mature} of {reviewed} reviewed cards.",
        )

    async def _due_today(self) -> Metric:
        now = datetime.now(UTC).replace(tzinfo=None)
        due = await self._scalar(
            select(func.count())
            .select_from(FlashcardModel)
            .where(FlashcardModel.due_date <= now)
        )
        total = await self._scalar(select(func.count()).select_from(FlashcardModel))
        return Metric(
            value=float(due),
            unit="count",
            sample_size=total,
            definition="Cards whose next review date has arrived or passed.",
            basis=f"{due} due of {total} cards in your library.",
        )

    async def _streaks(self) -> tuple[Metric, Metric]:
        # One source of truth. The page used to recompute a streak in the browser
        # from a 30-day window, which read 0 whenever the user had not studied yet
        # today -- while the stored streak on the same page said otherwise.
        streak = await EngagementService(
            self._session, tz_offset_minutes=self._tz_offset_minutes
        ).get_streak()
        current = int(streak.get("current_streak") or 0)
        longest = int(streak.get("longest_streak") or 0)
        studied_today = bool(streak.get("studied_today"))
        return (
            Metric(
                value=float(current),
                unit="days",
                sample_size=current,
                definition="Consecutive days you have studied, counting today only once you have.",
                basis=(
                    "Includes today." if studied_today else "Today is not counted yet."
                ),
            ),
            Metric(
                value=float(longest),
                unit="days",
                sample_size=longest,
                definition="Your longest run of consecutive study days.",
                basis=f"Best run so far: {longest} day{'' if longest == 1 else 's'}.",
            ),
        )

    async def _reviews_30d(self) -> Metric:
        cutoff = self._naive_cutoff(_RETENTION_WINDOW_DAYS)
        count = await self._scalar(
            select(func.count())
            .select_from(ReviewEventModel)
            .where(ReviewEventModel.reviewed_at >= cutoff)
        )
        return Metric(
            value=float(count),
            unit="count",
            sample_size=count,
            definition=f"Flashcard answers you graded in the last {_RETENTION_WINDOW_DAYS} days.",
            basis=f"Counted from your review history, last {_RETENTION_WINDOW_DAYS} days.",
        )

    async def _gaps_closed(self) -> Metric:
        stats = await get_misconception_stats(self._session)
        resolved = int(stats.get("resolved_count") or 0)
        open_count = int(stats.get("open_count") or 0)
        return Metric(
            value=float(resolved),
            unit="count",
            sample_size=resolved + open_count,
            definition=(
                "Misconceptions the system caught and you later answered correctly. "
                "Resolved by a passing review, never by a model's opinion."
            ),
            basis=f"{resolved} resolved, {open_count} still open.",
        )

    async def _time_on_luminary(self) -> Metric:
        """Minutes with a Luminary surface open and visible.

        Named for what it measures rather than what a reader would like it to
        mean. It is not time studied and not attention: the client samples every
        15s while the tab is visible, and a gap too long to be continuous is
        credited as nothing. See `docs/metrics.md`.
        """
        totals = await TimeOnTaskService(self._session).seconds_by_activity(
            days=_ACTIVITY_WINDOW_DAYS
        )
        seconds = sum(totals.values())
        definition = (
            f"Minutes with a Luminary surface open and visible, last "
            f"{_ACTIVITY_WINDOW_DAYS} days. Not a measure of attention."
        )
        if seconds == 0:
            return _absent(
                "minutes",
                definition,
                "Nothing recorded yet — this fills in as you read, write and review.",
            )
        # Under a minute, minutes round to zero -- which on screen is
        # indistinguishable from nothing recorded, the one confusion this whole
        # contract exists to prevent. The value stays truthful to its unit and
        # the basis carries the seconds, so the reader can tell the two apart.
        def _amount(value: int) -> str:
            return f"{value}s" if seconds < 60 else f"{round(value / 60)}m"

        split = ", ".join(
            f"{name} {_amount(value)}" for name, value in sorted(totals.items()) if value
        )
        return Metric(
            value=float(round(seconds / 60)),
            unit="minutes",
            sample_size=seconds,
            definition=definition,
            basis=f"Sampled every 15s while visible: {split}.",
        )

    async def _active_days(self) -> Metric:
        """Days you turned up, counted from things that actually happened.

        Deliberately not an "efficiency" or "focus" score. Both would divide by
        the time above, whose denominator measures a surface being open rather
        than work being done, and a ratio built on that reports a precision it
        never had. A day is active if it carries a graded review or a recorded
        interval — two direct observations, no interpolation.
        """
        cutoff = self._naive_cutoff(_ACTIVITY_WINDOW_DAYS)
        review_days = await self._session.execute(
            select(self._local_date_sql(ReviewEventModel.reviewed_at)).where(
                ReviewEventModel.reviewed_at >= cutoff
            )
        )
        task_days = await self._session.execute(
            select(self._local_date_sql(TimeOnTaskModel.started_at)).where(
                TimeOnTaskModel.started_at >= cutoff
            )
        )
        days = {d for (d,) in review_days if d} | {d for (d,) in task_days if d}
        return Metric(
            value=float(len(days)),
            unit="days",
            sample_size=_ACTIVITY_WINDOW_DAYS,
            definition=(
                f"Days in the last {_ACTIVITY_WINDOW_DAYS} with a graded review or "
                "recorded time."
            ),
            basis=f"{len(days)} of the last {_ACTIVITY_WINDOW_DAYS} days.",
        )

    async def _documents(self) -> Metric:
        count = await self._scalar(select(func.count()).select_from(DocumentModel))
        return Metric(
            value=float(count),
            unit="count",
            sample_size=count,
            definition="Documents in your library.",
            basis="Counted from your library.",
        )

    async def _notes(self) -> Metric:
        count = await self._scalar(
            select(func.count()).select_from(NoteModel).where(NoteModel.archived.is_(False))
        )
        return Metric(
            value=float(count),
            unit="count",
            sample_size=count,
            definition="Notes you have written, excluding archived ones.",
            basis="Counted from your notes.",
        )

    # -- public API ----------------------------------------------------------

    async def summary(self) -> ProgressSummaryResponse:
        current_streak, longest_streak = await self._streaks()
        return ProgressSummaryResponse(
            retention_30d=await self._retention(),
            mastery=await self._mastery(),
            mature_cards=await self._mature_cards(),
            due_today=await self._due_today(),
            current_streak=current_streak,
            longest_streak=longest_streak,
            reviews_30d=await self._reviews_30d(),
            gaps_closed=await self._gaps_closed(),
            time_on_luminary=await self._time_on_luminary(),
            active_days=await self._active_days(),
            documents=await self._documents(),
            notes=await self._notes(),
        )

    async def notes_timeline(self, months: int = 12) -> NotesTimelineResponse:
        """Notes per local month, grouped in SQL rather than in the browser."""
        month_expr = self._local_month_sql(NoteModel.created_at)
        rows = (
            await self._session.execute(
                select(month_expr.label("month"), func.count().label("count"))
                .where(NoteModel.archived.is_(False))
                .group_by(month_expr)
                .order_by(month_expr)
            )
        ).all()
        points = [NotesTimelinePoint(month=str(r.month), count=int(r.count)) for r in rows]
        total = sum(p.count for p in points)
        return NotesTimelineResponse(points=points[-months:], total_notes=total)

    def _local_date_sql(self, column):
        """SQL expression: a UTC datetime column as the user's local date.

        Same shift EngagementService applies, so a session at 11pm counts on the
        day the user had it rather than rolling into tomorrow.
        """
        if self._tz_offset_minutes == 0:
            return func.date(column)
        modifier = f"{-self._tz_offset_minutes:+d} minutes"
        return func.date(func.datetime(column, modifier))

    def _local_month_sql(self, column):
        """SQL expression: a UTC datetime column as the user's local YYYY-MM."""
        if self._tz_offset_minutes == 0:
            return func.strftime("%Y-%m", column)
        modifier = f"{-self._tz_offset_minutes:+d} minutes"
        return func.strftime("%Y-%m", func.datetime(column, modifier))
