"""KuzuService: Kuzu embedded graph database for entity relationship storage.

Schema:
  Nodes: Entity(id, name, type, frequency, aliases), Document(id, title, content_type)
         DiagramNode(id, name, node_type, source_image_id, document_id, frequency) -- S136
         Note(id, note_id, preview, created_at) -- S163
  Edges: MENTIONED_IN(Entity->Document, count),
         CO_OCCURS(Entity->Entity, weight, document_id),
         RELATED_TO(Entity->Entity, relation_label, confidence),
         CALLS(Entity->Entity, document_id)  -- function call graph for code documents
         PREREQUISITE_OF(Entity->Entity, document_id, confidence)  -- S117
         IMPLEMENTS(Entity->Entity, document_id)   -- tech relation
         EXTENDS(Entity->Entity, document_id)       -- tech relation
         USES(Entity->Entity, document_id)          -- tech relation
         REPLACES(Entity->Entity, document_id)      -- tech relation
         DEPENDS_ON(Entity->Entity, document_id)    -- tech relation
         VERSION_OF(Entity->Entity, document_id)    -- versioned library links
         CONNECTS_TO(DiagramNode->DiagramNode, document_id, label)  -- S136
         STORES_IN(DiagramNode->DiagramNode, document_id)            -- S136
         SENDS_TO(DiagramNode->DiagramNode, document_id, message)    -- S136
         HAS_FIELD(DiagramNode->DiagramNode, document_id)            -- S136
         REFERENCES_DM(DiagramNode->DiagramNode, document_id)        -- S136
         LEADS_TO(DiagramNode->DiagramNode, document_id, condition)  -- S136
         DEPICTS(DiagramNode->Entity, document_id)                   -- S136
         WRITTEN_ABOUT(Note->Entity, confidence)                     -- S163
         TAG_IS_CONCEPT(Note->Entity, tag)                           -- S163
         DERIVED_FROM(Note->Document)                                -- S163

Note: `aliases` column on Entity was added in S86.  Databases created before S86 will
not have this column; aliases writes are wrapped in try/except for graceful degradation.

SAME_CONCEPT edge: links two Entity nodes from different documents that represent
the same concept. Properties: source_doc_id, target_doc_id, confidence (FLOAT),
contradiction (INT64 0/1 -- Kuzu does not support BOOLEAN in all versions),
contradiction_note (STRING), prefer_source (STRING "a"|"b"|"").
"""

import logging

from app.config import get_settings
from app.services.graph_concept import KuzuConceptRepo
from app.services.graph_connection import KuzuConnection
from app.services.graph_entity import KuzuEntityRepo
from app.services.graph_prereq import KuzuPrereqRepo
from app.services.graph_tech import KuzuTechRepo
from app.services.graph_view import KuzuViewRepo

logger = logging.getLogger(__name__)

_graph_service: "KuzuService | None" = None


def get_graph_service() -> "KuzuService":
    global _graph_service
    if _graph_service is None:
        settings = get_settings()
        _graph_service = KuzuService(settings.DATA_DIR)
    return _graph_service


