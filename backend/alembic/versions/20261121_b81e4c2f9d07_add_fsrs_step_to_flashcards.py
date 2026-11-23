"""add fsrs_step to flashcards

Revision ID: b81e4c2f9d07
Revises: 5c0d3e9a71b2
Create Date: 2026-11-21 18:00:00.000000

Before this, every review rebuilt the card at learning step 0 (#533), so the step a card is
at follows from its last review alone: a learning card whose last review was Good is at
step 1; any other learning or relearning card is at step 0. The last review is known only
when the card's newest review event was written with it (within 5 s of
`last_review`); review events exist only for reviews made in a study session. Every other
card gets NULL, which fsrs uses outside learning. No due date changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b81e4c2f9d07"
down_revision: str | Sequence[str] | None = "5c0d3e9a71b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    # db_init's legacy bridge builds pre-Alembic databases from the live models.
    if not _has_column("flashcards", "fsrs_step"):
        op.add_column("flashcards", sa.Column("fsrs_step", sa.Integer(), nullable=True))
    # The event a review writes lands ~40 ms after `last_review` in the same request; 5 s
    # stays under fsrs's shortest learning step (1 min), which a wider window could straddle.
    op.execute(
        """
        WITH last_event AS (
            SELECT flashcard_id, rating, reviewed_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY flashcard_id ORDER BY reviewed_at DESC
                   ) AS newest
            FROM review_events
        )
        UPDATE flashcards
        SET fsrs_step = CASE
            WHEN fsrs_state = 'learning' AND EXISTS (
                SELECT 1 FROM last_event e
                WHERE e.flashcard_id = flashcards.id
                  AND e.newest = 1
                  AND e.rating = 'good'
                  AND flashcards.last_review IS NOT NULL
                  AND ABS(julianday(e.reviewed_at) - julianday(flashcards.last_review)) * 86400
                      <= 5
            ) THEN 1
            ELSE 0
        END
        WHERE fsrs_state IN ('learning', 'relearning')
        """
    )


def downgrade() -> None:
    if _has_column("flashcards", "fsrs_step"):
        # In place, never batch mode: rebuilding flashcards would cascade (I-69).
        op.execute("ALTER TABLE flashcards DROP COLUMN fsrs_step")
