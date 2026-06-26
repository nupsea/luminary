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

    # -------------------------------------------------------------------------
    # Concept nodes (the studyable atom -- distinct from Entity; see docs/concepts.md)
    # -------------------------------------------------------------------------

    def upsert_concept_node(
        self, concept_id: str, slug: str, label: str, kind: str, status: str
    ) -> None:
        """Create or update a Concept node. Idempotent on concept_id."""
        existing = self._conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.id", {"id": concept_id}
        )
        if existing.has_next():
            self._conn.execute(
                "MATCH (c:Concept {id: $id})"
                " SET c.slug = $slug, c.label = $label, c.kind = $kind, c.status = $status",
                {"id": concept_id, "slug": slug, "label": label, "kind": kind, "status": status},
            )
            return
        self._conn.execute(
            "CREATE (c:Concept {id: $id, slug: $slug, label: $label,"
            " kind: $kind, status: $status})",
            {"id": concept_id, "slug": slug, "label": label, "kind": kind, "status": status},
        )

    def add_extracted_from(self, concept_id: str, document_id: str) -> None:
        """Link a Concept to a Document it was extracted from (availability). Idempotent."""
        existing = self._conn.execute(
            "MATCH (c:Concept {id: $cid})-[:EXTRACTED_FROM]->(d:Document {id: $did}) RETURN c.id",
            {"cid": concept_id, "did": document_id},
        )
        if existing.has_next():
            return
        self._conn.execute(
            "MATCH (c:Concept {id: $cid}), (d:Document {id: $did})"
            " CREATE (c)-[:EXTRACTED_FROM]->(d)",
            {"cid": concept_id, "did": document_id},
        )

    def add_promoted_from(self, concept_id: str, entity_id: str, confidence: float = 1.0) -> None:
        """Link a Concept to an Entity it was promoted from (the NER bridge). Idempotent."""
        existing = self._conn.execute(
            "MATCH (c:Concept {id: $cid})-[:PROMOTED_FROM]->(e:Entity {id: $eid}) RETURN c.id",
            {"cid": concept_id, "eid": entity_id},
        )
        if existing.has_next():
            return
        self._conn.execute(
            "MATCH (c:Concept {id: $cid}), (e:Entity {id: $eid})"
            " CREATE (c)-[:PROMOTED_FROM {confidence: $conf}]->(e)",
            {"cid": concept_id, "eid": entity_id, "conf": float(confidence)},
        )

    def add_concept_relation(
        self, source_id: str, target_id: str, weight: float = 0.5, status: str = "proposed"
    ) -> None:
        """Create a CONCEPT_RELATED_TO edge between two concepts. Idempotent (one direction)."""
        existing = self._conn.execute(
            "MATCH (a:Concept {id: $a})-[r:CONCEPT_RELATED_TO]->(b:Concept {id: $b})"
            " RETURN r.weight",
            {"a": source_id, "b": target_id},
        )
        if existing.has_next():
            return
        self._conn.execute(
            "MATCH (a:Concept {id: $a}), (b:Concept {id: $b})"
            " CREATE (a)-[:CONCEPT_RELATED_TO {weight: $w, status: $s}]->(b)",
            {"a": source_id, "b": target_id, "w": float(weight), "s": status},
        )

    def get_concept_neighbors(self, concept_id: str, limit: int = 10) -> list[str]:
        """Return ids of concepts directly related to the given concept (both directions)."""
        try:
            result = self._conn.execute(
                "MATCH (a:Concept {id: $id})-[:CONCEPT_RELATED_TO]-(b:Concept)"
                " RETURN DISTINCT b.id LIMIT $lim",
                {"id": concept_id, "lim": limit},
            )
            out: list[str] = []
            while result.has_next():
                out.append(result.get_next()[0])
            return out
        except Exception:
            logger.debug("get_concept_neighbors failed for %s", concept_id, exc_info=True)
            return []

    def delete_concept_node(self, concept_id: str) -> None:
        """Delete a Concept node and its edges. Idempotent."""
        try:
            self._conn.execute(
                "MATCH (c:Concept {id: $id}) DETACH DELETE c", {"id": concept_id}
            )
        except Exception:
            logger.debug("delete_concept_node failed for %s", concept_id, exc_info=True)

    def delete_all_concepts(self) -> None:
        """Drop every Concept node + its edges (for a full regenerate). Idempotent."""
        try:
            self._conn.execute("MATCH (c:Concept) DETACH DELETE c")
        except Exception:
            logger.debug("delete_all_concepts failed", exc_info=True)

    def get_concept_ids_for_documents(self, document_ids: list[str]) -> list[str]:
        """Return ids of concepts EXTRACTED_FROM any of the given documents."""
        if not document_ids:
            return []
        try:
            result = self._conn.execute(
                "MATCH (c:Concept)-[:EXTRACTED_FROM]->(d:Document)"
                " WHERE d.id IN $dids RETURN DISTINCT c.id",
                {"dids": list(document_ids)},
            )
            out: list[str] = []
            while result.has_next():
                out.append(result.get_next()[0])
            return out
        except Exception:
            logger.debug("get_concept_ids_for_documents failed", exc_info=True)
            return []
