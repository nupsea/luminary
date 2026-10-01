"""Concept topology: edges between concepts, and the documents each was extracted from.

The `concepts` rows are the nodes, so deleting a concept or a document drops its edges by
cascade. Writes never raise on a row that has just been deleted: the existence checks and
the insert are one statement, and a write that lands on a missing endpoint stores nothing.
"""

from __future__ import annotations

from sqlalchemy import and_, exists, func, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ConceptModel,
    DocumentModel,
    GraphConceptDocumentModel,
    GraphConceptEdgeModel,
)


class GraphConceptRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_extracted_from(self, concept_id: str, document_id: str) -> bool:
        """Link a concept to a document it came from. Idempotent; False when nothing was stored."""
        link = GraphConceptDocumentModel
        row = select(literal(concept_id), literal(document_id)).where(
            exists().where(ConceptModel.id == concept_id),
            exists().where(DocumentModel.id == document_id),
            ~exists().where(and_(link.concept_id == concept_id, link.document_id == document_id)),
        )
        result = await self.session.execute(
            insert(link).from_select(["concept_id", "document_id"], row)
        )
        return bool(result.rowcount)

    async def add_relation(
        self,
        source_id: str,
        target_id: str,
        *,
        kind: str = "related",
        weight: float | None = None,
        confidence: float | None = None,
        status: str | None = "proposed",
    ) -> bool:
        """Add one directed concept edge. Idempotent; False when nothing was stored."""
        edge = GraphConceptEdgeModel
        row = select(
            literal(kind),
            literal(source_id),
            literal(target_id),
            literal(weight),
            literal(confidence),
            literal(status),
        ).where(
            exists().where(ConceptModel.id == source_id),
            exists().where(ConceptModel.id == target_id),
            ~exists().where(
                and_(edge.kind == kind, edge.source_id == source_id, edge.target_id == target_id)
            ),
        )
        result = await self.session.execute(
            insert(edge).from_select(
                ["kind", "source_id", "target_id", "weight", "confidence", "status"], row
            )
        )
        return bool(result.rowcount)

    async def neighbors(self, concept_id: str, limit: int = 10) -> list[str]:
        """Ids of concepts related to `concept_id`, in either direction."""
        edge = GraphConceptEdgeModel
        other = (
            select(edge.target_id.label("id"))
            .where(edge.kind == "related", edge.source_id == concept_id)
            .union(
                select(edge.source_id.label("id")).where(
                    edge.kind == "related", edge.target_id == concept_id
                )
            )
        )
        result = await self.session.execute(select(other.subquery().c.id).limit(limit))
        return [row[0] for row in result]

    async def concept_ids_for_documents(self, document_ids: list[str]) -> list[str]:
        """Ids of concepts extracted from any of `document_ids`."""
        if not document_ids:
            return []
        link = GraphConceptDocumentModel
        result = await self.session.execute(
            select(link.concept_id).where(link.document_id.in_(document_ids)).distinct()
        )
        return [row[0] for row in result]

    async def counts(self) -> dict[str, int]:
        """Rows per table, for the import's verification."""
        edges = await self.session.scalar(select(func.count()).select_from(GraphConceptEdgeModel))
        links = await self.session.scalar(
            select(func.count()).select_from(GraphConceptDocumentModel)
        )
        return {"concept_edges": edges or 0, "concept_documents": links or 0}
