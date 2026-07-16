"""drop orphan tables from removed features

Five tables survived the removal of the features that created them. No application
code reads any of them (models.py never declared them, so autogenerate cannot see
them either -- hence the hand-written DROPs).

  curricula, curriculum_nodes  the abandoned Universe/curriculum experiment
  glossary_terms               derived from documents; regenerable
  assessment_events            one row from a removed assessment feature; live
                               calibration uses review_events.predicted_rating
  note_collections             13 collections orphaned in April when the rename to
                               `collections` failed silently inside a try/except:
                               pass. The app reads `collections`, so these have been
                               invisible ever since, along with the 16
                               collection_members rows pointing at them. Those links
                               go too -- leaving them would be 16 rows referencing a
                               table that no longer exists.

Destructive and one-way: downgrade() restores the shapes, never the rows. Taken with
user sign-off against a VACUUM INTO snapshot of the live database.

Revision ID: cc1bfee0cb5b
Revises: 938e28777f4a
Create Date: 2026-07-15 19:47:09.691894

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'cc1bfee0cb5b'
down_revision: Union[str, Sequence[str], None] = '938e28777f4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ORPHAN_TABLES = (
    "curriculum_nodes",  # before curricula: FK child first
    "curricula",
    "glossary_terms",
    "assessment_events",
    "note_collections",
)


def upgrade() -> None:
    # A fresh database never had these tables -- it goes straight from the baseline to
    # head -- so every statement here must tolerate their absence, not just the DROPs.
    if sa.inspect(op.get_bind()).has_table("note_collections"):
        # Delete the dangling links BEFORE the table they point at.
        op.execute(
            """
            DELETE FROM collection_members
            WHERE collection_id IN (SELECT id FROM note_collections)
            """
        )
    for table in _ORPHAN_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")


def downgrade() -> None:
    # Shapes only -- the rows are gone. Restore from the backup taken alongside this
    # revision if you need the data.
    op.create_table(
        "curricula",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("target_date", sa.DateTime(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "curriculum_nodes",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("curriculum_id", sa.String(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
    )
    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("term", sa.String(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("first_mention_section_id", sa.String(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "assessment_events",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("concept_id", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("predicted_confidence", sa.Float(), nullable=True),
        sa.Column("calibration_delta", sa.Float(), nullable=True),
        sa.Column("mastery_before", sa.Float(), nullable=False),
        sa.Column("mastery_after", sa.Float(), nullable=False),
        sa.Column("covered_json", sa.JSON(), nullable=True),
        sa.Column("missing_json", sa.JSON(), nullable=True),
        sa.Column("misconceptions_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "note_collections",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=20), nullable=False),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("parent_collection_id", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("auto_document_id", sa.String(), nullable=True),
    )
