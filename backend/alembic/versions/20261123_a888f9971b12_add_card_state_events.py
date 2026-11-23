"""add card state events

Revision ID: a888f9971b12
Revises: bd9cb257888e
Create Date: 2026-11-23

A card's schedule becomes an append-only log (#453). Every existing card gets one `baseline`
row holding its schedule as it stands; nothing is replayed, so no due date moves.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a888f9971b12"
down_revision: str | Sequence[str] | None = "bd9cb257888e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out, not imported: a revision is a record of what it did then.
_COLUMNS = (
    "flashcard_id, kind, state, step, stability, difficulty, due_date, last_review, reps, lapses"
)
_SNAPSHOT = (
    "NEW.fsrs_state, NEW.fsrs_step, NEW.fsrs_stability, NEW.fsrs_difficulty, "
    "NEW.due_date, NEW.last_review, NEW.reps, NEW.lapses"
)
_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS card_state_created AFTER INSERT ON flashcards "
    f"BEGIN INSERT INTO card_state_events ({_COLUMNS}) VALUES (NEW.id, 'created', {_SNAPSHOT}); END",
    "CREATE TRIGGER IF NOT EXISTS card_state_changed "
    "AFTER UPDATE OF fsrs_state, fsrs_step, fsrs_stability, fsrs_difficulty, due_date "
    "ON flashcards WHEN NEW.last_review IS OLD.last_review "
    f"BEGIN INSERT INTO card_state_events ({_COLUMNS}) VALUES (NEW.id, 'state', {_SNAPSHOT}); END",
]


def upgrade() -> None:
    # db_init's legacy bridge builds pre-Alembic databases from the live models.
    if not sa.inspect(op.get_bind()).has_table("card_state_events"):
        op.create_table(
            "card_state_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("flashcard_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("rating", sa.String(length=8), nullable=True),
            sa.Column("state", sa.String(), nullable=True),
            sa.Column("step", sa.Integer(), nullable=True),
            sa.Column("stability", sa.Float(), nullable=True),
            sa.Column("difficulty", sa.Float(), nullable=True),
            sa.Column("due_date", sa.DateTime(), nullable=True),
            sa.Column("last_review", sa.DateTime(), nullable=True),
            sa.Column("reps", sa.Integer(), nullable=True),
            sa.Column("lapses", sa.Integer(), nullable=True),
            sa.Column("device_id", sa.String(), nullable=True),
            sa.Column("client_seq", sa.Integer(), nullable=True),
            sa.Column(
                "at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
            ),
            sa.PrimaryKeyConstraint("id"),
            sqlite_autoincrement=True,
        )
        op.create_index(
            "idx_card_state_events_card", "card_state_events", ["flashcard_id", "id"], unique=False
        )
    op.execute(
        f"INSERT INTO card_state_events ({_COLUMNS}) "
        "SELECT id, 'baseline', fsrs_state, fsrs_step, fsrs_stability, fsrs_difficulty, "
        "due_date, last_review, reps, lapses FROM flashcards "
        "WHERE id NOT IN (SELECT flashcard_id FROM card_state_events) ORDER BY created_at, id"
    )
    for ddl in _TRIGGERS:
        op.execute(ddl)


def downgrade() -> None:
    for name in ("card_state_created", "card_state_changed"):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("idx_card_state_events_card", table_name="card_state_events")
    op.drop_table("card_state_events")
