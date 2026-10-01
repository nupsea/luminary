"""The Kuzu side of the graph import: every row, as plain dicts.

Older graphs predate some tables and columns, so a query against a missing table reads
as no rows, and a query against a missing column falls back to one without it.
"""

from __future__ import annotations

from typing import Any

_ENTITY_QUERIES = (
    "MATCH (e:Entity) OPTIONAL MATCH (e)-[m:MENTIONED_IN]->(d:Document)"
    " RETURN e.id AS id, e.name AS name, e.type AS type, e.frequency AS frequency,"
    " e.aliases AS aliases, m.count AS mentions, d.id AS document_id",
    "MATCH (e:Entity) OPTIONAL MATCH (e)-[m:MENTIONED_IN]->(d:Document)"
    " RETURN e.id AS id, e.name AS name, e.type AS type, e.frequency AS frequency,"
    " m.count AS mentions, d.id AS document_id",
)

_EDGE = "MATCH (a:Entity)-[r:{kind}]->(b:Entity) RETURN a.id AS source_id, b.id AS target_id"
# Extra properties per relation, most complete form first.
_ENTITY_EDGE_PROPS: dict[str, tuple[str, ...]] = {
    "CO_OCCURS": (", r.document_id AS document_id, r.weight AS weight",),
    "RELATED_TO": (", r.relation_label AS label, r.confidence AS confidence",),
    "PREREQUISITE_OF": (
        ", r.document_id AS document_id, r.confidence AS confidence,"
        " r.source_section_id AS source_section_id",
        ", r.document_id AS document_id, r.confidence AS confidence",
    ),
    **dict.fromkeys(
        ("CALLS", "IMPLEMENTS", "EXTENDS", "USES", "REPLACES", "DEPENDS_ON", "VERSION_OF"),
        (", r.document_id AS document_id",),
    ),
}

_DIAGRAM_EDGE_LABELS = {
    "CONNECTS_TO": "r.label",
    "STORES_IN": None,
    "SENDS_TO": "r.message",
    "HAS_FIELD": None,
    "REFERENCES_DM": None,
    "LEADS_TO": "r.condition",
}


def _is_missing(exc: Exception, what: str) -> bool:
    message = str(exc).lower()
    return what in message and ("does not exist" in message or "cannot find" in message)


def rows(conn, *queries: str) -> list[dict[str, Any]]:
    """Rows of the first query whose columns all exist; [] if its table does not."""
    for query in queries:
        try:
            result = conn.execute(query)
        except RuntimeError as exc:
            if _is_missing(exc, "table"):
                return []
            if _is_missing(exc, "property") and query is not queries[-1]:
                continue
            raise
        names = result.get_column_names()
        out = []
        while result.has_next():
            out.append(dict(zip(names, result.get_next(), strict=True)))
        return out
    return []


def read_concept_edges(conn) -> list[dict[str, Any]]:
    related = rows(
        conn,
        "MATCH (a:Concept)-[r:CONCEPT_RELATED_TO]->(b:Concept)"
        " RETURN a.id AS source_id, b.id AS target_id, r.weight AS weight, r.status AS status",
    )
    prereq = rows(
        conn,
        "MATCH (a:Concept)-[r:CONCEPT_PREREQUISITE_OF]->(b:Concept)"
        " RETURN a.id AS source_id, b.id AS target_id, r.confidence AS confidence",
    )
    return [{"kind": "related", **r} for r in related] + [
        {"kind": "prerequisite", **r} for r in prereq
    ]


def read_concept_documents(conn) -> list[dict[str, Any]]:
    return rows(
        conn,
        "MATCH (c:Concept)-[:EXTRACTED_FROM]->(d:Document)"
        " RETURN c.id AS concept_id, d.id AS document_id",
    )


def read_entities(conn) -> list[dict[str, Any]]:
    return rows(conn, *_ENTITY_QUERIES)


def read_entity_edges(conn) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for kind, props in _ENTITY_EDGE_PROPS.items():
        queries = [_EDGE.format(kind=kind) + p for p in props]
        edges += [{"kind": kind, **r} for r in rows(conn, *queries)]
    return edges


def read_entity_links(conn) -> list[dict[str, Any]]:
    return rows(
        conn,
        "MATCH (a:Entity)-[r:SAME_CONCEPT]->(b:Entity)"
        " RETURN a.id AS source_id, b.id AS target_id,"
        " r.source_doc_id AS source_document_id, r.target_doc_id AS target_document_id,"
        " r.confidence AS confidence, r.contradiction AS contradiction,"
        " r.contradiction_note AS contradiction_note, r.prefer_source AS prefer_source",
    )


def read_diagram_nodes(conn) -> list[dict[str, Any]]:
    return rows(
        conn,
        "MATCH (n:DiagramNode) RETURN n.id AS id, n.name AS name, n.node_type AS node_type,"
        " n.source_image_id AS source_image_id, n.document_id AS document_id,"
        " n.frequency AS frequency",
    )


def read_diagram_edges(conn) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for kind, label in _DIAGRAM_EDGE_LABELS.items():
        query = (
            f"MATCH (a:DiagramNode)-[r:{kind}]->(b:DiagramNode)"
            " RETURN a.id AS source_id, b.id AS target_id, r.document_id AS document_id"
            + (f", {label} AS label" if label else "")
        )
        edges += [{"kind": kind, **r} for r in rows(conn, query)]
    return edges


def read_diagram_depictions(conn) -> list[dict[str, Any]]:
    return rows(
        conn,
        "MATCH (n:DiagramNode)-[r:DEPICTS]->(e:Entity)"
        " RETURN n.id AS node_id, e.id AS entity_id, r.document_id AS document_id",
    )


def read_note_entities(conn) -> list[dict[str, Any]]:
    written = rows(
        conn,
        "MATCH (n:Note)-[r:WRITTEN_ABOUT]->(e:Entity)"
        " RETURN n.id AS note_id, e.id AS entity_id, r.confidence AS confidence",
    )
    tagged = rows(
        conn,
        "MATCH (n:Note)-[r:TAG_IS_CONCEPT]->(e:Entity)"
        " RETURN n.id AS note_id, e.id AS entity_id, r.tag AS tag",
    )
    return [{"kind": "written_about", **r} for r in written] + [
        {"kind": "tag", "confidence": 1.0, **r} for r in tagged
    ]


def count_superseded_note_edges(conn) -> int:
    """DERIVED_FROM and LINKS_TO rows: `note_sources` and `note_links` already hold them."""
    derived = rows(conn, "MATCH (:Note)-[r:DERIVED_FROM]->(:Document) RETURN count(r) AS n")
    links = rows(conn, "MATCH (:Note)-[r:LINKS_TO]->(:Note) RETURN count(r) AS n")
    return sum(r["n"] for r in derived + links)


def count_unused_entity_edges(conn) -> int:
    """PROMOTED_FROM rows: no reader or writer remains, so they are counted, not copied."""
    return sum(
        r["n"]
        for r in rows(conn, "MATCH (:Concept)-[r:PROMOTED_FROM]->(:Entity) RETURN count(r) AS n")
    )
