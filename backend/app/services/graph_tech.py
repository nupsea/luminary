"""KuzuTechRepo: code-graph + diagram + tech-relation edges (S135 / S140 / S160).

Methods are lifted verbatim from `KuzuService` so query strings, error
handling, and return shapes are unchanged. `KuzuService` keeps the
public method names and delegates to this repo for back-compat.

Covers six edge / node types:
- CALLS                 function-to-function call edges (code docs)
- IMPLEMENTS / EXTENDS / USES / REPLACES / DEPENDS_ON   tech relations
- VERSION_OF            entity-version provenance (e.g. Python 3.12 → Python)
- DiagramNode           extracted diagram nodes (S140)
- diagram edges         arrows / containment between diagram nodes
- DEPICTS               diagram-node-to-Entity links

Independent of view / prereq / concept repos -- only depends on
KuzuConnection.
"""

from __future__ import annotations

import logging

from app.services.graph_connection import KuzuConnection

logger = logging.getLogger(__name__)


class KuzuTechRepo:
    def __init__(self, connection: KuzuConnection) -> None:
        self._conn = connection.conn

    def add_call_edge(self, caller_id: str, callee_id: str, document_id: str) -> None:
        """Add a CALLS edge from caller Entity to callee Entity for a code document."""
        # Avoid duplicate edges for the same (caller, callee, document_id)
        result = self._conn.execute(
            "MATCH (a:Entity {id: $cid})-[r:CALLS]->(b:Entity {id: $eid})"
            " WHERE r.document_id = $did RETURN r",
            {"cid": caller_id, "eid": callee_id, "did": document_id},
        )
        if not result.has_next():
            self._conn.execute(
                "MATCH (a:Entity {id: $cid}), (b:Entity {id: $eid})"
                " CREATE (a)-[:CALLS {document_id: $did}]->(b)",
                {"cid": caller_id, "eid": callee_id, "did": document_id},
            )

    # -------------------------------------------------------------------------
    # Tech relation edges (S135)
    # -------------------------------------------------------------------------

    _TECH_REL_TYPES: frozenset[str] = frozenset(
        {
            "IMPLEMENTS",
            "EXTENDS",
            "USES",
            "REPLACES",
            "DEPENDS_ON",
        }
    )

    def add_tech_relation(
        self,
        entity_id_a: str,
        entity_id_b: str,
        relation_label: str,
        document_id: str,
    ) -> None:
        """Create a directed tech relation edge from entity_id_a to entity_id_b.

        relation_label must be one of: IMPLEMENTS, EXTENDS, USES, REPLACES, DEPENDS_ON.
        Idempotent: if the edge already exists for this document, it is left unchanged.
        Raises ValueError for unknown relation labels.
        """
        if relation_label not in self._TECH_REL_TYPES:
            raise ValueError(
                f"Unknown tech relation label: {relation_label!r}."
                f" Must be one of {sorted(self._TECH_REL_TYPES)}"
            )
        # Check existence first (idempotency)
        # Kuzu does not support parameterized rel-type names, so use explicit branches.
        if relation_label == "IMPLEMENTS":
            result = self._conn.execute(
                "MATCH (a:Entity {id: $aid})-[r:IMPLEMENTS]->(b:Entity {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
            )
            if not result.has_next():
                self._conn.execute(
                    "MATCH (a:Entity {id: $aid}), (b:Entity {id: $bid})"
                    " CREATE (a)-[:IMPLEMENTS {document_id: $did}]->(b)",
                    {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
                )
        elif relation_label == "EXTENDS":
            result = self._conn.execute(
                "MATCH (a:Entity {id: $aid})-[r:EXTENDS]->(b:Entity {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
            )
            if not result.has_next():
                self._conn.execute(
                    "MATCH (a:Entity {id: $aid}), (b:Entity {id: $bid})"
                    " CREATE (a)-[:EXTENDS {document_id: $did}]->(b)",
                    {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
                )
        elif relation_label == "USES":
            result = self._conn.execute(
                "MATCH (a:Entity {id: $aid})-[r:USES]->(b:Entity {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
            )
            if not result.has_next():
                self._conn.execute(
                    "MATCH (a:Entity {id: $aid}), (b:Entity {id: $bid})"
                    " CREATE (a)-[:USES {document_id: $did}]->(b)",
                    {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
                )
        elif relation_label == "REPLACES":
            result = self._conn.execute(
                "MATCH (a:Entity {id: $aid})-[r:REPLACES]->(b:Entity {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
            )
            if not result.has_next():
                self._conn.execute(
                    "MATCH (a:Entity {id: $aid}), (b:Entity {id: $bid})"
                    " CREATE (a)-[:REPLACES {document_id: $did}]->(b)",
                    {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
                )
        elif relation_label == "DEPENDS_ON":
            result = self._conn.execute(
                "MATCH (a:Entity {id: $aid})-[r:DEPENDS_ON]->(b:Entity {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
            )
            if not result.has_next():
                self._conn.execute(
                    "MATCH (a:Entity {id: $aid}), (b:Entity {id: $bid})"
                    " CREATE (a)-[:DEPENDS_ON {document_id: $did}]->(b)",
                    {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
                )

    def add_version_of(
        self, versioned_entity_id: str, base_entity_id: str, document_id: str
    ) -> None:
        """Create a VERSION_OF edge from a versioned entity to its major-version base.

        Example: 'Python 3.13' -[VERSION_OF]-> 'Python 3'
        Idempotent: if the edge already exists, it is left unchanged.
        """
        result = self._conn.execute(
            "MATCH (a:Entity {id: $vid})-[r:VERSION_OF]->(b:Entity {id: $bid})"
            " WHERE r.document_id = $did RETURN r",
            {"vid": versioned_entity_id, "bid": base_entity_id, "did": document_id},
        )
        if not result.has_next():
            self._conn.execute(
                "MATCH (a:Entity {id: $vid}), (b:Entity {id: $bid})"
                " CREATE (a)-[:VERSION_OF {document_id: $did}]->(b)",
                {"vid": versioned_entity_id, "bid": base_entity_id, "did": document_id},
            )

    # Diagram-derived node types (S136) -- queried from DiagramNode table, not Entity
    _DIAGRAM_NODE_TYPES: frozenset[str] = frozenset({"COMPONENT", "ACTOR", "ENTITY_DM", "STEP"})

    def get_entities_by_type(self, document_id: str, entity_type: str) -> list[dict]:
        """Return entities of a specific type for a document.

        For diagram node types (COMPONENT, ACTOR, ENTITY_DM, STEP), queries the
        DiagramNode table filtered by node_type. For all other types, queries Entity.
        Returns list of {id, name, type, frequency} dicts.
        Returns [] on any error (non-fatal).
        """
        if entity_type in self._DIAGRAM_NODE_TYPES:
            return self._get_diagram_nodes_by_type(document_id, entity_type)
        try:
            result = self._conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did})"
                " WHERE e.type = $etype"
                " RETURN e.id, e.name, e.type, e.frequency",
                {"did": document_id, "etype": entity_type},
            )
            entities: list[dict] = []
            while result.has_next():
                row = result.get_next()
                entities.append(
                    {
                        "id": row[0],
                        "name": row[1],
                        "type": row[2],
                        "frequency": int(row[3] or 1),
                    }
                )
            return entities
        except Exception:
            logger.debug("get_entities_by_type failed", exc_info=True)
            return []

    def _get_diagram_nodes_by_type(self, document_id: str, node_type: str) -> list[dict]:
        """Return DiagramNode rows of a specific node_type for a document.

        Returns list of {id, name, type, frequency} dicts (same shape as get_entities_by_type).
        Returns [] on any error.
        """
        try:
            result = self._conn.execute(
                "MATCH (n:DiagramNode)"
                " WHERE n.document_id = $did AND n.node_type = $ntype"
                " RETURN n.id, n.name, n.node_type, n.frequency",
                {"did": document_id, "ntype": node_type},
            )
            nodes: list[dict] = []
            while result.has_next():
                row = result.get_next()
                nodes.append(
                    {
                        "id": row[0],
                        "name": row[1],
                        "type": row[2],
                        "frequency": int(row[3] or 1),
                    }
                )
            return nodes
        except Exception:
            logger.debug("_get_diagram_nodes_by_type failed", exc_info=True)
            return []

    # -------------------------------------------------------------------------
    # Diagram-derived nodes and edges (S136)
    # -------------------------------------------------------------------------

    def upsert_diagram_node(
        self,
        node_id: str,
        name: str,
        node_type: str,
        source_image_id: str,
        document_id: str,
    ) -> None:
        """Create or increment frequency for a DiagramNode.

        node_id should be deterministic: f"{source_image_id}:{name.lower()}"
        Idempotent: re-running increments frequency.
        """
        result = self._conn.execute(
            "MATCH (n:DiagramNode {id: $id}) RETURN n.frequency",
            {"id": node_id},
        )
        if result.has_next():
            row = result.get_next()
            freq = (row[0] or 0) + 1
            self._conn.execute(
                "MATCH (n:DiagramNode {id: $id}) SET n.frequency = $freq",
                {"id": node_id, "freq": freq},
            )
        else:
            self._conn.execute(
                "CREATE (:DiagramNode {id: $id, name: $name, node_type: $ntype,"
                " source_image_id: $siid, document_id: $did, frequency: 1})",
                {
                    "id": node_id,
                    "name": name,
                    "ntype": node_type,
                    "siid": source_image_id,
                    "did": document_id,
                },
            )

    def add_diagram_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        document_id: str,
        **properties: str,
    ) -> None:
        """Create a diagram edge between two DiagramNode rows.

        edge_type must be one of: CONNECTS_TO, STORES_IN, SENDS_TO, HAS_FIELD,
        REFERENCES_DM, LEADS_TO.
        Idempotent: skips creation if an identical edge already exists.
        Kuzu does not support parameterised relation types, so explicit branches are used.
        """
        # Nodes referenced by from/to must exist; caller guarantees this
        if edge_type == "CONNECTS_TO":
            r = self._conn.execute(
                "MATCH (a:DiagramNode {id: $aid})-[r:CONNECTS_TO]->(b:DiagramNode {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": from_id, "bid": to_id, "did": document_id},
            )
            if not r.has_next():
                label = properties.get("label", "")
                self._conn.execute(
                    "MATCH (a:DiagramNode {id: $aid}), (b:DiagramNode {id: $bid})"
                    " CREATE (a)-[:CONNECTS_TO {document_id: $did, label: $lbl}]->(b)",
                    {"aid": from_id, "bid": to_id, "did": document_id, "lbl": label},
                )
        elif edge_type == "STORES_IN":
            r = self._conn.execute(
                "MATCH (a:DiagramNode {id: $aid})-[r:STORES_IN]->(b:DiagramNode {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": from_id, "bid": to_id, "did": document_id},
            )
            if not r.has_next():
                self._conn.execute(
                    "MATCH (a:DiagramNode {id: $aid}), (b:DiagramNode {id: $bid})"
                    " CREATE (a)-[:STORES_IN {document_id: $did}]->(b)",
                    {"aid": from_id, "bid": to_id, "did": document_id},
                )
        elif edge_type == "SENDS_TO":
            r = self._conn.execute(
                "MATCH (a:DiagramNode {id: $aid})-[r:SENDS_TO]->(b:DiagramNode {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": from_id, "bid": to_id, "did": document_id},
            )
            if not r.has_next():
                message = properties.get("message", "")
                self._conn.execute(
                    "MATCH (a:DiagramNode {id: $aid}), (b:DiagramNode {id: $bid})"
                    " CREATE (a)-[:SENDS_TO {document_id: $did, message: $msg}]->(b)",
                    {"aid": from_id, "bid": to_id, "did": document_id, "msg": message},
                )
        elif edge_type == "HAS_FIELD":
            r = self._conn.execute(
                "MATCH (a:DiagramNode {id: $aid})-[r:HAS_FIELD]->(b:DiagramNode {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": from_id, "bid": to_id, "did": document_id},
            )
            if not r.has_next():
                self._conn.execute(
                    "MATCH (a:DiagramNode {id: $aid}), (b:DiagramNode {id: $bid})"
                    " CREATE (a)-[:HAS_FIELD {document_id: $did}]->(b)",
                    {"aid": from_id, "bid": to_id, "did": document_id},
                )
        elif edge_type == "REFERENCES_DM":
            r = self._conn.execute(
                "MATCH (a:DiagramNode {id: $aid})-[r:REFERENCES_DM]->(b:DiagramNode {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": from_id, "bid": to_id, "did": document_id},
            )
            if not r.has_next():
                self._conn.execute(
                    "MATCH (a:DiagramNode {id: $aid}), (b:DiagramNode {id: $bid})"
                    " CREATE (a)-[:REFERENCES_DM {document_id: $did}]->(b)",
                    {"aid": from_id, "bid": to_id, "did": document_id},
                )
        elif edge_type == "LEADS_TO":
            r = self._conn.execute(
                "MATCH (a:DiagramNode {id: $aid})-[r:LEADS_TO]->(b:DiagramNode {id: $bid})"
                " WHERE r.document_id = $did RETURN r",
                {"aid": from_id, "bid": to_id, "did": document_id},
            )
            if not r.has_next():
                condition = properties.get("condition", "")
                self._conn.execute(
                    "MATCH (a:DiagramNode {id: $aid}), (b:DiagramNode {id: $bid})"
                    " CREATE (a)-[:LEADS_TO {document_id: $did, condition: $cond}]->(b)",
                    {"aid": from_id, "bid": to_id, "did": document_id, "cond": condition},
                )
        else:
            logger.warning("add_diagram_edge: unknown edge_type=%r, skipping", edge_type)

    def add_depicts_edge(self, diagram_node_id: str, entity_id: str, document_id: str) -> None:
        """Create a DEPICTS edge from a DiagramNode to an Entity.

        DEPICTS represents that a diagram component visually depicts a known entity
        (e.g. COMPONENT 'PostgreSQL' depicts LIBRARY Entity 'postgresql').
        Idempotent: if the edge already exists, it is left unchanged.
        """
        r = self._conn.execute(
            "MATCH (d:DiagramNode {id: $did_n})-[r:DEPICTS]->(e:Entity {id: $eid})"
            " WHERE r.document_id = $did RETURN r",
            {"did_n": diagram_node_id, "eid": entity_id, "did": document_id},
        )
        if not r.has_next():
            self._conn.execute(
                "MATCH (d:DiagramNode {id: $did_n}), (e:Entity {id: $eid})"
                " CREATE (d)-[:DEPICTS {document_id: $did}]->(e)",
                {"did_n": diagram_node_id, "eid": entity_id, "did": document_id},
            )

    def get_diagram_nodes_for_document(self, document_id: str) -> list[dict]:
        """Return all DiagramNode rows for a document.

        Returns list of dicts: {id, name, type, size, source_image_id, mention_count}
        where type = node_type and size = frequency.
        Returns [] on any Kuzu error.
        """
        try:
            result = self._conn.execute(
                "MATCH (n:DiagramNode) WHERE n.document_id = $did"
                " RETURN n.id, n.name, n.node_type, n.frequency, n.source_image_id",
                {"did": document_id},
            )
            nodes: list[dict] = []
            while result.has_next():
                row = result.get_next()
                nodes.append(
                    {
                        "id": row[0],
                        "label": row[1],
                        "type": row[2],
                        "size": int(row[3] or 1),
                        "source_image_id": row[4] or "",
                        "mention_count": int(row[3] or 1),
                    }
                )
            return nodes
        except Exception:
            logger.debug("get_diagram_nodes_for_document failed", exc_info=True)
            return []

    def get_diagram_edges_for_document(self, document_id: str) -> list[dict]:
        """Return all diagram edges for a document (across all diagram edge types).

        Returns list of {source, target, weight, relation} dicts.
        Returns [] on any error.
        """
        edges: list[dict] = []
        _DIAGRAM_RELS = (
            "CONNECTS_TO",
            "STORES_IN",
            "SENDS_TO",
            "HAS_FIELD",
            "REFERENCES_DM",
            "LEADS_TO",
        )
        for rel in _DIAGRAM_RELS:
            try:
                result = self._conn.execute(
                    f"MATCH (a:DiagramNode)-[r:{rel}]->(b:DiagramNode)"
                    f" WHERE r.document_id = $did"
                    f" RETURN a.id, b.id",
                    {"did": document_id},
                )
                while result.has_next():
                    row = result.get_next()
                    edges.append(
                        {
                            "source": row[0],
                            "target": row[1],
                            "weight": 1.0,
                            "relation": rel,
                        }
                    )
            except Exception:
                logger.debug("get_diagram_edges_for_document failed for %s", rel, exc_info=True)
        return edges

    def _get_tech_relation_edges(self, entity_ids: set[str], document_id: str) -> list[dict]:
        """Return tech relation edges (IMPLEMENTS, EXTENDS, USES, REPLACES, DEPENDS_ON)
        among the given entity IDs for a document."""
        if not entity_ids:
            return []
        placeholders = ", ".join(f"$eid{i}" for i in range(len(entity_ids)))
        params = {f"eid{i}": eid for i, eid in enumerate(entity_ids)}
        params["did"] = document_id
        edges: list[dict] = []
        for rel in ("IMPLEMENTS", "EXTENDS", "USES", "REPLACES", "DEPENDS_ON"):
            try:
                result = self._conn.execute(
                    f"MATCH (a:Entity)-[r:{rel}]->(b:Entity)"
                    f" WHERE a.id IN [{placeholders}] AND b.id IN [{placeholders}]"
                    f" AND r.document_id = $did"
                    f" RETURN a.id, b.id",
                    params,
                )
                while result.has_next():
                    row = result.get_next()
                    edges.append(
                        {
                            "source": row[0],
                            "target": row[1],
                            "weight": 1.0,
                            "relation": rel,
                        }
                    )
            except Exception:
                logger.debug("_get_tech_relation_edges failed for %s", rel, exc_info=True)
        return edges

    def get_call_graph(self, document_id: str) -> dict:
        """Return call graph nodes and edges for a code document."""
        result = self._conn.execute(
            "MATCH (a:Entity)-[r:CALLS]->(b:Entity)"
            " WHERE r.document_id = $did"
            " RETURN a.id, a.name, a.type, a.frequency, b.id, b.name, b.type, b.frequency",
            {"did": document_id},
        )
        nodes_map: dict[str, dict] = {}
        edges: list[dict] = []
        while result.has_next():
            row = result.get_next()
            aid, aname, atype, afreq, bid, bname, btype, bfreq = row
            if aid not in nodes_map:
                nodes_map[aid] = {
                    "id": aid,
                    "label": aname,
                    "type": atype or "FUNCTION",
                    "size": afreq or 1,
                }
            if bid not in nodes_map:
                nodes_map[bid] = {
                    "id": bid,
                    "label": bname,
                    "type": btype or "FUNCTION",
                    "size": bfreq or 1,
                }
            edges.append({"source": aid, "target": bid, "weight": 1.0})
        return {"nodes": list(nodes_map.values()), "edges": edges}
