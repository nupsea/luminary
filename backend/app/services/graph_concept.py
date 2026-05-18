"""KuzuConceptRepo: SAME_CONCEPT cross-document edges + concept clustering

Methods are lifted verbatim from `KuzuService` so query strings and
return shapes are unchanged. `KuzuService` keeps the public method
names and delegates to this repo.
"""

from __future__ import annotations

import logging

from app.services.graph_connection import KuzuConnection

logger = logging.getLogger(__name__)


class KuzuConceptRepo:
    def __init__(self, connection: KuzuConnection) -> None:
        self._conn = connection.conn

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
                            "aid": entity_id_a,
                            "bid": entity_id_b,
                            "c": contradiction_int,
                            "cn": contradiction_note,
                            "ps": prefer_source,
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
                    "aid": entity_id_a,
                    "bid": entity_id_b,
                    "sdid": source_doc_id,
                    "tdid": target_doc_id,
                    "conf": float(confidence),
                    "c": contradiction_int,
                    "cn": contradiction_note,
                    "ps": prefer_source,
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
                edges.append(
                    {
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
                    }
                )
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

        parent: dict[str, str] = {}

        def find(x: str) -> str:
            if parent.setdefault(x, x) != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: str, y: str) -> None:
            parent[find(x)] = find(y)

        node_names: dict[str, str] = {}
        node_docs: dict[str, str] = {}

        for edge in edges:
            aid, bid = edge["entity_id_a"], edge["entity_id_b"]
            node_names[aid] = edge["name_a"]
            node_names[bid] = edge["name_b"]
            node_docs[aid] = edge["source_doc_id"]
            node_docs[bid] = edge["target_doc_id"]
            union(aid, bid)

        groups: dict[str, list[str]] = {}
        for eid in node_names:
            root = find(eid)
            groups.setdefault(root, []).append(eid)

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
            clusters.append(
                {
                    "concept_name": concept_name,
                    "entity_ids": eids,
                    "document_ids": list(doc_ids),
                    "has_contradiction": has_contradiction,
                    "contradiction_note": contradiction_note,
                }
            )
        return clusters
