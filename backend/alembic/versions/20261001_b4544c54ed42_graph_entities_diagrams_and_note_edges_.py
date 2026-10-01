"""graph entities diagrams and note edges in sqlite

Revision ID: b4544c54ed42
Revises: b6d91c364d48
Create Date: 2026-10-01 14:24:24.407044

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4544c54ed42"
down_revision: str | Sequence[str] | None = "b6d91c364d48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    # The legacy bridge builds pre-Alembic databases from the live models before stamping
    # the baseline, so on that path these tables already exist (see cae3aba739eb).
    if not _has_table("graph_diagram_nodes"):
        op.create_table(
            "graph_diagram_nodes",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("document_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("node_type", sa.String(), nullable=False),
            sa.Column("source_image_id", sa.String(), nullable=False),
            sa.Column("frequency", sa.Integer(), nullable=False),
            sa.Column("library_id", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("graph_diagram_nodes", schema=None) as batch_op:
            batch_op.create_index(
                "ix_graph_diagram_nodes_document_type", ["document_id", "node_type"], unique=False
            )
    if not _has_table("graph_entities"):
        op.create_table(
            "graph_entities",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("document_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("frequency", sa.Integer(), nullable=False),
            sa.Column("mention_count", sa.Integer(), nullable=False),
            sa.Column("aliases", sqlite.JSON(), nullable=False),
            sa.Column("library_id", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("graph_entities", schema=None) as batch_op:
            batch_op.create_index(
                "ix_graph_entities_document_type", ["document_id", "type"], unique=False
            )
            batch_op.create_index("ix_graph_entities_name", ["name"], unique=False)
    if not _has_table("graph_diagram_depictions"):
        op.create_table(
            "graph_diagram_depictions",
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("entity_id", sa.String(), nullable=False),
            sa.Column("document_id", sa.String(), nullable=False),
            sa.Column("library_id", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["node_id"], ["graph_diagram_nodes.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("node_id", "entity_id"),
        )
        with op.batch_alter_table("graph_diagram_depictions", schema=None) as batch_op:
            batch_op.create_index("ix_graph_diagram_depictions_entity", ["entity_id"], unique=False)
    if not _has_table("graph_diagram_edges"):
        op.create_table(
            "graph_diagram_edges",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=False),
            sa.Column("document_id", sa.String(), nullable=False),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("library_id", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_id"], ["graph_diagram_nodes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["target_id"], ["graph_diagram_nodes.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("kind", "source_id", "target_id", name="uq_graph_diagram_edge"),
        )
        with op.batch_alter_table("graph_diagram_edges", schema=None) as batch_op:
            batch_op.create_index("ix_graph_diagram_edges_document", ["document_id"], unique=False)
    if not _has_table("graph_entity_edges"):
        op.create_table(
            "graph_entity_edges",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=False),
            sa.Column("document_id", sa.String(), nullable=False),
            sa.Column("weight", sa.Float(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("source_section_id", sa.String(), nullable=True),
            sa.Column("label", sa.String(), nullable=True),
            sa.Column("library_id", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_id"], ["graph_entities.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["target_id"], ["graph_entities.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("kind", "source_id", "target_id", name="uq_graph_entity_edge"),
        )
        with op.batch_alter_table("graph_entity_edges", schema=None) as batch_op:
            batch_op.create_index(
                "ix_graph_entity_edges_document", ["document_id", "kind"], unique=False
            )
            batch_op.create_index(
                "ix_graph_entity_edges_source", ["source_id", "kind"], unique=False
            )
            batch_op.create_index(
                "ix_graph_entity_edges_target", ["target_id", "kind"], unique=False
            )
    if not _has_table("graph_entity_links"):
        op.create_table(
            "graph_entity_links",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("source_id", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=False),
            sa.Column("source_document_id", sa.String(), nullable=False),
            sa.Column("target_document_id", sa.String(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("contradiction", sa.Boolean(), nullable=False),
            sa.Column("contradiction_note", sa.Text(), nullable=False),
            sa.Column("prefer_source", sa.String(), nullable=False),
            sa.Column("library_id", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["source_id"], ["graph_entities.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["target_id"], ["graph_entities.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_id", "target_id", name="uq_graph_entity_link"),
        )
        with op.batch_alter_table("graph_entity_links", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_graph_entity_links_source_document_id"),
                ["source_document_id"],
                unique=False,
            )
            batch_op.create_index("ix_graph_entity_links_target", ["target_id"], unique=False)
            batch_op.create_index(
                batch_op.f("ix_graph_entity_links_target_document_id"),
                ["target_document_id"],
                unique=False,
            )
    if not _has_table("graph_note_entities"):
        op.create_table(
            "graph_note_entities",
            sa.Column("note_id", sa.String(), nullable=False),
            sa.Column("entity_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("tag", sa.String(), nullable=True),
            sa.Column("library_id", sa.String(), nullable=True),
            sa.CheckConstraint(
                "kind IN ('written_about', 'tag')", name="ck_graph_note_entity_kind"
            ),
            sa.ForeignKeyConstraint(["entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("note_id", "entity_id", "kind"),
        )
        with op.batch_alter_table("graph_note_entities", schema=None) as batch_op:
            batch_op.create_index("ix_graph_note_entities_entity", ["entity_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("graph_note_entities", schema=None) as batch_op:
        batch_op.drop_index("ix_graph_note_entities_entity")

    op.drop_table("graph_note_entities")
    with op.batch_alter_table("graph_entity_links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_graph_entity_links_target_document_id"))
        batch_op.drop_index("ix_graph_entity_links_target")
        batch_op.drop_index(batch_op.f("ix_graph_entity_links_source_document_id"))

    op.drop_table("graph_entity_links")
    with op.batch_alter_table("graph_entity_edges", schema=None) as batch_op:
        batch_op.drop_index("ix_graph_entity_edges_target")
        batch_op.drop_index("ix_graph_entity_edges_source")
        batch_op.drop_index("ix_graph_entity_edges_document")

    op.drop_table("graph_entity_edges")
    with op.batch_alter_table("graph_diagram_edges", schema=None) as batch_op:
        batch_op.drop_index("ix_graph_diagram_edges_document")

    op.drop_table("graph_diagram_edges")
    with op.batch_alter_table("graph_diagram_depictions", schema=None) as batch_op:
        batch_op.drop_index("ix_graph_diagram_depictions_entity")

    op.drop_table("graph_diagram_depictions")
    with op.batch_alter_table("graph_entities", schema=None) as batch_op:
        batch_op.drop_index("ix_graph_entities_name")
        batch_op.drop_index("ix_graph_entities_document_type")

    op.drop_table("graph_entities")
    with op.batch_alter_table("graph_diagram_nodes", schema=None) as batch_op:
        batch_op.drop_index("ix_graph_diagram_nodes_document_type")

    op.drop_table("graph_diagram_nodes")
