"""add quiz tables

Revision ID: 9f257ad0a1b1
Revises: a888f9971b12
Create Date: 2026-11-26

Quizzes, their bank of items and options, the questions each quiz asks and the learner's answers.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f257ad0a1b1"
down_revision: str | Sequence[str] | None = "a888f9971b12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRAPS = (
    "'near_miss_detail', 'swapped_relation', 'overgeneralised', "
    "'wrong_condition', 'related_but_different', 'common_misconception'"
)


def _tables() -> list[tuple[str, list, list[tuple[str, list[str]]]]]:
    """(table, columns and constraints, indexes), in creation order."""
    return [
        (
            "quizzes",
            [
                sa.Column("id", sa.String(), nullable=False),
                sa.Column("document_id", sa.String(), nullable=False),
                sa.Column("scope_type", sa.String(), nullable=False),
                sa.Column("scope_ref", sa.String(), nullable=False),
                sa.Column("difficulty", sa.String(), nullable=False),
                sa.Column("mode", sa.String(), nullable=False),
                sa.Column("question_count", sa.Integer(), nullable=False),
                sa.Column("question_kinds", sa.String(), nullable=False),
                sa.Column("status", sa.String(), nullable=False),
                sa.Column("error", sa.Text(), nullable=True),
                sa.Column("session_id", sa.String(), nullable=True),
                sa.Column("retake_of", sa.String(), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=False),
                sa.Column("completed_at", sa.DateTime(), nullable=True),
                sa.CheckConstraint(
                    "difficulty IN ('easy', 'medium', 'hard', 'adaptive')",
                    name="ck_quizzes_difficulty",
                ),
                sa.CheckConstraint("mode IN ('practice', 'exam')", name="ck_quizzes_mode"),
                sa.CheckConstraint(
                    "question_kinds IN ('single', 'multi', 'mixed')",
                    name="ck_quizzes_question_kinds",
                ),
                sa.CheckConstraint(
                    "status IN ('building', 'ready', 'complete', 'error')",
                    name="ck_quizzes_status",
                ),
                sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
                sa.PrimaryKeyConstraint("id"),
            ],
            [("ix_quizzes_document_id", ["document_id"])],
        ),
        (
            "quiz_items",
            [
                sa.Column("id", sa.String(), nullable=False),
                sa.Column("document_id", sa.String(), nullable=False),
                sa.Column("section_id", sa.String(), nullable=True),
                sa.Column("kind", sa.String(), nullable=False),
                sa.Column("difficulty", sa.String(), nullable=False),
                sa.Column("stem", sa.Text(), nullable=False),
                sa.Column("source_chunk_ids", sqlite.JSON(), nullable=False),
                sa.Column("flashcard_id", sa.String(), nullable=True),
                sa.Column("model", sa.String(), nullable=True),
                sa.Column("origin", sa.String(), nullable=False),
                sa.Column("support_check", sa.String(), nullable=False),
                sa.Column("created_at", sa.DateTime(), nullable=False),
                sa.CheckConstraint(
                    "difficulty IN ('easy', 'medium', 'hard')", name="ck_quiz_items_difficulty"
                ),
                sa.CheckConstraint("kind IN ('single', 'multi')", name="ck_quiz_items_kind"),
                sa.CheckConstraint("origin IN ('model', 'cards')", name="ck_quiz_items_origin"),
                sa.CheckConstraint(
                    "support_check IN ('unchecked', 'supported', 'unsupported')",
                    name="ck_quiz_items_support_check",
                ),
                sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
                sa.ForeignKeyConstraint(["flashcard_id"], ["flashcards.id"], ondelete="SET NULL"),
                sa.PrimaryKeyConstraint("id"),
            ],
            [
                ("ix_quiz_items_flashcard_id", ["flashcard_id"]),
                ("ix_quiz_items_scope", ["document_id", "section_id"]),
            ],
        ),
        (
            "quiz_attempts",
            [
                sa.Column("id", sa.String(), nullable=False),
                sa.Column("quiz_id", sa.String(), nullable=False),
                sa.Column("position", sa.Integer(), nullable=False),
                sa.Column("item_id", sa.String(), nullable=False),
                sa.Column("selected_option_ids", sqlite.JSON(), nullable=False),
                sa.Column("confidence", sa.String(), nullable=True),
                sa.Column("outcome", sa.String(), nullable=False),
                sa.Column("score", sa.Float(), nullable=False),
                sa.Column("time_ms", sa.Integer(), nullable=True),
                sa.Column("answered_at", sa.DateTime(), nullable=False),
                sa.CheckConstraint(
                    "confidence IS NULL OR confidence IN ('sure', 'think', 'guess')",
                    name="ck_quiz_attempts_confidence",
                ),
                sa.CheckConstraint(
                    "outcome IN ('correct', 'partial', 'wrong')", name="ck_quiz_attempts_outcome"
                ),
                sa.ForeignKeyConstraint(["item_id"], ["quiz_items.id"], ondelete="CASCADE"),
                sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
                sa.PrimaryKeyConstraint("id"),
                sa.UniqueConstraint("quiz_id", "position", name="uq_quiz_attempts_question"),
            ],
            [("ix_quiz_attempts_item_id", ["item_id"])],
        ),
        (
            "quiz_options",
            [
                sa.Column("id", sa.String(), nullable=False),
                sa.Column("item_id", sa.String(), nullable=False),
                sa.Column("position", sa.Integer(), nullable=False),
                sa.Column("text", sa.Text(), nullable=False),
                sa.Column("is_correct", sa.Boolean(), nullable=False),
                sa.Column("explanation", sa.Text(), nullable=False),
                sa.Column("evidence_quote", sa.Text(), nullable=True),
                sa.Column("trap", sa.String(), nullable=True),
                sa.Column("key_similarity", sa.Float(), nullable=True),
                sa.CheckConstraint(
                    f"trap IS NULL OR trap IN ({_TRAPS})", name="ck_quiz_options_trap"
                ),
                sa.ForeignKeyConstraint(["item_id"], ["quiz_items.id"], ondelete="CASCADE"),
                sa.PrimaryKeyConstraint("id"),
            ],
            [("ix_quiz_options_item_id", ["item_id"])],
        ),
        (
            "quiz_questions",
            [
                sa.Column("quiz_id", sa.String(), nullable=False),
                sa.Column("position", sa.Integer(), nullable=False),
                sa.Column("item_id", sa.String(), nullable=False),
                sa.Column("option_order", sqlite.JSON(), nullable=False),
                sa.ForeignKeyConstraint(["item_id"], ["quiz_items.id"], ondelete="CASCADE"),
                sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
                sa.PrimaryKeyConstraint("quiz_id", "position"),
            ],
            [("ix_quiz_questions_item_id", ["item_id"])],
        ),
    ]


def upgrade() -> None:
    # db_init's legacy bridge builds pre-Alembic databases from the live models.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table, parts, indexes in _tables():
        if table in existing:
            continue
        op.create_table(table, *parts)
        for name, columns in indexes:
            op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for table, _parts, indexes in reversed(_tables()):
        for name, _columns in indexes:
            op.drop_index(name, table_name=table)
        op.drop_table(table)
