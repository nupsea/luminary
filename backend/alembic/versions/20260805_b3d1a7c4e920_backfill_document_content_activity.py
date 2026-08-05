"""backfill content_activity for already-ingested documents

Revision ID: b3d1a7c4e920
Revises: 41b18d4c6987
Create Date: 2026-08-05 13:10:00.000000

Ingestion never wrote a content_activity row, and that table is the only source
for the hub's recent, continue-reading and fading feeds. Libraries built before
the fix therefore render an empty hub until each document is opened. Their
created_at is the honest timestamp for when the user added them.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3d1a7c4e920'
down_revision: Union[str, Sequence[str], None] = '41b18d4c6987'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Data only -- no schema change."""
    op.execute(
        """
        INSERT INTO content_activity (member_type, member_id, last_meaningful_at)
        SELECT 'document', d.id, d.created_at
        FROM documents d
        WHERE d.stage = 'complete'
        ON CONFLICT(member_type, member_id) DO NOTHING
        """
    )


def downgrade() -> None:
    """Deliberately empty: these rows are indistinguishable from real activity."""
