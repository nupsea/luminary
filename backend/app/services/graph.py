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
         IMPLEMENTS(Entity->Entity, document_id)   -- tech relation (S135)
         EXTENDS(Entity->Entity, document_id)       -- tech relation (S135)
         USES(Entity->Entity, document_id)          -- tech relation (S135)
         REPLACES(Entity->Entity, document_id)      -- tech relation (S135)
         DEPENDS_ON(Entity->Entity, document_id)    -- tech relation (S135)
         VERSION_OF(Entity->Entity, document_id)    -- versioned library links (S135)
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

SAME_CONCEPT edge (S141): links two Entity nodes from different documents that represent
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
    # Prerequisite edges (S117)
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
    # SAME_CONCEPT edges (S141)
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

    def get_entities_for_documents(self, document_ids: list[str], limit: int = 15) -> list[str]:
        """Return entity names (PERSON, PLACE, CONCEPT) mentioned in the given documents.

        Iterates over each document_id and collects unique names up to *limit*.
        Returns empty list on any error (non-fatal for query rewriting).
        """
        if not document_ids:
            return []
        try:
            seen: set[str] = set()
            names: list[str] = []
            for doc_id in document_ids:
                if len(names) >= limit:
                    break
                result = self._conn.execute(
                    "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did})"
                    " WHERE e.type IN ['PERSON', 'PLACE', 'CONCEPT']"
                    " RETURN e.name",
                    {"did": doc_id},
                )
                while result.has_next() and len(names) < limit:
                    row = result.get_next()
                    name = row[0]
                    if name and name not in seen:
                        seen.add(name)
                        names.append(name)
            return names
        except Exception:
            logger.warning("get_entities_for_documents failed", exc_info=True)
            return []

    def get_cross_document_entities(self, limit: int = 10) -> list[str]:
        """Return entity names that appear in 2+ documents, ordered by doc count desc.

        Used for all-scope chat suggestions (cross-document themes).
        Returns empty list on any Kuzu error (non-fatal).
        """
        try:
            result = self._conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document)"
                " WHERE e.type IN ['PERSON', 'PLACE', 'CONCEPT']"
                " WITH e.name AS name, count(DISTINCT d.id) AS doc_count"
                " WHERE doc_count >= 2"
                " RETURN name"
                f" ORDER BY doc_count DESC LIMIT {int(limit)}",
            )
            names: list[str] = []
            while result.has_next():
                row = result.get_next()
                if row[0]:
                    names.append(row[0])
            return names
        except Exception:
            logger.debug("get_cross_document_entities failed", exc_info=True)
            return []

    # -------------------------------------------------------------------------
    # Query
    # -------------------------------------------------------------------------

    def get_graph_for_document(self, document_id: str, include_notes: bool = False) -> dict:
        """Return nodes and edges for a single document.

        Includes Entity nodes (with CO_OCCURS + tech-relation edges) and
        DiagramNode rows (with diagram edges) merged into a single graph.
        Pass include_notes=True to also include Note nodes connected to entities
        via WRITTEN_ABOUT or TAG_IS_CONCEPT edges (S172).
        """
        result = self._conn.execute(
            "MATCH (e:Entity)-[r:MENTIONED_IN]->(d:Document {id: $did})"
            " RETURN e.id, e.name, e.type, e.frequency, r.count",
            {"did": document_id},
        )
        nodes: list[dict] = []
        entity_ids: set[str] = set()
        while result.has_next():
            row = result.get_next()
            eid, name, etype, freq, count = row
            nodes.append(
                {
                    "id": eid,
                    "label": name,
                    "type": etype,
                    "size": freq or 1,
                    "source_image_id": "",
                    "mention_count": count or 1,
                }
            )
            entity_ids.add(eid)

        edges = self._get_co_occurrence_edges(entity_ids, document_id)
        edges.extend(self._tech._get_tech_relation_edges(entity_ids, document_id))
        # Include PREREQUISITE_OF edges for Viz tab (S139)
        edges.extend(self.get_prerequisite_edges_for_graph(document_id))

        # Include diagram-derived nodes and edges (S136)
        diagram_nodes = self.get_diagram_nodes_for_document(document_id)
        nodes.extend(diagram_nodes)
        edges.extend(self.get_diagram_edges_for_document(document_id))

        # Include Note nodes connected to entities in scope (S172)
        if include_notes and entity_ids:
            note_nodes, note_edges = self._get_note_nodes_for_entities(entity_ids)
            nodes.extend(note_nodes)
            edges.extend(note_edges)

        return {"nodes": nodes, "edges": edges}

    def get_graph_for_documents(
        self,
        document_ids: list[str],
        include_same_concept: bool = False,
        include_notes: bool = False,
    ) -> dict:
        """Return merged nodes and edges for multiple documents.

        Includes Entity nodes and DiagramNode rows from all specified documents.
        Pass include_same_concept=True to include SAME_CONCEPT cross-book edges (S141).
        Pass include_notes=True to include Note nodes connected to entities in scope (S172).
        """
        if not document_ids:
            return {"nodes": [], "edges": []}

        placeholders = ", ".join(f"$id{i}" for i in range(len(document_ids)))
        params = {f"id{i}": did for i, did in enumerate(document_ids)}
        result = self._conn.execute(
            f"MATCH (e:Entity)-[r:MENTIONED_IN]->(d:Document)"
            f" WHERE d.id IN [{placeholders}]"
            f" RETURN e.id, e.name, e.type, e.frequency, r.count",
            params,
        )
        nodes_map: dict[str, dict] = {}
        while result.has_next():
            row = result.get_next()
            eid, name, etype, freq, count = row
            if eid not in nodes_map:
                nodes_map[eid] = {
                    "id": eid,
                    "label": name,
                    "type": etype,
                    "size": freq or 1,
                    "source_image_id": "",
                    "mention_count": count or 1,
                }
            else:
                nodes_map[eid]["mention_count"] = nodes_map[eid]["mention_count"] + (count or 1)

        entity_ids = set(nodes_map.keys())
        edges: list[dict] = []
        for doc_id in document_ids:
            edges.extend(self._get_co_occurrence_edges(entity_ids, doc_id))
            # Include diagram-derived nodes and edges for this document (S136)
            for dnode in self.get_diagram_nodes_for_document(doc_id):
                if dnode["id"] not in nodes_map:
                    nodes_map[dnode["id"]] = dnode
            edges.extend(self.get_diagram_edges_for_document(doc_id))

        # Include SAME_CONCEPT cross-book edges when requested (S141)
        if include_same_concept:
            sc_edges = self.get_same_concept_edges()
            for e in sc_edges:
                if e["entity_id_a"] in nodes_map and e["entity_id_b"] in nodes_map:
                    edges.append(
                        {
                            "source": e["entity_id_a"],
                            "target": e["entity_id_b"],
                            "weight": e["confidence"],
                            "relation": "SAME_CONCEPT",
                            "contradiction": e["contradiction"],
                        }
                    )

        # Include Note nodes connected to entities in scope (S172)
        if include_notes and entity_ids:
            note_nodes, note_edges = self._get_note_nodes_for_entities(entity_ids)
            for nn in note_nodes:
                if nn["id"] not in nodes_map:
                    nodes_map[nn["id"]] = nn
            edges.extend(note_edges)

        return {"nodes": list(nodes_map.values()), "edges": edges}

    def _get_note_nodes_for_entities(self, entity_ids: set[str]) -> tuple[list[dict], list[dict]]:
        """Return Note nodes and their edges for entities in scope (S172).

        Returns (note_nodes, note_edges) where:
          - note_nodes: list of {id, note_id, label, type='note', size, outgoing_link_count}
          - note_edges: WRITTEN_ABOUT + TAG_IS_CONCEPT + LINKS_TO edges in graph wire format

        Only notes with at least one WRITTEN_ABOUT or TAG_IS_CONCEPT edge to an entity
        in entity_ids are included. Isolated notes (no entity edges in scope) are excluded.

        Acquires self._lock for all Kuzu calls (thread-safety per patterns.md).
        Returns ([], []) on any error (non-fatal).
        """
        if not entity_ids:
            return [], []

        # Build placeholder list for entity_ids (Kuzu does not support list params)
        placeholders = ", ".join(f"$eid{i}" for i in range(len(entity_ids)))
        params = {f"eid{i}": eid for i, eid in enumerate(entity_ids)}

        note_nodes: list[dict] = []
        note_edges: list[dict] = []

        try:
            with self._lock:
                # Kuzu does not support type() function in this version.
                # Run separate queries for WRITTEN_ABOUT and TAG_IS_CONCEPT.
                note_data: dict[str, dict] = {}

                # Query 1a: WRITTEN_ABOUT edges
                wa_result = self._conn.execute(
                    f"MATCH (n:Note)-[r:WRITTEN_ABOUT]->(e:Entity)"
                    f" WHERE e.id IN [{placeholders}]"
                    f" RETURN n.note_id, n.preview, e.id, r.confidence",
                    params,
                )
                while wa_result.has_next():
                    row = wa_result.get_next()
                    nid, preview, eid, confidence = row
                    if nid not in note_data:
                        note_data[nid] = {"preview": preview or "", "entity_edges": []}
                    note_data[nid]["entity_edges"].append(
                        {
                            "entity_id": eid,
                            "rel_type": "WRITTEN_ABOUT",
                            "confidence": float(confidence or 0.5),
                        }
                    )

                # Query 1b: TAG_IS_CONCEPT edges
                tic_result = self._conn.execute(
                    f"MATCH (n:Note)-[:TAG_IS_CONCEPT]->(e:Entity)"
                    f" WHERE e.id IN [{placeholders}]"
                    f" RETURN n.note_id, n.preview, e.id",
                    params,
                )
                while tic_result.has_next():
                    row = tic_result.get_next()
                    nid, preview, eid = row
                    if nid not in note_data:
                        note_data[nid] = {"preview": preview or "", "entity_edges": []}
                    note_data[nid]["entity_edges"].append(
                        {
                            "entity_id": eid,
                            "rel_type": "TAG_IS_CONCEPT",
                            "confidence": 1.0,
                        }
                    )

                if not note_data:
                    return [], []

                note_ids = list(note_data.keys())
                note_id_placeholders = ", ".join(f"$nid{i}" for i in range(len(note_ids)))
                note_params = {f"nid{i}": nid for i, nid in enumerate(note_ids)}

                # Query 2: LINKS_TO edges between notes in scope
                links_result = self._conn.execute(
                    f"MATCH (n1:Note)-[l:LINKS_TO]->(n2:Note)"
                    f" WHERE n1.note_id IN [{note_id_placeholders}]"
                    f" AND n2.note_id IN [{note_id_placeholders}]"
                    f" RETURN n1.note_id, n2.note_id, l.link_type",
                    note_params,
                )
                links_to_edges: list[dict] = []
                while links_result.has_next():
                    row = links_result.get_next()
                    src_nid, tgt_nid, link_type = row
                    links_to_edges.append(
                        {
                            "source": src_nid,
                            "target": tgt_nid,
                            "link_type": link_type or "",
                        }
                    )

            # Build note_nodes from collected data
            # Compute outgoing_link_count from entity_edges + LINKS_TO edges per note
            links_out: dict[str, int] = {}
            for le in links_to_edges:
                links_out[le["source"]] = links_out.get(le["source"], 0) + 1

            for nid, nd in note_data.items():
                entity_edge_count = len(nd["entity_edges"])
                total_out = entity_edge_count + links_out.get(nid, 0)
                preview = nd["preview"]
                note_nodes.append(
                    {
                        "id": nid,
                        "note_id": nid,
                        "label": preview[:40] if preview else nid[:40],
                        "type": "note",
                        "size": max(8, int((total_out**0.5) * 5)),
                        "outgoing_link_count": total_out,
                        "source_image_id": "",
                    }
                )
                # Add WRITTEN_ABOUT / TAG_IS_CONCEPT edges
                for ee in nd["entity_edges"]:
                    note_edges.append(
                        {
                            "source": nid,
                            "target": ee["entity_id"],
                            "weight": ee["confidence"],
                            "relation": ee["rel_type"],
                        }
                    )

            # Add LINKS_TO edges
            note_id_set = set(note_data.keys())
            for le in links_to_edges:
                if le["source"] in note_id_set and le["target"] in note_id_set:
                    note_edges.append(
                        {
                            "source": le["source"],
                            "target": le["target"],
                            "weight": 1.0,
                            "relation": "LINKS_TO",
                        }
                    )

            return note_nodes, note_edges

        except Exception:
            logger.warning("_get_note_nodes_for_entities failed (non-fatal)", exc_info=True)
            return [], []

    def _get_co_occurrence_edges(self, entity_ids: set[str], document_id: str) -> list[dict]:
        """Return CO_OCCURS edges among the given entity IDs for a document."""
        if not entity_ids:
            return []
        placeholders = ", ".join(f"$eid{i}" for i in range(len(entity_ids)))
        params = {f"eid{i}": eid for i, eid in enumerate(entity_ids)}
        params["did"] = document_id
        result = self._conn.execute(
            f"MATCH (a:Entity)-[r:CO_OCCURS]->(b:Entity)"
            f" WHERE a.id IN [{placeholders}] AND b.id IN [{placeholders}]"
            f" AND r.document_id = $did"
            f" RETURN a.id, b.id, r.weight",
            params,
        )
        edges = []
        while result.has_next():
            row = result.get_next()
            edges.append({"source": row[0], "target": row[1], "weight": row[2]})
        return edges


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
            node_id, name, node_type, document_id, source_image_id
        )

    def add_diagram_edge(
        self,
        from_node_id: str,
        to_node_id: str,
        edge_type: str,
        document_id: str,
        label: str | None = None,
    ) -> None:
        return self._tech.add_diagram_edge(
            from_node_id, to_node_id, edge_type, document_id, label
        )

    def add_depicts_edge(self, diagram_node_id: str, entity_id: str, document_id: str) -> None:
        return self._tech.add_depicts_edge(diagram_node_id, entity_id, document_id)

    def get_diagram_nodes_for_document(self, document_id: str) -> list[dict]:
        return self._tech.get_diagram_nodes_for_document(document_id)

    def get_diagram_edges_for_document(self, document_id: str) -> list[dict]:
        return self._tech.get_diagram_edges_for_document(document_id)

    def get_call_graph(self, document_id: str) -> dict:
        return self._tech.get_call_graph(document_id)
