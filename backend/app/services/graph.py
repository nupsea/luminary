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
import threading
from pathlib import Path

import kuzu

from app.config import get_settings

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
        db_path = str(Path(data_dir).expanduser() / "graph.kuzu")
        self._db = kuzu.Database(db_path)
        self._conn = kuzu.Connection(self._db)
        # Kuzu connection is not thread-safe. Serialise all _conn.execute() calls.
        self._lock = threading.Lock()
        self._create_schema()
        logger.info("KuzuService initialized", extra={"db_path": db_path})

    def _create_schema(self) -> None:
        """Create node and edge tables if they do not exist."""
        stmts = [
            # Node tables
            "CREATE NODE TABLE IF NOT EXISTS Entity("
            "id STRING PRIMARY KEY, name STRING, type STRING, frequency INT64, aliases STRING)",
            "CREATE NODE TABLE IF NOT EXISTS Document("
            "id STRING PRIMARY KEY, title STRING, content_type STRING)",
            # Diagram-derived node table (S136) -- must be created before DEPICTS edge
            "CREATE NODE TABLE IF NOT EXISTS DiagramNode("
            "id STRING PRIMARY KEY, name STRING, node_type STRING,"
            " source_image_id STRING, document_id STRING, frequency INT64)",
            # Edge tables
            "CREATE REL TABLE IF NOT EXISTS MENTIONED_IN("
            "FROM Entity TO Document, count INT64)",
            "CREATE REL TABLE IF NOT EXISTS CO_OCCURS("
            "FROM Entity TO Entity, weight FLOAT, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS RELATED_TO("
            "FROM Entity TO Entity, relation_label STRING, confidence FLOAT)",
            "CREATE REL TABLE IF NOT EXISTS CALLS("
            "FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS PREREQUISITE_OF("
            "FROM Entity TO Entity, document_id STRING, confidence FLOAT)",
            # Tech relation edges (S135)
            "CREATE REL TABLE IF NOT EXISTS IMPLEMENTS("
            "FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS EXTENDS("
            "FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS USES("
            "FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS REPLACES("
            "FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS DEPENDS_ON("
            "FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS VERSION_OF("
            "FROM Entity TO Entity, document_id STRING)",
            # Diagram-derived edge tables (S136)
            "CREATE REL TABLE IF NOT EXISTS CONNECTS_TO("
            "FROM DiagramNode TO DiagramNode, document_id STRING, label STRING)",
            "CREATE REL TABLE IF NOT EXISTS STORES_IN("
            "FROM DiagramNode TO DiagramNode, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS SENDS_TO("
            "FROM DiagramNode TO DiagramNode, document_id STRING, message STRING)",
            "CREATE REL TABLE IF NOT EXISTS HAS_FIELD("
            "FROM DiagramNode TO DiagramNode, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS REFERENCES_DM("
            "FROM DiagramNode TO DiagramNode, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS LEADS_TO("
            "FROM DiagramNode TO DiagramNode, document_id STRING, condition STRING)",
            # DEPICTS: links a diagram-derived node to an existing Entity (S136)
            "CREATE REL TABLE IF NOT EXISTS DEPICTS("
            "FROM DiagramNode TO Entity, document_id STRING)",
            # SAME_CONCEPT: cross-document concept links (S141)
            # Uses INT64 for contradiction (not BOOLEAN) for Kuzu compatibility
            "CREATE REL TABLE IF NOT EXISTS SAME_CONCEPT("
            "FROM Entity TO Entity,"
            " source_doc_id STRING, target_doc_id STRING,"
            " confidence FLOAT, contradiction INT64,"
            " contradiction_note STRING, prefer_source STRING)",
            # Note graph (S163) -- Note nodes + edges to Entity and Document
            "CREATE NODE TABLE IF NOT EXISTS Note("
            "id STRING PRIMARY KEY, note_id STRING, preview STRING, created_at STRING)",
            "CREATE REL TABLE IF NOT EXISTS WRITTEN_ABOUT("
            "FROM Note TO Entity, confidence FLOAT)",
            "CREATE REL TABLE IF NOT EXISTS TAG_IS_CONCEPT("
            "FROM Note TO Entity, tag STRING)",
            "CREATE REL TABLE IF NOT EXISTS DERIVED_FROM("
            "FROM Note TO Document)",
            # Zettelkasten links (S171) -- explicit typed note-to-note connections
            "CREATE REL TABLE IF NOT EXISTS LINKS_TO("
            "FROM Note TO Note, link_type STRING)",
        ]
        for stmt in stmts:
            self._conn.execute(stmt)

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
        """Create or update an Entity node.

        Args:
            entity_id:   UUID primary key.
            name:        Canonical surface form (lowercase).
            entity_type: GLiNER entity type label.
            aliases:     Non-canonical surface forms that resolved to this entity.
                         Written as a pipe-delimited string in the `aliases` column.
                         Silently skipped on databases that pre-date S86 (no column).
        """
        aliases_str = "|".join(aliases) if aliases else ""

        result = self._conn.execute(
            "MATCH (e:Entity {id: $id}) RETURN e.frequency",
            {"id": entity_id},
        )
        if result.has_next():
            row = result.get_next()
            freq = (row[0] or 0) + 1
            self._conn.execute(
                "MATCH (e:Entity {id: $id})"
                " SET e.frequency = $freq, e.name = $name, e.type = $type",
                {"id": entity_id, "freq": freq, "name": name, "type": entity_type},
            )
            if aliases_str:
                try:
                    self._conn.execute(
                        "MATCH (e:Entity {id: $id}) SET e.aliases = $a",
                        {"id": entity_id, "a": aliases_str},
                    )
                except Exception:
                    logger.debug("aliases column absent on Entity, skipping aliases update")
        else:
            try:
                self._conn.execute(
                    "CREATE (:Entity {id: $id, name: $name, type: $type,"
                    " frequency: 1, aliases: $a})",
                    {"id": entity_id, "name": name, "type": entity_type, "a": aliases_str},
                )
            except Exception:
                # Fallback for databases that pre-date the aliases column (S86).
                self._conn.execute(
                    "CREATE (:Entity {id: $id, name: $name, type: $type, frequency: 1})",
                    {"id": entity_id, "name": name, "type": entity_type},
                )

    def get_entities_by_type_for_document(self, document_id: str) -> dict[str, list[str]]:
        """Return existing canonical names grouped by entity type for *document_id*.

        Used by the disambiguation pipeline to populate the initial lookup pool
        before calling canonicalize_batch on newly extracted entities.

        Returns an empty dict on any Kuzu error (non-fatal).
        """
        try:
            result = self._conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did})"
                " RETURN e.name, e.type",
                {"did": document_id},
            )
            by_type: dict[str, list[str]] = {}
            while result.has_next():
                row = result.get_next()
                name, etype = row[0], row[1]
                if name and etype:
                    by_type.setdefault(etype, []).append(name)
            return by_type
        except Exception:
            logger.debug(
                "get_entities_by_type_for_document failed, returning empty",
                exc_info=True,
            )
            return {}

    def upsert_document(self, doc_id: str, title: str, content_type: str) -> None:
        """Create or update a Document node."""
        result = self._conn.execute(
            "MATCH (d:Document {id: $id}) RETURN d.id",
            {"id": doc_id},
        )
        if result.has_next():
            self._conn.execute(
                "MATCH (d:Document {id: $id}) SET d.title = $title, d.content_type = $ct",
                {"id": doc_id, "title": title, "ct": content_type},
            )
        else:
            self._conn.execute(
                "CREATE (:Document {id: $id, title: $title, content_type: $ct})",
                {"id": doc_id, "title": title, "ct": content_type},
            )

    def add_mention(self, entity_id: str, document_id: str) -> None:
        """Create a MENTIONED_IN edge if it does not already exist."""
        result = self._conn.execute(
            "MATCH (e:Entity {id: $eid})-[r:MENTIONED_IN]->(d:Document {id: $did}) RETURN r.count",
            {"eid": entity_id, "did": document_id},
        )
        if result.has_next():
            row = result.get_next()
            new_count = (row[0] or 0) + 1
            self._conn.execute(
                "MATCH (e:Entity {id: $eid})-[r:MENTIONED_IN]->(d:Document {id: $did})"
                " SET r.count = $c",
                {"eid": entity_id, "did": document_id, "c": new_count},
            )
        else:
            self._conn.execute(
                "MATCH (e:Entity {id: $eid}), (d:Document {id: $did})"
                " CREATE (e)-[:MENTIONED_IN {count: 1}]->(d)",
                {"eid": entity_id, "did": document_id},
            )

    def add_co_occurrence(
        self, entity_id_a: str, entity_id_b: str, document_id: str
    ) -> None:
        """Create or increment a CO_OCCURS edge between two entities."""
        result = self._conn.execute(
            "MATCH (a:Entity {id: $aid})-[r:CO_OCCURS]->(b:Entity {id: $bid})"
            " WHERE r.document_id = $did RETURN r.weight",
            {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
        )
        if result.has_next():
            row = result.get_next()
            new_weight = (row[0] or 0.0) + 1.0
            self._conn.execute(
                "MATCH (a:Entity {id: $aid})-[r:CO_OCCURS]->(b:Entity {id: $bid})"
                " WHERE r.document_id = $did SET r.weight = $w",
                {"aid": entity_id_a, "bid": entity_id_b, "did": document_id, "w": new_weight},
            )
        else:
            self._conn.execute(
                "MATCH (a:Entity {id: $aid}), (b:Entity {id: $bid})"
                " CREATE (a)-[:CO_OCCURS {weight: 1.0, document_id: $did}]->(b)",
                {"aid": entity_id_a, "bid": entity_id_b, "did": document_id},
            )

    def add_relation(
        self, entity_id_a: str, entity_id_b: str, relation_label: str, confidence: float = 1.0
    ) -> None:
        """Create a RELATED_TO edge from entity_id_a to entity_id_b.

        Idempotent: if the edge already exists, it is left unchanged.
        """
        result = self._conn.execute(
            "MATCH (a:Entity {id: $aid})-[r:RELATED_TO]->(b:Entity {id: $bid}) RETURN r.confidence",
            {"aid": entity_id_a, "bid": entity_id_b},
        )
        if not result.has_next():
            self._conn.execute(
                "MATCH (a:Entity {id: $aid}), (b:Entity {id: $bid})"
                " CREATE (a)-[:RELATED_TO {relation_label: $rl, confidence: $conf}]->(b)",
                {"aid": entity_id_a, "bid": entity_id_b, "rl": relation_label, "conf": confidence},
            )

    def get_related_entity_pairs_for_document(
        self, document_id: str, limit: int = 5
    ) -> list[tuple[str, str, str, float]]:
        """Return entity pairs connected by RELATED_TO edges for a given document.

        Returns list of (name_a, name_b, relation_label, confidence), ordered by
        confidence descending, capped at *limit*.  Returns [] if no edges exist
        or on any Kuzu error.
        """
        try:
            result = self._conn.execute(
                f"MATCH (e1:Entity)-[:MENTIONED_IN]->(d:Document {{id: $did}}),"
                f" (e2:Entity)-[:MENTIONED_IN]->(d),"
                f" (e1)-[r:RELATED_TO]->(e2)"
                f" RETURN e1.name, e2.name, r.relation_label, r.confidence"
                f" ORDER BY r.confidence DESC LIMIT {int(limit)}",
                {"did": document_id},
            )
            pairs: list[tuple[str, str, str, float]] = []
            while result.has_next():
                row = result.get_next()
                name_a, name_b, label, conf = row[0], row[1], row[2], row[3]
                if name_a and name_b:
                    pairs.append((name_a, name_b, label or "", float(conf or 0.0)))
            return pairs
        except Exception:
            logger.debug(
                "get_related_entity_pairs_for_document failed, returning empty", exc_info=True
            )
            return []

    def get_co_occurring_pairs_for_document(
        self, document_id: str, limit: int = 5
    ) -> list[tuple[str, str, float]]:
        """Return top-K entity pairs by CO_OCCURS edge weight for a given document.

        Returns list of (name_a, name_b, weight), ordered by weight descending,
        capped at *limit*. Returns [] on any Kuzu error or when no CO_OCCURS edges exist.

        Used as a fallback by generate_from_graph when no RELATED_TO edges exist.
        """
        try:
            result = self._conn.execute(
                f"MATCH (a:Entity)-[:MENTIONED_IN]->(d:Document {{id: $did}}),"
                f" (b:Entity)-[:MENTIONED_IN]->(d),"
                f" (a)-[r:CO_OCCURS]->(b)"
                f" WHERE r.document_id = $did"
                f" RETURN a.name, b.name, r.weight"
                f" ORDER BY r.weight DESC LIMIT {int(limit)}",
                {"did": document_id},
            )
            pairs: list[tuple[str, str, float]] = []
            while result.has_next():
                row = result.get_next()
                name_a, name_b, weight = row[0], row[1], row[2]
                if name_a and name_b:
                    pairs.append((name_a, name_b, float(weight or 0.0)))
            return pairs
        except Exception:
            logger.debug(
                "get_co_occurring_pairs_for_document failed, returning empty", exc_info=True
            )
            return []

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
        """Create a PREREQUISITE_OF edge from dependent to prerequisite.

        Idempotent: if an edge with the same (dependent, prerequisite, document_id)
        already exists, it is left unchanged.
        """
        result = self._conn.execute(
            "MATCH (a:Entity {id: $dep})-[r:PREREQUISITE_OF]->(b:Entity {id: $pre})"
            " WHERE r.document_id = $did RETURN r.confidence",
            {"dep": dependent_id, "pre": prerequisite_id, "did": document_id},
        )
        if not result.has_next():
            self._conn.execute(
                "MATCH (a:Entity {id: $dep}), (b:Entity {id: $pre})"
                " CREATE (a)-[:PREREQUISITE_OF {document_id: $did, confidence: $conf}]->(b)",
                {
                    "dep": dependent_id, "pre": prerequisite_id,
                    "did": document_id, "conf": confidence,
                },
            )

    def get_prerequisite_edges_for_document(self, document_id: str) -> list[dict]:
        """Return all PREREQUISITE_OF edges for a document.

        Returns list of dicts:
            {from_entity, to_entity, from_id, to_id, confidence}
        """
        try:
            result = self._conn.execute(
                "MATCH (a:Entity)-[:MENTIONED_IN]->(d:Document {id: $did}),"
                " (b:Entity)-[:MENTIONED_IN]->(d),"
                " (a)-[r:PREREQUISITE_OF]->(b)"
                " WHERE r.document_id = $did"
                " RETURN a.name, b.name, a.id, b.id, r.confidence",
                {"did": document_id},
            )
            edges: list[dict] = []
            while result.has_next():
                row = result.get_next()
                edges.append({
                    "from_entity": row[0],
                    "to_entity": row[1],
                    "from_id": row[2],
                    "to_id": row[3],
                    "confidence": float(row[4] or 1.0),
                })
            return edges
        except Exception:
            logger.debug("get_prerequisite_edges_for_document failed", exc_info=True)
            return []

    def add_prerequisite_with_section(
        self,
        dependent_id: str,
        prerequisite_id: str,
        document_id: str,
        confidence: float,
        source_section_id: str,
    ) -> None:
        """Create a PREREQUISITE_OF edge with source_section_id; fallback for old DBs.

        Idempotent: if the edge already exists, it is left unchanged.
        Falls back to 2-property form for databases created before S139 (no source_section_id).
        """
        result = self._conn.execute(
            "MATCH (a:Entity {id: $dep})-[r:PREREQUISITE_OF]->(b:Entity {id: $pre})"
            " WHERE r.document_id = $did RETURN r.confidence",
            {"dep": dependent_id, "pre": prerequisite_id, "did": document_id},
        )
        if not result.has_next():
            try:
                self._conn.execute(
                    "MATCH (a:Entity {id: $dep}), (b:Entity {id: $pre})"
                    " CREATE (a)-[:PREREQUISITE_OF {document_id: $did,"
                    " confidence: $conf, source_section_id: $sid}]->(b)",
                    {
                        "dep": dependent_id, "pre": prerequisite_id,
                        "did": document_id, "conf": confidence, "sid": source_section_id,
                    },
                )
            except Exception:
                # Old DB without source_section_id column -- fall back to 2-property form
                logger.debug(
                    "add_prerequisite_with_section: source_section_id absent, fallback",
                    exc_info=True,
                )
                self._conn.execute(
                    "MATCH (a:Entity {id: $dep}), (b:Entity {id: $pre})"
                    " CREATE (a)-[:PREREQUISITE_OF {document_id: $did, confidence: $conf}]->(b)",
                    {"dep": dependent_id, "pre": prerequisite_id,
                     "did": document_id, "conf": confidence},
                )

    def has_prerequisite_edges(self, document_id: str) -> bool:
        """Return True if the document has any PREREQUISITE_OF edges."""
        try:
            result = self._conn.execute(
                "MATCH (a:Entity)-[r:PREREQUISITE_OF]->(b:Entity)"
                " WHERE r.document_id = $did RETURN r LIMIT 1",
                {"did": document_id},
            )
            return result.has_next()
        except Exception:
            return False

    def get_entry_point_concepts(self, document_id: str, limit: int = 10) -> list[str]:
        """Return entity names that have no outgoing PREREQUISITE_OF edges for this document.

        These are root concepts (no listed prerequisites) that ARE referenced as
        prerequisites by other concepts -- valid entry-point starting concepts.
        Returns at most `limit` names, ordered by MENTIONED_IN count desc.
        """
        try:
            # All concepts with MENTIONED_IN this doc
            all_result = self._conn.execute(
                "MATCH (e:Entity)-[r:MENTIONED_IN]->(d:Document {id: $did})"
                " RETURN e.id, e.name, r.count",
                {"did": document_id},
            )
            all_entities: dict[str, tuple[str, int]] = {}  # id -> (name, count)
            while all_result.has_next():
                row = all_result.get_next()
                all_entities[row[0]] = (row[1], int(row[2] or 1))

            # Concepts with outgoing PREREQUISITE_OF edges (they have prerequisites)
            dep_result = self._conn.execute(
                "MATCH (a:Entity)-[r:PREREQUISITE_OF]->(b:Entity)"
                " WHERE r.document_id = $did RETURN DISTINCT a.id",
                {"did": document_id},
            )
            has_prereqs: set[str] = set()
            while dep_result.has_next():
                has_prereqs.add(dep_result.get_next()[0])

            # Concepts pointed to as prerequisites (targets in the graph)
            referenced_result = self._conn.execute(
                "MATCH (a:Entity)-[r:PREREQUISITE_OF]->(b:Entity)"
                " WHERE r.document_id = $did RETURN DISTINCT b.id",
                {"did": document_id},
            )
            referenced: set[str] = set()
            while referenced_result.has_next():
                referenced.add(referenced_result.get_next()[0])

            # Entry points: in the doc, no outgoing prereq edges, AND are referenced as prereqs
            entry = [
                (eid, name, count)
                for eid, (name, count) in all_entities.items()
                if eid not in has_prereqs and eid in referenced
            ]
            entry.sort(key=lambda x: x[2], reverse=True)
            return [name for _, name, _ in entry[:limit]]
        except Exception:
            logger.debug("get_entry_point_concepts failed", exc_info=True)
            return []

    def get_prerequisite_edges_for_graph(self, document_id: str) -> list[dict]:
        """Return PREREQUISITE_OF edges in the graph wire format for Viz rendering.

        Returns list of {source, target, weight, relation} dicts.
        """
        raw = self.get_prerequisite_edges_for_document(document_id)
        return [
            {
                "source": e["from_id"],
                "target": e["to_id"],
                "weight": e["confidence"],
                "relation": "PREREQUISITE_OF",
            }
            for e in raw
        ]

    def get_learning_path(self, start_entity_name: str, document_id: str) -> dict:
        """Return topologically sorted prerequisite chain starting from start_entity_name.

        Algorithm:
        1. Find the Entity node matching start_entity_name (case-insensitive)
           that is MENTIONED_IN the given document_id.
        2. BFS traversal following PREREQUISITE_OF edges outward from start,
           collecting all reachable nodes. Cycles are handled with a seen set.
        3. Kahn's algorithm topological sort on the subgraph.
        4. Return {start_entity, document_id, nodes, edges}.
        Returns empty nodes/edges if start_entity not found or has no prerequisite edges.
        """
        from collections import deque  # noqa: PLC0415

        # Step 1: find start entity node (case-insensitive name match)
        try:
            name_lower = start_entity_name.lower()
            result = self._conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did})"
                " RETURN e.id, e.name, e.type",
                {"did": document_id},
            )
            start_id: str | None = None
            nodes_in_doc: dict[str, dict] = {}  # id -> {name, type}
            while result.has_next():
                row = result.get_next()
                eid, ename, etype = row[0], row[1], row[2]
                nodes_in_doc[eid] = {"name": ename, "type": etype or "CONCEPT"}
                if ename and ename.lower() == name_lower:
                    start_id = eid

            if start_id is None:
                return {"start_entity": start_entity_name, "document_id": document_id,
                        "nodes": [], "edges": []}
        except Exception:
            logger.debug("get_learning_path entity lookup failed", exc_info=True)
            return {"start_entity": start_entity_name, "document_id": document_id,
                    "nodes": [], "edges": []}

        # Step 2: BFS traversal following PREREQUISITE_OF edges from start
        try:
            # Build adjacency list for PREREQUISITE_OF edges scoped to document
            all_prereq_result = self._conn.execute(
                "MATCH (a:Entity)-[r:PREREQUISITE_OF]->(b:Entity)"
                " WHERE r.document_id = $did RETURN a.id, b.id, r.confidence",
                {"did": document_id},
            )
            # adj: from_id -> list of (to_id, confidence)
            adj: dict[str, list[tuple[str, float]]] = {}
            while all_prereq_result.has_next():
                row = all_prereq_result.get_next()
                from_id, to_id, conf = row[0], row[1], float(row[2] or 1.0)
                adj.setdefault(from_id, []).append((to_id, conf))

            if start_id not in adj:
                # Start node exists but has no outgoing prerequisite edges
                return {"start_entity": start_entity_name, "document_id": document_id,
                        "nodes": [], "edges": []}

            # BFS to collect reachable subgraph
            visited: set[str] = {start_id}
            queue: deque[str] = deque([start_id])
            subgraph_nodes: set[str] = {start_id}
            subgraph_edges: list[tuple[str, str, float]] = []

            while queue:
                current = queue.popleft()
                for neighbor_id, conf in adj.get(current, []):
                    subgraph_edges.append((current, neighbor_id, conf))
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        subgraph_nodes.add(neighbor_id)
                        queue.append(neighbor_id)

            # Step 3: Kahn's algorithm topological sort
            # Build in-degree map restricted to subgraph
            in_degree: dict[str, int] = {n: 0 for n in subgraph_nodes}
            sub_adj: dict[str, list[str]] = {n: [] for n in subgraph_nodes}
            for from_id, to_id, _ in subgraph_edges:
                if from_id in subgraph_nodes and to_id in subgraph_nodes:
                    sub_adj[from_id].append(to_id)
                    in_degree[to_id] = in_degree.get(to_id, 0) + 1

            # Initialize queue with nodes that have no incoming edges.
            # Kahn's on PREREQUISITE_OF edges (dep -> prereq) yields dependents
            # first.  Reversing gives learning order: deepest prerequisites first.
            topo_queue: deque[str] = deque(
                nid for nid in subgraph_nodes if in_degree[nid] == 0
            )
            topo_order: list[str] = []
            while topo_queue:
                node = topo_queue.popleft()
                topo_order.append(node)
                for neighbor in sub_adj.get(node, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        topo_queue.append(neighbor)

            # Reverse so prerequisites come first (learning order).
            topo_order.reverse()

            # Cycle detection: Kahn's drops cyclic nodes (their in-degree never
            # reaches 0).  Log a warning so data-quality issues are surfaced.
            if len(topo_order) < len(subgraph_nodes):
                logger.warning(
                    "Cyclic PREREQUISITE_OF subgraph detected for document %s"
                    " (start=%s): %d nodes unreachable via topological sort",
                    document_id, start_entity_name,
                    len(subgraph_nodes) - len(topo_order),
                )

            # Assign depth: 0 = deepest prerequisite, increasing = closer to start
            depth_map: dict[str, int] = {}
            for i, nid in enumerate(topo_order):
                depth_map[nid] = i

            from app.types import LearningPathNode  # noqa: PLC0415

            sorted_nodes = [
                LearningPathNode(
                    entity_id=nid,
                    name=nodes_in_doc.get(nid, {}).get("name", nid),
                    entity_type=nodes_in_doc.get(nid, {}).get("type", "CONCEPT"),
                    depth=depth_map.get(nid, 0),
                )
                for nid in topo_order
                if nid in nodes_in_doc
            ]

            return_edges = [
                {
                    "from_entity": nodes_in_doc.get(f, {}).get("name", f),
                    "to_entity": nodes_in_doc.get(t, {}).get("name", t),
                    "confidence": c,
                }
                for f, t, c in subgraph_edges
            ]

            return {
                "start_entity": start_entity_name,
                "document_id": document_id,
                "nodes": sorted_nodes,
                "edges": return_edges,
            }
        except Exception:
            logger.debug("get_learning_path traversal failed", exc_info=True)
            return {"start_entity": start_entity_name, "document_id": document_id,
                    "nodes": [], "edges": []}

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
        """Create a SAME_CONCEPT edge between two Entity nodes from different documents.

        Idempotent: checks both directions (a->b and b->a) before creating.
        If an existing edge is found and contradiction=True, updates the contradiction fields.
        """
        contradiction_int = 1 if contradiction else 0

        # Check a->b direction
        result_ab = self._conn.execute(
            "MATCH (a:Entity {id: $aid})-[r:SAME_CONCEPT]->(b:Entity {id: $bid})"
            " RETURN r.confidence",
            {"aid": entity_id_a, "bid": entity_id_b},
        )
        result_ba = self._conn.execute(
            "MATCH (a:Entity {id: $bid})-[r:SAME_CONCEPT]->(b:Entity {id: $aid})"
            " RETURN r.confidence",
            {"aid": entity_id_a, "bid": entity_id_b},
        )
        if result_ab.has_next() or result_ba.has_next():
            if contradiction:
                try:
                    self._conn.execute(
                        "MATCH (a:Entity {id: $aid})-[r:SAME_CONCEPT]->(b:Entity {id: $bid})"
                        " SET r.contradiction = $c, r.contradiction_note = $cn,"
                        " r.prefer_source = $ps",
                        {
                            "aid": entity_id_a, "bid": entity_id_b,
                            "c": contradiction_int, "cn": contradiction_note, "ps": prefer_source,
                        },
                    )
                except Exception:
                    logger.debug("add_same_concept_edge: SET contradiction failed", exc_info=True)
            return
        try:
            self._conn.execute(
                "MATCH (a:Entity {id: $aid}), (b:Entity {id: $bid})"
                " CREATE (a)-[:SAME_CONCEPT {"
                "source_doc_id: $sdid, target_doc_id: $tdid,"
                " confidence: $conf, contradiction: $c,"
                " contradiction_note: $cn, prefer_source: $ps"
                "}]->(b)",
                {
                    "aid": entity_id_a, "bid": entity_id_b,
                    "sdid": source_doc_id, "tdid": target_doc_id,
                    "conf": float(confidence), "c": contradiction_int,
                    "cn": contradiction_note, "ps": prefer_source,
                },
            )
        except Exception:
            logger.debug("add_same_concept_edge: CREATE failed", exc_info=True)

    def get_same_concept_edges(self) -> list[dict]:
        """Return all SAME_CONCEPT edges across the entire graph.

        Returns list of dicts:
            {entity_id_a, entity_id_b, name_a, name_b,
             source_doc_id, target_doc_id,
             confidence, contradiction, contradiction_note, prefer_source}
        Returns [] on any Kuzu error.
        """
        try:
            result = self._conn.execute(
                "MATCH (a:Entity)-[r:SAME_CONCEPT]->(b:Entity)"
                " RETURN a.id, b.id, a.name, b.name,"
                " r.source_doc_id, r.target_doc_id,"
                " r.confidence, r.contradiction,"
                " r.contradiction_note, r.prefer_source"
            )
            edges: list[dict] = []
            while result.has_next():
                row = result.get_next()
                edges.append({
                    "entity_id_a": row[0],
                    "entity_id_b": row[1],
                    "name_a": row[2],
                    "name_b": row[3],
                    "source_doc_id": row[4],
                    "target_doc_id": row[5],
                    "confidence": float(row[6] or 0.0),
                    "contradiction": bool(row[7]),
                    "contradiction_note": row[8] or "",
                    "prefer_source": row[9] or "",
                })
            return edges
        except Exception:
            logger.debug("get_same_concept_edges failed", exc_info=True)
            return []

    def get_concept_clusters(self) -> list[dict]:
        """Return concept clusters: groups of Entity nodes linked by SAME_CONCEPT edges.

        Uses union-find on SAME_CONCEPT edge pairs to group entities into clusters.
        Returns list of cluster dicts:
            {concept_name, entity_ids, document_ids, has_contradiction, contradiction_note}
        Returns [] if no SAME_CONCEPT edges exist.
        """
        edges = self.get_same_concept_edges()
        if not edges:
            return []

        # Union-find
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            if parent.setdefault(x, x) != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: str, y: str) -> None:
            parent[find(x)] = find(y)

        node_names: dict[str, str] = {}
        node_docs: dict[str, str] = {}  # entity_id -> doc_id

        for edge in edges:
            aid, bid = edge["entity_id_a"], edge["entity_id_b"]
            node_names[aid] = edge["name_a"]
            node_names[bid] = edge["name_b"]
            node_docs[aid] = edge["source_doc_id"]
            node_docs[bid] = edge["target_doc_id"]
            union(aid, bid)

        # Group by root
        groups: dict[str, list[str]] = {}
        for eid in node_names:
            root = find(eid)
            groups.setdefault(root, []).append(eid)

        # For each group, gather contradiction info
        edge_index: dict[tuple[str, str], dict] = {
            (e["entity_id_a"], e["entity_id_b"]): e for e in edges
        }

        clusters: list[dict] = []
        for eids in groups.values():
            has_contradiction = False
            contradiction_note = ""
            doc_ids: set[str] = set()
            for eid in eids:
                if eid in node_docs:
                    doc_ids.add(node_docs[eid])
            for eid_a in eids:
                for eid_b in eids:
                    e = edge_index.get((eid_a, eid_b))
                    if e and e["contradiction"]:
                        has_contradiction = True
                        if not contradiction_note:
                            contradiction_note = e["contradiction_note"]
            concept_name = max((node_names.get(eid, "") for eid in eids), key=len)
            clusters.append({
                "concept_name": concept_name,
                "entity_ids": eids,
                "document_ids": list(doc_ids),
                "has_contradiction": has_contradiction,
                "contradiction_note": contradiction_note,
            })
        return clusters

    # -------------------------------------------------------------------------
    # Delete
    # -------------------------------------------------------------------------

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
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did})"
                " RETURN count(*)",
                {"did": document_id},
            )
            entity_count = e_result.get_next()[0] if e_result.has_next() else 0

            co_result = self._conn.execute(
                "MATCH ()-[r:CO_OCCURS {document_id: $did}]->()"
                " RETURN count(*)",
                {"did": document_id},
            )
            edge_count = co_result.get_next()[0] if co_result.has_next() else 0
        except Exception:
            entity_count = 0
            edge_count = 0
        return int(entity_count), int(edge_count)

    def get_entities_for_documents(
        self, document_ids: list[str], limit: int = 15
    ) -> list[str]:
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

    # -------------------------------------------------------------------------
    # Query
    # -------------------------------------------------------------------------

    def get_graph_for_document(self, document_id: str) -> dict:
        """Return nodes and edges for a single document.

        Includes Entity nodes (with CO_OCCURS + tech-relation edges) and
        DiagramNode rows (with diagram edges) merged into a single graph.
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
        edges.extend(self._get_tech_relation_edges(entity_ids, document_id))
        # Include PREREQUISITE_OF edges for Viz tab (S139)
        edges.extend(self.get_prerequisite_edges_for_graph(document_id))

        # Include diagram-derived nodes and edges (S136)
        diagram_nodes = self.get_diagram_nodes_for_document(document_id)
        nodes.extend(diagram_nodes)
        edges.extend(self.get_diagram_edges_for_document(document_id))

        return {"nodes": nodes, "edges": edges}

    def get_graph_for_documents(
        self,
        document_ids: list[str],
        include_same_concept: bool = False,
    ) -> dict:
        """Return merged nodes and edges for multiple documents.

        Includes Entity nodes and DiagramNode rows from all specified documents.
        Pass include_same_concept=True to include SAME_CONCEPT cross-book edges (S141).
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
                    edges.append({
                        "source": e["entity_id_a"],
                        "target": e["entity_id_b"],
                        "weight": e["confidence"],
                        "relation": "SAME_CONCEPT",
                        "contradiction": e["contradiction"],
                    })

        return {"nodes": list(nodes_map.values()), "edges": edges}

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

    # -------------------------------------------------------------------------
    # Call graph (code documents)
    # -------------------------------------------------------------------------

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

    _TECH_REL_TYPES: frozenset[str] = frozenset({
        "IMPLEMENTS", "EXTENDS", "USES", "REPLACES", "DEPENDS_ON",
    })

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
                entities.append({
                    "id": row[0],
                    "name": row[1],
                    "type": row[2],
                    "frequency": int(row[3] or 1),
                })
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
                nodes.append({
                    "id": row[0],
                    "name": row[1],
                    "type": row[2],
                    "frequency": int(row[3] or 1),
                })
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
                    "id": node_id, "name": name, "ntype": node_type,
                    "siid": source_image_id, "did": document_id,
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
            logger.warning(
                "add_diagram_edge: unknown edge_type=%r, skipping", edge_type
            )

    def add_depicts_edge(
        self, diagram_node_id: str, entity_id: str, document_id: str
    ) -> None:
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

    def match_entity_by_name(self, node_name: str, document_id: str) -> str | None:
        """Return Entity.id if an Entity with a name containing node_name exists.

        Case-insensitive substring match: returns the first Entity in document_id
        whose lowercase name contains the lowercase node_name, or None.
        Pure Kuzu query; no LLM.
        """
        try:
            name_lower = node_name.lower()
            result = self._conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did})"
                " RETURN e.id, e.name",
                {"did": document_id},
            )
            while result.has_next():
                row = result.get_next()
                eid, ename = row[0], row[1]
                if ename and name_lower in ename.lower():
                    return eid
            return None
        except Exception:
            logger.debug("match_entity_by_name failed", exc_info=True)
            return None

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
                nodes.append({
                    "id": row[0],
                    "label": row[1],
                    "type": row[2],
                    "size": int(row[3] or 1),
                    "source_image_id": row[4] or "",
                    "mention_count": int(row[3] or 1),
                })
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
            "CONNECTS_TO", "STORES_IN", "SENDS_TO", "HAS_FIELD", "REFERENCES_DM", "LEADS_TO"
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
                    edges.append({
                        "source": row[0],
                        "target": row[1],
                        "weight": 1.0,
                        "relation": rel,
                    })
            except Exception:
                logger.debug("get_diagram_edges_for_document failed for %s", rel, exc_info=True)
        return edges

    def _get_tech_relation_edges(
        self, entity_ids: set[str], document_id: str
    ) -> list[dict]:
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
                    edges.append({
                        "source": row[0],
                        "target": row[1],
                        "weight": 1.0,
                        "relation": rel,
                    })
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
                nodes_map[aid] = {"id": aid, "label": aname, "type": atype or "FUNCTION",
                                   "size": afreq or 1}
            if bid not in nodes_map:
                nodes_map[bid] = {"id": bid, "label": bname, "type": btype or "FUNCTION",
                                   "size": bfreq or 1}
            edges.append({"source": aid, "target": bid, "weight": 1.0})
        return {"nodes": list(nodes_map.values()), "edges": edges}
