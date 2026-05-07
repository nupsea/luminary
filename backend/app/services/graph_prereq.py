"""KuzuPrereqRepo: PREREQUISITE_OF edges + learning path traversal (S117).

Methods are lifted verbatim from `KuzuService` so query strings, error
handling, and return shapes are unchanged. `KuzuService` keeps the
public method names and delegates to this repo for back-compat.
"""

from __future__ import annotations

import logging
from collections import deque

from app.services.graph_connection import KuzuConnection

logger = logging.getLogger(__name__)


class KuzuPrereqRepo:
    def __init__(self, connection: KuzuConnection) -> None:
        self._conn = connection.conn

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
                    "dep": dependent_id,
                    "pre": prerequisite_id,
                    "did": document_id,
                    "conf": confidence,
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
                edges.append(
                    {
                        "from_entity": row[0],
                        "to_entity": row[1],
                        "from_id": row[2],
                        "to_id": row[3],
                        "confidence": float(row[4] or 1.0),
                    }
                )
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
                        "dep": dependent_id,
                        "pre": prerequisite_id,
                        "did": document_id,
                        "conf": confidence,
                        "sid": source_section_id,
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
                    {
                        "dep": dependent_id,
                        "pre": prerequisite_id,
                        "did": document_id,
                        "conf": confidence,
                    },
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
            all_result = self._conn.execute(
                "MATCH (e:Entity)-[r:MENTIONED_IN]->(d:Document {id: $did})"
                " RETURN e.id, e.name, r.count",
                {"did": document_id},
            )
            all_entities: dict[str, tuple[str, int]] = {}
            while all_result.has_next():
                row = all_result.get_next()
                all_entities[row[0]] = (row[1], int(row[2] or 1))

            dep_result = self._conn.execute(
                "MATCH (a:Entity)-[r:PREREQUISITE_OF]->(b:Entity)"
                " WHERE r.document_id = $did RETURN DISTINCT a.id",
                {"did": document_id},
            )
            has_prereqs: set[str] = set()
            while dep_result.has_next():
                has_prereqs.add(dep_result.get_next()[0])

            referenced_result = self._conn.execute(
                "MATCH (a:Entity)-[r:PREREQUISITE_OF]->(b:Entity)"
                " WHERE r.document_id = $did RETURN DISTINCT b.id",
                {"did": document_id},
            )
            referenced: set[str] = set()
            while referenced_result.has_next():
                referenced.add(referenced_result.get_next()[0])

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
        try:
            name_lower = start_entity_name.lower()
            result = self._conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did})"
                " RETURN e.id, e.name, e.type",
                {"did": document_id},
            )
            start_id: str | None = None
            nodes_in_doc: dict[str, dict] = {}
            while result.has_next():
                row = result.get_next()
                eid, ename, etype = row[0], row[1], row[2]
                nodes_in_doc[eid] = {"name": ename, "type": etype or "CONCEPT"}
                if ename and ename.lower() == name_lower:
                    start_id = eid

            if start_id is None:
                return {
                    "start_entity": start_entity_name,
                    "document_id": document_id,
                    "nodes": [],
                    "edges": [],
                }
        except Exception:
            logger.debug("get_learning_path entity lookup failed", exc_info=True)
            return {
                "start_entity": start_entity_name,
                "document_id": document_id,
                "nodes": [],
                "edges": [],
            }

        try:
            all_prereq_result = self._conn.execute(
                "MATCH (a:Entity)-[r:PREREQUISITE_OF]->(b:Entity)"
                " WHERE r.document_id = $did RETURN a.id, b.id, r.confidence",
                {"did": document_id},
            )
            adj: dict[str, list[tuple[str, float]]] = {}
            while all_prereq_result.has_next():
                row = all_prereq_result.get_next()
                from_id, to_id, conf = row[0], row[1], float(row[2] or 1.0)
                adj.setdefault(from_id, []).append((to_id, conf))

            if start_id not in adj:
                return {
                    "start_entity": start_entity_name,
                    "document_id": document_id,
                    "nodes": [],
                    "edges": [],
                }

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

            in_degree: dict[str, int] = {n: 0 for n in subgraph_nodes}
            sub_adj: dict[str, list[str]] = {n: [] for n in subgraph_nodes}
            for from_id, to_id, _ in subgraph_edges:
                if from_id in subgraph_nodes and to_id in subgraph_nodes:
                    sub_adj[from_id].append(to_id)
                    in_degree[to_id] = in_degree.get(to_id, 0) + 1

            topo_queue: deque[str] = deque(nid for nid in subgraph_nodes if in_degree[nid] == 0)
            topo_order: list[str] = []
            while topo_queue:
                node = topo_queue.popleft()
                topo_order.append(node)
                for neighbor in sub_adj.get(node, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        topo_queue.append(neighbor)

            topo_order.reverse()

            if len(topo_order) < len(subgraph_nodes):
                logger.warning(
                    "Cyclic PREREQUISITE_OF subgraph detected for document %s"
                    " (start=%s): %d nodes unreachable via topological sort",
                    document_id,
                    start_entity_name,
                    len(subgraph_nodes) - len(topo_order),
                )

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
            return {
                "start_entity": start_entity_name,
                "document_id": document_id,
                "nodes": [],
                "edges": [],
            }
