"""KuzuService: Kuzu embedded graph database for entity relationship storage.

Schema:
  Nodes: Entity(id, name, type, frequency, aliases), Document(id, title, content_type)
  Edges: MENTIONED_IN(Entity->Document, count),
         CO_OCCURS(Entity->Entity, weight, document_id),
         RELATED_TO(Entity->Entity, relation_label, confidence),
         CALLS(Entity->Entity, document_id)  -- function call graph for code documents
         PREREQUISITE_OF(Entity->Entity, document_id, confidence)  -- S117

Note: `aliases` column on Entity was added in S86.  Databases created before S86 will
not have this column; aliases writes are wrapped in try/except for graceful degradation.
"""

import logging
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
        """Return nodes and edges for a single document."""
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
                    "mention_count": count or 1,
                }
            )
            entity_ids.add(eid)

        edges = self._get_co_occurrence_edges(entity_ids, document_id)
        return {"nodes": nodes, "edges": edges}

    def get_graph_for_documents(self, document_ids: list[str]) -> dict:
        """Return merged nodes and edges for multiple documents."""
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
                    "mention_count": count or 1,
                }
            else:
                nodes_map[eid]["mention_count"] = nodes_map[eid]["mention_count"] + (count or 1)

        entity_ids = set(nodes_map.keys())
        edges: list[dict] = []
        for doc_id in document_ids:
            edges.extend(self._get_co_occurrence_edges(entity_ids, doc_id))

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
