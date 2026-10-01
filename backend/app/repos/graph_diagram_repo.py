"""Nodes and arrows read from diagram images, and the entities those nodes depict."""

from __future__ import annotations

from sqlalchemy import exists, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DocumentModel,
    GraphDiagramDepictionModel,
    GraphDiagramEdgeModel,
    GraphDiagramNodeModel,
    GraphEntityModel,
)
from app.repos._helpers import upsert_insert

Node = GraphDiagramNodeModel
Edge = GraphDiagramEdgeModel
Depiction = GraphDiagramDepictionModel

DIAGRAM_EDGE_KINDS = (
    "CONNECTS_TO",
    "STORES_IN",
    "SENDS_TO",
    "HAS_FIELD",
    "REFERENCES_DM",
    "LEADS_TO",
)


class GraphDiagramRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_node(
        self, node_id: str, name: str, node_type: str, source_image_id: str, document_id: str
    ) -> None:
        """Add a node, or count one more sighting. Nothing is stored for a deleted document."""
        row = select(
            literal(node_id),
            literal(document_id),
            literal(name),
            literal(node_type),
            literal(source_image_id),
            literal(1),
        ).where(exists().where(DocumentModel.id == document_id))
        stmt = upsert_insert(self.session, Node).from_select(
            ["id", "document_id", "name", "node_type", "source_image_id", "frequency"], row
        )
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Node.id], set_={"frequency": Node.frequency + 1}
            )
        )

    async def add_edge(
        self, source_id: str, target_id: str, kind: str, document_id: str, label: str = ""
    ) -> None:
        """Add an arrow between two stored nodes; an existing arrow is left as it is."""
        row = select(
            literal(kind),
            literal(source_id),
            literal(target_id),
            literal(document_id),
            literal(label),
        ).where(exists().where(Node.id == source_id), exists().where(Node.id == target_id))
        stmt = upsert_insert(self.session, Edge).from_select(
            ["kind", "source_id", "target_id", "document_id", "label"], row
        )
        await self.session.execute(
            stmt.on_conflict_do_nothing(index_elements=[Edge.kind, Edge.source_id, Edge.target_id])
        )

    async def add_depiction(self, node_id: str, entity_id: str, document_id: str) -> None:
        row = select(literal(node_id), literal(entity_id), literal(document_id)).where(
            exists().where(Node.id == node_id),
            exists().where(GraphEntityModel.id == entity_id),
            ~exists().where(Depiction.node_id == node_id, Depiction.entity_id == entity_id),
        )
        await self.session.execute(
            insert(Depiction).from_select(["node_id", "entity_id", "document_id"], row)
        )

    async def nodes_for_document(
        self, document_id: str, node_type: str | None = None
    ) -> list[Node]:
        stmt = select(Node).where(Node.document_id == document_id)
        if node_type is not None:
            stmt = stmt.where(Node.node_type == node_type)
        return list((await self.session.scalars(stmt.order_by(Node.id))).all())

    async def edges_for_document(self, document_id: str) -> list[Edge]:
        stmt = select(Edge).where(Edge.document_id == document_id).order_by(Edge.id)
        return list((await self.session.scalars(stmt)).all())