class KuzuService:
    def __init__(self, data_dir: str) -> None:
        self._connection = KuzuConnection(data_dir)
        # Back-compat aliases. chat_graph (and possibly tests) read
        # `service._conn` directly.
        self._db = self._connection.db
        self._conn = self._connection.conn
        self._lock = self._connection.lock
        self._entity = KuzuEntityRepo(self._connection)
        self._prereq = KuzuPrereqRepo(self._connection)
        self._concept = KuzuConceptRepo(self._connection)
        self._tech = KuzuTechRepo(self._connection)
        self._view = KuzuViewRepo(self._connection, self._tech, self._prereq, self._concept)
        logger.info("KuzuService initialized")

    # -------------------------------------------------------------------------
    # Upsert helpers
    # -------------------------------------------------------------------------

    def upsert_entity(
        self,
        entity_id: str,
        name: str,
        entity_type: str,
        aliases: list[str] | None = None,
    ) -> None:
        return self._entity.upsert_entity(entity_id, name, entity_type, aliases)

    def get_entities_by_type_for_document(self, document_id: str) -> dict[str, list[str]]:
        return self._entity.get_entities_by_type_for_document(document_id)

    def upsert_document(self, doc_id: str, title: str, content_type: str) -> None:
        return self._entity.upsert_document(doc_id, title, content_type)

    def add_mention(self, entity_id: str, document_id: str) -> None:
        return self._entity.add_mention(entity_id, document_id)

    def add_co_occurrence(self, entity_id_a: str, entity_id_b: str, document_id: str) -> None:
        return self._entity.add_co_occurrence(entity_id_a, entity_id_b, document_id)

    def add_relation(
        self, entity_id_a: str, entity_id_b: str, relation_label: str, confidence: float = 1.0
    ) -> None:
        return self._entity.add_relation(entity_id_a, entity_id_b, relation_label, confidence)

    def get_related_entity_pairs_for_document(
        self, document_id: str, limit: int = 5
    ) -> list[tuple[str, str, str, float]]:
        return self._entity.get_related_entity_pairs_for_document(document_id, limit=limit)

    def get_co_occurring_pairs_for_document(
        self, document_id: str, limit: int = 5
    ) -> list[tuple[str, str, float]]:
        return self._entity.get_co_occurring_pairs_for_document(document_id, limit=limit)

    # -------------------------------------------------------------------------
    # Prerequisite edges
    # -------------------------------------------------------------------------

    def add_prerequisite(
        self,
        dependent_id: str,
        prerequisite_id: str,
        document_id: str,
        confidence: float = 1.0,
    ) -> None:
        return self._prereq.add_prerequisite(
            dependent_id, prerequisite_id, document_id, confidence
        )

    def get_prerequisite_edges_for_document(self, document_id: str) -> list[dict]:
        return self._prereq.get_prerequisite_edges_for_document(document_id)

    def add_prerequisite_with_section(
        self,
        dependent_id: str,
        prerequisite_id: str,
        document_id: str,
        confidence: float,
        source_section_id: str,
    ) -> None:
        return self._prereq.add_prerequisite_with_section(
            dependent_id, prerequisite_id, document_id, confidence, source_section_id
        )

    def has_prerequisite_edges(self, document_id: str) -> bool:
        return self._prereq.has_prerequisite_edges(document_id)

    def get_entry_point_concepts(self, document_id: str, limit: int = 10) -> list[str]:
        return self._prereq.get_entry_point_concepts(document_id, limit=limit)

    def get_prerequisite_edges_for_graph(self, document_id: str) -> list[dict]:
        return self._prereq.get_prerequisite_edges_for_graph(document_id)

    def get_learning_path(self, start_entity_name: str, document_id: str) -> dict:
        return self._prereq.get_learning_path(start_entity_name, document_id)

    # -------------------------------------------------------------------------
    # SAME_CONCEPT edges
    # -------------------------------------------------------------------------

    def add_same_concept_edge(
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
        return self._concept.add_same_concept_edge(
            entity_id_a,
            entity_id_b,
            source_doc_id,
            target_doc_id,
            confidence,
            contradiction=contradiction,
            contradiction_note=contradiction_note,
            prefer_source=prefer_source,
        )

    def get_same_concept_edges(self) -> list[dict]:
        return self._concept.get_same_concept_edges()

    def get_concept_clusters(self) -> list[dict]:
        return self._concept.get_concept_clusters()

    # -------------------------------------------------------------------------
    # Delete
    # -------------------------------------------------------------------------

    def get_all_document_ids(self) -> list[str]:
        """Return every Document.id known to the graph (deduplicated, no order)."""
        try:
            result = self._conn.execute("MATCH (d:Document) RETURN d.id")
            ids: list[str] = []
            seen: set[str] = set()
            while result.has_next():
                did = result.get_next()[0]
                if did and did not in seen:
                    seen.add(did)
                    ids.append(did)
            return ids
        except Exception:
            logger.debug("get_all_document_ids failed", exc_info=True)
            return []

    def delete_document(self, document_id: str) -> None:
        """Remove a Document node and all edges connected to it."""
        # Delete MENTIONED_IN edges to this document
        self._conn.execute(
            "MATCH (e:Entity)-[r:MENTIONED_IN]->(d:Document {id: $did}) DELETE r",
            {"did": document_id},
        )
        # Delete the Document node
        self._conn.execute(
            "MATCH (d:Document {id: $did}) DELETE d",
            {"did": document_id},
        )
        logger.info("Deleted graph nodes for document", extra={"document_id": document_id})

    def count_for_document(self, document_id: str) -> tuple[int, int]:
        """Return (entity_count, edge_count) for the given document.

        entity_count — distinct Entity nodes that MENTIONED_IN this document.
        edge_count   — CO_OCCURS edges recorded for this document.
        """
        try:
            e_result = self._conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did}) RETURN count(*)",
                {"did": document_id},
            )
            entity_count = e_result.get_next()[0] if e_result.has_next() else 0

            co_result = self._conn.execute(
                "MATCH ()-[r:CO_OCCURS {document_id: $did}]->() RETURN count(*)",
                {"did": document_id},
            )
            edge_count = co_result.get_next()[0] if co_result.has_next() else 0
        except Exception:
            entity_count = 0
            edge_count = 0
        return int(entity_count), int(edge_count)

    # -------------------------------------------------------------------------
    # Cross-cutting view aggregators -- delegated to KuzuViewRepo
    # -------------------------------------------------------------------------

    def get_entities_for_documents(self, document_ids: list[str], limit: int = 15) -> list[str]:
        return self._view.get_entities_for_documents(document_ids, limit=limit)

    def get_cross_document_entities(self, limit: int = 10) -> list[str]:
        return self._view.get_cross_document_entities(limit=limit)

    def get_graph_for_document(self, document_id: str, include_notes: bool = False) -> dict:
        return self._view.get_graph_for_document(document_id, include_notes=include_notes)

    def get_graph_for_documents(
        self,
        document_ids: list[str],
        include_same_concept: bool = False,
        include_notes: bool = False,
    ) -> dict:
        return self._view.get_graph_for_documents(
            document_ids,
            include_same_concept=include_same_concept,
            include_notes=include_notes,
        )

    def match_entity_by_name(self, node_name: str, document_id: str) -> str | None:
        return self._entity.match_entity_by_name(node_name, document_id)

    # -------------------------------------------------------------------------
    # Code-graph + diagram + tech-relation edges -- delegated to KuzuTechRepo
    # -------------------------------------------------------------------------

    def add_call_edge(self, caller_id: str, callee_id: str, document_id: str) -> None:
        return self._tech.add_call_edge(caller_id, callee_id, document_id)

    def add_tech_relation(
        self,
        entity_id_a: str,
        entity_id_b: str,
        relation_label: str,
        document_id: str,
    ) -> None:
        return self._tech.add_tech_relation(
            entity_id_a, entity_id_b, relation_label, document_id
        )

    def add_version_of(self, version_entity_id: str, base_entity_id: str, document_id: str) -> None:
        return self._tech.add_version_of(version_entity_id, base_entity_id, document_id)

    def get_entities_by_type(self, document_id: str, entity_type: str) -> list[dict]:
        return self._tech.get_entities_by_type(document_id, entity_type)

    def upsert_diagram_node(
        self,
        node_id: str,
        name: str,
        node_type: str,
        document_id: str,
        source_image_id: str | None = None,
    ) -> None:
        return self._tech.upsert_diagram_node(
            node_id=node_id,
            name=name,
            node_type=node_type,
            source_image_id=source_image_id or "",
            document_id=document_id,
        )

    def add_diagram_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        document_id: str,
        **properties: str,
    ) -> None:
        return self._tech.add_diagram_edge(
            from_id=from_id,
            to_id=to_id,
            edge_type=edge_type,
            document_id=document_id,
            **properties,
        )

    def add_depicts_edge(self, diagram_node_id: str, entity_id: str, document_id: str) -> None:
        return self._tech.add_depicts_edge(diagram_node_id, entity_id, document_id)

    def get_diagram_nodes_for_document(self, document_id: str) -> list[dict]:
        return self._tech.get_diagram_nodes_for_document(document_id)

    def get_diagram_edges_for_document(self, document_id: str) -> list[dict]:
        return self._tech.get_diagram_edges_for_document(document_id)

    def get_call_graph(self, document_id: str) -> dict:
        return self._tech.get_call_graph(document_id)
