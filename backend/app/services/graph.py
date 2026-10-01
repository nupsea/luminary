"""GraphService: the entity graph, stored in SQLite (`app/repos/graph_*_repo.py`).

Each method opens its own session. Ingestion writes a document's whole graph in one
transaction (`write_document_graph`), so a killed reprocess leaves no half-written graph.
Every row hangs off a document, note or entity row by a cascading foreign key, so
deleting one of those deletes its graph (#204).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.repos.graph_diagram_repo import DIAGRAM_EDGE_KINDS, GraphDiagramRepo
from app.repos.graph_entity_repo import GraphEntityRepo
from app.services import graph_prereq, graph_view

logger = logging.getLogger(__name__)

TECH_RELATIONS = frozenset({"IMPLEMENTS", "EXTENDS", "USES", "REPLACES", "DEPENDS_ON"})
_DIAGRAM_NODE_TYPES = frozenset({"COMPONENT", "ACTOR", "ENTITY_DM", "STEP"})
# Kinds a reader would call a topic rather than code or a library.
_TOPIC_TYPES = ("PERSON", "PLACE", "CONCEPT")
# The diagram extractor's property name for each arrow's text.
_DIAGRAM_LABEL_KEYS = {"CONNECTS_TO": "label", "SENDS_TO": "message", "LEADS_TO": "condition"}


@dataclass
class DocumentGraph:
    """One document's extracted graph, accumulated in memory and written in one transaction."""

    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    co_occurrences: Counter[tuple[str, str]] = field(default_factory=Counter)
    edges: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def add_entity(
        self, entity_id: str, name: str, entity_type: str, aliases: list[str] | None = None
    ) -> None:
        """Count one mention. The latest name and type win, as do non-empty aliases."""
        row = self.entities.setdefault(entity_id, {"id": entity_id, "count": 0, "aliases": []})
        row.update(name=name, type=entity_type, count=row["count"] + 1)
        if aliases:
            row["aliases"] = list(aliases)

    def add_co_occurrence(self, entity_id_a: str, entity_id_b: str) -> None:
        if entity_id_a != entity_id_b:
            self.co_occurrences[(entity_id_a, entity_id_b)] += 1

    def add_edge(self, kind: str, source_id: str, target_id: str, **props: Any) -> None:
        self.edges.setdefault(kind, []).append(
            {"source_id": source_id, "target_id": target_id, **props}
        )

    def add_tech_relation(self, source_id: str, target_id: str, label: str) -> None:
        if label not in TECH_RELATIONS:
            raise ValueError(
                f"Unknown tech relation label: {label!r}. Must be one of {sorted(TECH_RELATIONS)}"
            )
        self.add_edge(label, source_id, target_id)


_graph_service: GraphService | None = None


def get_graph_service() -> GraphService:
    global _graph_service
    if _graph_service is None:
        _graph_service = GraphService()
    return _graph_service


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


