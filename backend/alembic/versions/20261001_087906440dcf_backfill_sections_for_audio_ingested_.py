"""backfill sections for audio ingested before 0.7.5

Revision ID: 087906440dcf
Revises: 45c26ee949d4
Create Date: 2026-10-01 22:25:54.757934

Audio and video ingested before 0.7.5 got chunks and no sections, so the reader
showed "No content available" for a transcript it could retrieve from (#97).
`chunk_node` now writes one section per transcript window, with the window's
text as its body and no heading (I-30). Audio chunks have always been those same
windows -- whole Whisper segments grouped into ~60 s, never overlapping or cut
mid-sentence (`_chunk_audio`, unchanged since audio ingest landed) -- so one
section per stored chunk is what a re-ingest would write, not prose stitched
from overlapping retrieval chunks (I-29).

Data only, guarded on the data: a document that has any section is skipped, so a
replay finishes a partial run and never doubles one.

"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "087906440dcf"
down_revision: str | Sequence[str] | None = "45c26ee949d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# chunk.py's PREVIEW_CHARS, inlined so this revision keeps its meaning if that moves.
_PREVIEW_CHARS = 10000


def upgrade() -> None:
    bind = op.get_bind()
    documents = bind.execute(
        sa.text(
            "SELECT d.id FROM documents d "
            "WHERE d.content_type IN ('audio', 'video') "
            "  AND NOT EXISTS (SELECT 1 FROM sections s WHERE s.document_id = d.id) "
            "  AND EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.id)"
        )
    ).scalars().all()
    for document_id in documents:
        chunks = bind.execute(
            sa.text(
                "SELECT id, text FROM chunks WHERE document_id = :d ORDER BY chunk_index"
            ),
            {"d": document_id},
        ).all()
        for order, (chunk_id, text) in enumerate(chunks):
            section_id = str(uuid.uuid4())
            body = text or ""
            bind.execute(
                sa.text(
                    "INSERT INTO sections (id, document_id, heading, level, page_start, "
                    "page_end, section_order, preview, body) "
                    "VALUES (:id, :d, '', 1, 0, 0, :o, :preview, :body)"
                ),
                {
                    "id": section_id,
                    "d": document_id,
                    "o": order,
                    "preview": body[:_PREVIEW_CHARS],
                    "body": body,
                },
            )
            bind.execute(
                sa.text("UPDATE chunks SET section_id = :s WHERE id = :c"),
                {"s": section_id, "c": chunk_id},
            )


def downgrade() -> None:
    """No-op: the sections are what a re-ingest writes, and nothing marks which this added."""
