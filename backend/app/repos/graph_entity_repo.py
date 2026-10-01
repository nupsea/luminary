"""Entities, the edges between them, and cross-document SAME_CONCEPT links.

An entity belongs to the document it was extracted from (its id is derived from the
document id), so deleting the document deletes its entities, and their edges with them.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, delete, exists, func, insert, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import GraphEntityEdgeModel, GraphEntityLinkModel, GraphEntityModel
from app.repos._helpers import upsert_insert

Entity = GraphEntityModel
Edge = GraphEntityEdgeModel
Link = GraphEntityLinkModel


class GraphEntityRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Writes

    async def upsert_entities(self, document_id: str, rows: list[dict[str, Any]]) -> None:
        """Add entities, or add to their counts. Each row: id, name, type, count, aliases."""
        if not rows:
            return
        stmt = upsert_insert(self.session, Entity)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Entity.id],
            set_={
                "name": stmt.excluded.name,
                "type": stmt.excluded.type,
                "frequency": Entity.frequency + stmt.excluded.frequency,
                "mention_count": Entity.mention_count + stmt.excluded.mention_count,
                "aliases": func.coalesce(func.nullif(stmt.excluded.aliases, "[]"), Entity.aliases),
            },
        )
        await self.session.execute(
            stmt,
            [
                {
                    "id": r["id"],
                    "document_id": document_id,
                    "name": r["name"],
                    "type": r["type"],
                    "frequency": r["count"],
                    "mention_count": r["count"],
                    "aliases": r.get("aliases") or [],
                }
                for r in rows
            ],
        )

    async def add_co_occurrences(
        self, document_id: str, weights: dict[tuple[str, str], float]
    ) -> None:
        """Add to the weight of each co-occurrence pair. Self-pairs are refused (I-49)."""
        rows = [
            {
                "kind": "CO_OCCURS",
                "source_id": a,
                "target_id": b,
                "document_id": document_id,
                "weight": w,
            }
            for (a, b), w in weights.items()
            if a != b
        ]
        if not rows:
            return
        stmt = upsert_insert(self.session, Edge)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Edge.kind, Edge.source_id, Edge.target_id],
            set_={"weight": Edge.weight + stmt.excluded.weight},
        )
        await self.session.execute(stmt, rows)

    async def add_edges(self, document_id: str, kind: str, rows: list[dict[str, Any]]) -> None:
        """Add edges of one kind; an edge that exists is left as it is.

        Each row: source_id, target_id, and optionally confidence, source_section_id, label.
        """
        rows = [r for r in rows if r["source_id"] != r["target_id"]]
        if not rows:
            return
        values = [
            {
                "kind": kind,
                "document_id": document_id,
                "source_id": r["source_id"],
                "target_id": r["target_id"],
                "confidence": r.get("confidence"),
                "source_section_id": r.get("source_section_id"),
                "label": r.get("label"),
            }
            for r in rows
        ]
        stmt = upsert_insert(self.session, Edge).on_conflict_do_nothing(
            index_elements=[Edge.kind, Edge.source_id, Edge.target_id]
        )
        await self.session.execute(stmt, values)

    async def delete_for_document(self, document_id: str) -> int:
        result = await self.session.execute(delete(Entity).where(Entity.document_id == document_id))
        return result.rowcount or 0

    async def add_link(
        self,
        source_id: str,
        target_id: str,
        source_document_id: str,
        target_document_id: str,
        confidence: float,
        *,
        contradiction: bool = False,
        contradiction_note: str = "",
        prefer_source: str = "",
    ) -> None:
        """Link two entities as the same concept, in either direction, once.

        A second call for a linked pair only records a contradiction, never clears one.
        """
        existing = await self.session.scalar(
            select(Link).where(
                or_(
                    and_(Link.source_id == source_id, Link.target_id == target_id),
                    and_(Link.source_id == target_id, Link.target_id == source_id),
                )
            )
        )
        if existing is not None:
            if contradiction:
                existing.contradiction = True
                existing.contradiction_note = contradiction_note
                existing.prefer_source = prefer_source
            return
        columns = {
            "source_id": source_id,
            "target_id": target_id,
            "source_document_id": source_document_id,
            "target_document_id": target_document_id,
            "confidence": float(confidence),
            "contradiction": contradiction,
            "contradiction_note": contradiction_note,
            "prefer_source": prefer_source,
        }
        row = select(*(literal(v) for v in columns.values())).where(
            exists().where(Entity.id == source_id), exists().where(Entity.id == target_id)
        )
        await self.session.execute(insert(Link).from_select(list(columns), row))

    # Reads

    async def entities_for_document(
        self, document_id: str, types: Iterable[str] | None = None
    ) -> list[Entity]:
        stmt = select(Entity).where(Entity.document_id == document_id)
        if types is not None:
            stmt = stmt.where(Entity.type.in_(list(types)))
        return list((await self.session.scalars(stmt)).all())

    async def entities_for_documents(self, document_ids: list[str]) -> list[Entity]:
        if not document_ids:
            return []
        stmt = select(Entity).where(Entity.document_id.in_(document_ids))
        return list((await self.session.scalars(stmt)).all())

    async def names_by_mentions(
        self, document_id: str, types: Iterable[str], min_mentions: int
    ) -> list[tuple[str, int]]:
        result = await self.session.execute(
            select(Entity.name, Entity.mention_count)
            .where(
                Entity.document_id == document_id,
                Entity.type.in_(list(types)),
                Entity.mention_count >= min_mentions,
            )
            .order_by(Entity.mention_count.desc(), Entity.name)
        )
        return [(name, int(count)) for name, count in result]

    async def cross_document_names(
        self, min_documents: int, limit: int, types: Iterable[str] | None = None
    ) -> list[str]:
        """Names that occur in at least `min_documents` documents, most widespread first."""
        doc_count = func.count(Entity.document_id.distinct())
        stmt = select(Entity.name).group_by(Entity.name).having(doc_count >= min_documents)
        if types is not None:
            stmt = stmt.where(Entity.type.in_(list(types)))
        result = await self.session.execute(stmt.order_by(doc_count.desc()).limit(limit))
        return [row[0] for row in result]

    async def document_ids_for_name(self, name: str, *, partial: bool, limit: int) -> list[str]:
        pattern = func.lower(name)
        condition = (
            func.instr(func.lower(Entity.name), pattern) > 0
            if partial
            else func.lower(Entity.name) == pattern
        )
        result = await self.session.execute(
            select(Entity.document_id).where(condition).distinct().limit(limit)
        )
        return [row[0] for row in result]

    async def document_ids(self) -> list[str]:
        result = await self.session.execute(select(Entity.document_id).distinct())
        return [row[0] for row in result]

    async def entity_count(self, document_id: str) -> int:
        stmt = select(func.count()).select_from(Entity).where(Entity.document_id == document_id)
        return (await self.session.scalar(stmt)) or 0

    async def edge_count(self, document_id: str, kind: str) -> int:
        stmt = (
            select(func.count())
            .select_from(Edge)
            .where(Edge.document_id == document_id, Edge.kind == kind)
        )
        return (await self.session.scalar(stmt)) or 0

    async def edges_for_documents(
        self, document_ids: list[str], kinds: Iterable[str]
    ) -> list[Edge]:
        if not document_ids:
            return []
        stmt = select(Edge).where(Edge.document_id.in_(document_ids), Edge.kind.in_(list(kinds)))
        return list((await self.session.scalars(stmt)).all())

    async def named_edges(
        self, document_id: str, kind: str, *, limit: int | None = None
    ) -> list[tuple[str, str, str, str, Edge]]:
        """(source name, target name, source id, target id, edge) for one kind, heaviest first."""
        source, target = aliased(Entity), aliased(Entity)
        stmt = (
            select(source.name, target.name, source.id, target.id, Edge)
            .join(source, source.id == Edge.source_id)
            .join(target, target.id == Edge.target_id)
            .where(Edge.document_id == document_id, Edge.kind == kind)
            .order_by(Edge.weight.desc(), Edge.confidence.desc(), Edge.id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return [tuple(row) for row in await self.session.execute(stmt)]

    async def neighbours_by_name(
        self, name: str, kind: str, document_ids: list[str] | None, limit: int
    ) -> list[tuple[str, float, str]]:
        """(neighbour name, weight, label) for `kind` edges leaving entities called `name`."""
        source, target = aliased(Entity), aliased(Entity)
        stmt = (
            select(target.name, Edge.weight, Edge.label)
            .join(source, source.id == Edge.source_id)
            .join(target, target.id == Edge.target_id)
            .where(Edge.kind == kind, source.name == name)
        )
        if document_ids is not None:
            stmt = stmt.where(Edge.document_id.in_(document_ids))
        result = await self.session.execute(stmt.order_by(Edge.weight.desc()).limit(limit))
        return [(n, float(w or 0.0), label or "") for n, w, label in result]

    async def links(
        self, document_ids: list[str] | None = None, *, contradictions_only: bool = False
    ) -> list[dict[str, Any]]:
        source, target = aliased(Entity), aliased(Entity)
        stmt = (
            select(Link, source.name, target.name)
            .join(source, source.id == Link.source_id)
            .join(target, target.id == Link.target_id)
            .order_by(Link.id)
        )
        if contradictions_only:
            stmt = stmt.where(Link.contradiction.is_(True))
        if document_ids is not None:
            stmt = stmt.where(
                or_(
                    Link.source_document_id.in_(document_ids),
                    Link.target_document_id.in_(document_ids),
                )
            )
        return [
            {
                "entity_id_a": link.source_id,
                "entity_id_b": link.target_id,
                "name_a": name_a,
                "name_b": name_b,
                "source_doc_id": link.source_document_id,
                "target_doc_id": link.target_document_id,
                "confidence": float(link.confidence or 0.0),
                "contradiction": bool(link.contradiction),
                "contradiction_note": link.contradiction_note or "",
                "prefer_source": link.prefer_source or "",
            }
            for link, name_a, name_b in await self.session.execute(stmt)
        ]