class GraphService:
    # Writes

    async def write_document_graph(
        self, document_id: str, extracted: DocumentGraph, *, replace: bool = False
    ) -> bool:
        """Write a document's graph in one transaction. False if the document is gone.

        `replace` first deletes the document's existing entities, in the same transaction.
        """
        async with _session() as session:
            repo = GraphEntityRepo(session)
            try:
                if replace:
                    removed = await repo.delete_for_document(document_id)
                    logger.info("replacing %d entities", removed, extra={"doc_id": document_id})
                await repo.upsert_entities(document_id, list(extracted.entities.values()))
                known = set(extracted.entities) | {
                    e.id for e in await repo.entities_for_document(document_id)
                }
                pairs = {
                    pair: float(w)
                    for pair, w in extracted.co_occurrences.items()
                    if pair[0] in known and pair[1] in known
                }
                await repo.add_co_occurrences(document_id, pairs)
                for kind, rows in extracted.edges.items():
                    kept = [r for r in rows if r["source_id"] in known and r["target_id"] in known]
                    await repo.add_edges(document_id, kind, kept)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.info("graph not written: document %s was deleted", document_id)
                return False
        return True

    async def add_prerequisite_with_section(
        self,
        dependent_id: str,
        prerequisite_id: str,
        document_id: str,
        confidence: float,
        source_section_id: str,
    ) -> None:
        extracted = DocumentGraph()
        extracted.add_edge(
            "PREREQUISITE_OF",
            dependent_id,
            prerequisite_id,
            confidence=confidence,
            source_section_id=source_section_id,
        )
        await self.write_document_graph(document_id, extracted)

    async def add_same_concept_edge(
        self,
        entity_id_a: str,
        entity_id_b: str,
        source_doc_id: str,
        target_doc_id: str,
        confidence: float,
        contradiction: bool = False,
        contradiction_note: str = "",
        prefer_source: str = "",
    ) -> None:
        async with _session() as session:
            await GraphEntityRepo(session).add_link(
                entity_id_a,
                entity_id_b,
                source_doc_id,
                target_doc_id,
                confidence,
                contradiction=contradiction,
                contradiction_note=contradiction_note,
                prefer_source=prefer_source,
            )
            await session.commit()

    async def upsert_diagram_node(
        self,
        node_id: str,
        name: str,
        node_type: str,
        document_id: str,
        source_image_id: str | None = None,
    ) -> None:
        async with _session() as session:
            await GraphDiagramRepo(session).upsert_node(
                node_id, name, node_type, source_image_id or "", document_id
            )
            await session.commit()

    async def add_diagram_edge(
        self, from_id: str, to_id: str, edge_type: str, document_id: str, **properties: str
    ) -> None:
        if edge_type not in DIAGRAM_EDGE_KINDS:
            logger.warning("add_diagram_edge: unknown edge_type=%r, skipping", edge_type)
            return
        label = properties.get(_DIAGRAM_LABEL_KEYS.get(edge_type, ""), "")
        async with _session() as session:
            await GraphDiagramRepo(session).add_edge(from_id, to_id, edge_type, document_id, label)
            await session.commit()

    async def add_depicts_edge(
        self, diagram_node_id: str, entity_id: str, document_id: str
    ) -> None:
        async with _session() as session:
            await GraphDiagramRepo(session).add_depiction(diagram_node_id, entity_id, document_id)
            await session.commit()

    # Entity reads

    async def get_entities_by_type_for_document(self, document_id: str) -> dict[str, list[str]]:
        async with _session() as session:
            entities = await GraphEntityRepo(session).entities_for_document(document_id)
        by_type: dict[str, list[str]] = {}
        for e in entities:
            by_type.setdefault(e.type, []).append(e.name)
        return by_type

    async def get_entity_ids_by_name(
        self, document_id: str, types: Iterable[str]
    ) -> dict[str, str]:
        async with _session() as session:
            entities = await GraphEntityRepo(session).entities_for_document(document_id, types)
        return {e.name: e.id for e in entities}

    async def get_entities_detailed_for_document(self, document_id: str) -> list[dict]:
        async with _session() as session:
            entities = await GraphEntityRepo(session).entities_for_document(document_id)
        return [{"name": e.name, "type": e.type, "frequency": e.frequency} for e in entities]

    async def get_entities_by_type(self, document_id: str, entity_type: str) -> list[dict]:
        async with _session() as session:
            if entity_type in _DIAGRAM_NODE_TYPES:
                nodes = await GraphDiagramRepo(session).nodes_for_document(document_id, entity_type)
                return [
                    {"id": n.id, "name": n.name, "type": n.node_type, "frequency": n.frequency}
                    for n in nodes
                ]
            entities = await GraphEntityRepo(session).entities_for_document(
                document_id, (entity_type,)
            )
        return [
            {"id": e.id, "name": e.name, "type": e.type, "frequency": e.frequency} for e in entities
        ]

    async def get_entities_with_counts(
        self,
        document_id: str,
        min_mentions: int = 1,
        allowed_types: tuple[str, ...] = ("CONCEPT",),
    ) -> list[tuple[str, int]]:
        """[(name, mention count)] for one document, most mentioned first."""
        if not document_id or not allowed_types:
            return []
        async with _session() as session:
            rows = await GraphEntityRepo(session).names_by_mentions(
                document_id, allowed_types, min_mentions
            )
        out: list[tuple[str, int]] = []
        seen: set[str] = set()
        for name, count in rows:
            if name not in seen:
                seen.add(name)
                out.append((name, count))
        return out

    async def get_entities_for_documents(
        self, document_ids: list[str], limit: int = 15
    ) -> list[str]:
        """Distinct topic names across `document_ids`, document by document."""
        names: list[str] = []
        async with _session() as session:
            repo = GraphEntityRepo(session)
            for doc_id in document_ids:
                for name, _ in await repo.names_by_mentions(doc_id, _TOPIC_TYPES, 1):
                    if len(names) >= limit:
                        return names
                    if name not in names:
                        names.append(name)
        return names

    async def get_cross_document_entities(
        self, limit: int = 10, min_documents: int = 2, topics_only: bool = True
    ) -> list[str]:
        """Names found in `min_documents` or more documents, most widespread first."""
        async with _session() as session:
            return await GraphEntityRepo(session).cross_document_names(
                min_documents, limit, _TOPIC_TYPES if topics_only else None
            )

    async def get_document_ids_for_entity(self, name: str) -> list[str]:
        """Documents holding an entity called `name`; failing that, one containing it."""
        async with _session() as session:
            repo = GraphEntityRepo(session)
            exact = await repo.document_ids_for_name(name, partial=False, limit=1000)
            return exact or await repo.document_ids_for_name(name, partial=True, limit=20)

    async def get_entity_neighbours(
        self, name: str, kind: str, document_ids: list[str] | None, limit: int = 10
    ) -> list[tuple[str, float, str]]:
        """(name, weight, label) of entities a `kind` edge leads to from one called `name`.

        Only edges in `document_ids` when given; every live document otherwise.
        """
        async with _session() as session:
            return await GraphEntityRepo(session).neighbours_by_name(
                name, kind, document_ids, limit
            )

    async def match_entity_by_name(self, node_name: str, document_id: str) -> str | None:
        """Id of the first entity in the document whose name contains `node_name`."""
        needle = node_name.lower()
        async with _session() as session:
            entities = await GraphEntityRepo(session).entities_for_document(document_id)
        return next((e.id for e in entities if needle in e.name.lower()), None)

    async def get_all_document_ids(self) -> list[str]:
        """Documents that have at least one entity."""
        async with _session() as session:
            return await GraphEntityRepo(session).document_ids()

    async def count_for_document(self, document_id: str) -> tuple[int, int]:
        """(entities, co-occurrence edges) for one document."""
        async with _session() as session:
            repo = GraphEntityRepo(session)
            return (
                await repo.entity_count(document_id),
                await repo.edge_count(document_id, "CO_OCCURS"),
            )

    async def get_co_occurring_pairs_for_document(
        self, document_id: str, limit: int = 5
    ) -> list[tuple[str, str, float]]:
        """Top pairs by co-occurrence weight. A pair stored in both directions is
        returned once, at its heavier weight (I-49)."""
        async with _session() as session:
            rows = await GraphEntityRepo(session).named_edges(
                document_id, "CO_OCCURS", limit=limit * 2
            )
        pairs: list[tuple[str, str, float]] = []
        seen: set[frozenset[str]] = set()
        for name_a, name_b, id_a, id_b, edge in rows:
            key = frozenset((name_a.casefold(), name_b.casefold()))
            if id_a == id_b or key in seen:
                continue
            seen.add(key)
            pairs.append((name_a, name_b, float(edge.weight or 0.0)))
            if len(pairs) >= limit:
                break
        return pairs

    # Prerequisites

    async def get_prerequisite_edges_for_document(self, document_id: str) -> list[dict]:
        async with _session() as session:
            return await graph_prereq.prerequisite_edges(GraphEntityRepo(session), document_id)

    async def get_entry_point_concepts(self, document_id: str, limit: int = 10) -> list[str]:
        async with _session() as session:
            return await graph_prereq.entry_points(GraphEntityRepo(session), document_id, limit)

    async def get_learning_path(self, start_entity_name: str, document_id: str) -> dict:
        async with _session() as session:
            return await graph_prereq.learning_path(
                GraphEntityRepo(session), start_entity_name, document_id
            )

    # SAME_CONCEPT

    async def get_same_concept_edges(self) -> list[dict]:
        async with _session() as session:
            return await GraphEntityRepo(session).links()

    async def get_contradiction_edges_for_docs(self, doc_ids: list[str]) -> list[dict]:
        if not doc_ids:
            return []
        async with _session() as session:
            return await GraphEntityRepo(session).links(doc_ids, contradictions_only=True)

    async def get_concept_clusters(self) -> list[dict]:
        return graph_view.concept_clusters(await self.get_same_concept_edges())

    # Views for the graph API

    async def get_graph_for_document(self, document_id: str, include_notes: bool = False) -> dict:
        async with _session() as session:
            return await graph_view.document_graph(session, document_id, include_notes)

    async def get_graph_for_documents(
        self,
        document_ids: list[str],
        include_same_concept: bool = False,
        include_notes: bool = False,
    ) -> dict:
        async with _session() as session:
            return await graph_view.documents_graph(
                session, document_ids, include_same_concept, include_notes
            )

    async def get_call_graph(self, document_id: str) -> dict:
        async with _session() as session:
            return await graph_view.call_graph(GraphEntityRepo(session), document_id)
