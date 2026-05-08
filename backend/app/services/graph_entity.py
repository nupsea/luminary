"""KuzuEntityRepo: core Entity CRUD + Document upserts + co-occurrence/relation edges.

Methods are lifted verbatim from `KuzuService` so query strings, error
handling, and return shapes are unchanged. `KuzuService` keeps the
public method names and delegates to this repo for back-compat.

This repo is the seam that ViewRepo + TechRepo (future phases) will
read through, so it must stay independent of the prereq / concept
repos.
"""

from __future__ import annotations

import logging

from app.services.graph_connection import KuzuConnection

logger = logging.getLogger(__name__)


class KuzuEntityRepo:
    def __init__(self, connection: KuzuConnection) -> None:
        self._conn = connection.conn

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
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did}) RETURN e.name, e.type",
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

    def add_co_occurrence(self, entity_id_a: str, entity_id_b: str, document_id: str) -> None:
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

    def match_entity_by_name(self, node_name: str, document_id: str) -> str | None:
        """Return Entity.id if an Entity with a name containing node_name exists.

        Case-insensitive substring match: returns the first Entity in document_id
        whose lowercase name contains the lowercase node_name, or None.
        Pure Kuzu query; no LLM.
        """
        try:
            name_lower = node_name.lower()
            result = self._conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did}) RETURN e.id, e.name",
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
