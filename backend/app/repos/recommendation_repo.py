"""The signals the recommender ranks: due cards, weak concepts, open misconceptions,
overconfidence and stalled reading, plus what the learner did with past suggestions."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RecommendationFeedbackModel


class RecommendationRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def due_cards(self) -> Row | None:
        """(count, oldest due date, newest due date) of cards due now."""
        return (
            await self.session.execute(
                text(
                    "SELECT COUNT(*), MIN(due_date), MAX(due_date) FROM flashcards "
                    "WHERE due_date IS NOT NULL AND due_date <= datetime('now')"
                )
            )
        ).first()

    async def weak_concepts(
        self, days: int, mastery_floor: float, min_bad: int, limit: int
    ) -> list[Row]:
        """(slug, label, mastery, again/hard reviews, last such review) of struggling concepts."""
        return list(
            (
                await self.session.execute(
                    text(
                        """
                        SELECT c.slug, c.label, c.mastery,
                               COUNT(re.id) AS bad_count, MAX(re.reviewed_at) AS last_bad
                        FROM concepts c
                        JOIN flashcards f ON f.concept_slug = c.slug
                        JOIN review_events re ON re.flashcard_id = f.id
                        WHERE re.rating IN ('again', 'hard')
                          AND re.reviewed_at >= datetime('now', :cutoff)
                          AND c.mastery < :floor
                          AND c.kind = 'concept'
                          AND c.status != 'candidate'
                        GROUP BY c.slug, c.label, c.mastery
                        HAVING COUNT(re.id) >= :min_bad
                        ORDER BY COUNT(re.id) * (1.0 - c.mastery) DESC
                        LIMIT :lim
                        """
                    ),
                    {
                        "cutoff": f"-{days} days",
                        "floor": mastery_floor,
                        "min_bad": min_bad,
                        "lim": limit,
                    },
                )
            ).all()
        )

    async def open_misconceptions(self, limit: int) -> list[Row]:
        """(card id, error type, note, detected at, concept slug, document id, question,
        concept label), newest first."""
        return list(
            (
                await self.session.execute(
                    text(
                        """
                        SELECT m.flashcard_id, m.error_type, m.correction_note, m.detected_at,
                               f.concept_slug, f.document_id, f.question, c.label
                        FROM misconceptions m
                        JOIN flashcards f ON f.id = m.flashcard_id
                        LEFT JOIN concepts c ON c.slug = f.concept_slug
                        WHERE m.status = 'open'
                        ORDER BY m.detected_at DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).all()
        )

    async def overconfident_concepts(self, days: int, min_over: int, limit: int) -> list[Row]:
        """(slug, label, reviews predicted good/easy but rated again, last such review)."""
        return list(
            (
                await self.session.execute(
                    text(
                        """
                        SELECT f.concept_slug, c.label, COUNT(*) AS n, MAX(re.reviewed_at)
                        FROM review_events re
                        JOIN flashcards f ON f.id = re.flashcard_id
                        JOIN concepts c ON c.slug = f.concept_slug
                        WHERE re.predicted_rating IN ('good', 'easy')
                          AND re.rating = 'again'
                          AND re.reviewed_at >= datetime('now', :cutoff)
                        GROUP BY f.concept_slug, c.label
                        HAVING COUNT(*) >= :min_over
                        ORDER BY COUNT(*) DESC
                        LIMIT :lim
                        """
                    ),
                    {"cutoff": f"-{days} days", "min_over": min_over, "lim": limit},
                )
            ).all()
        )

    async def stalled_documents(self, min_days: int, max_days: int, limit: int) -> list[Row]:
        """(id, title, last meaningful activity, sections, sections read) of documents left
        between `min_days` and `max_days` ago, most recent first."""
        return list(
            (
                await self.session.execute(
                    text(
                        """
                        SELECT d.id, d.title, ca.last_meaningful_at,
                          (SELECT COUNT(*) FROM sections WHERE document_id = d.id) AS total,
                          (SELECT COUNT(*) FROM reading_progress WHERE document_id = d.id)
                            AS read
                        FROM content_activity ca
                        JOIN documents d ON d.id = ca.member_id
                        WHERE ca.member_type = 'document'
                          AND ca.last_meaningful_at <= datetime('now', :min_days)
                          AND ca.last_meaningful_at >= datetime('now', :max_days)
                        ORDER BY ca.last_meaningful_at DESC
                        LIMIT :lim
                        """
                    ),
                    {
                        "min_days": f"-{min_days} days",
                        "max_days": f"-{max_days} days",
                        "lim": limit,
                    },
                )
            ).all()
        )

    async def feedback(self) -> list[RecommendationFeedbackModel]:
        return list(
            (await self.session.execute(select(RecommendationFeedbackModel))).scalars().all()
        )
