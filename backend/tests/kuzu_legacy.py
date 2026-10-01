"""A Kuzu graph in the layout Luminary wrote up to 0.15.0, for the importer's tests.

The app no longer writes Kuzu; `services/graph_import.py` only reads an existing
`graph.kuzu`. This builds one so the import can be tested against the real layout.
"""

from pathlib import Path

import kuzu

_SCHEMA = [
    # Node tables
    "CREATE NODE TABLE IF NOT EXISTS Entity("
    "id STRING PRIMARY KEY, name STRING, type STRING, frequency INT64, aliases STRING)",
    "CREATE NODE TABLE IF NOT EXISTS Document("
    "id STRING PRIMARY KEY, title STRING, content_type STRING)",
    # Diagram-derived node table -- must be created before DEPICTS edge
    "CREATE NODE TABLE IF NOT EXISTS DiagramNode("
    "id STRING PRIMARY KEY, name STRING, node_type STRING,"
    " source_image_id STRING, document_id STRING, frequency INT64)",
    # Edge tables
    "CREATE REL TABLE IF NOT EXISTS MENTIONED_IN(FROM Entity TO Document, count INT64)",
    "CREATE REL TABLE IF NOT EXISTS CO_OCCURS("
    "FROM Entity TO Entity, weight FLOAT, document_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS RELATED_TO("
    "FROM Entity TO Entity, relation_label STRING, confidence FLOAT)",
    "CREATE REL TABLE IF NOT EXISTS CALLS(FROM Entity TO Entity, document_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS PREREQUISITE_OF("
    "FROM Entity TO Entity, document_id STRING, confidence FLOAT)",
    # Tech relation edges
    "CREATE REL TABLE IF NOT EXISTS IMPLEMENTS(FROM Entity TO Entity, document_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS EXTENDS(FROM Entity TO Entity, document_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS USES(FROM Entity TO Entity, document_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS REPLACES(FROM Entity TO Entity, document_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS DEPENDS_ON(FROM Entity TO Entity, document_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS VERSION_OF(FROM Entity TO Entity, document_id STRING)",
    # Diagram-derived edge tables
    "CREATE REL TABLE IF NOT EXISTS CONNECTS_TO("
    "FROM DiagramNode TO DiagramNode, document_id STRING, label STRING)",
    "CREATE REL TABLE IF NOT EXISTS STORES_IN(FROM DiagramNode TO DiagramNode, document_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS SENDS_TO("
    "FROM DiagramNode TO DiagramNode, document_id STRING, message STRING)",
    "CREATE REL TABLE IF NOT EXISTS HAS_FIELD(FROM DiagramNode TO DiagramNode, document_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS REFERENCES_DM("
    "FROM DiagramNode TO DiagramNode, document_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS LEADS_TO("
    "FROM DiagramNode TO DiagramNode, document_id STRING, condition STRING)",
    # DEPICTS: links a diagram-derived node to an existing Entity
    "CREATE REL TABLE IF NOT EXISTS DEPICTS(FROM DiagramNode TO Entity, document_id STRING)",
    # SAME_CONCEPT: cross-document concept links
    # Uses INT64 for contradiction (not BOOLEAN) for Kuzu compatibility
    "CREATE REL TABLE IF NOT EXISTS SAME_CONCEPT("
    "FROM Entity TO Entity,"
    " source_doc_id STRING, target_doc_id STRING,"
    " confidence FLOAT, contradiction INT64,"
    " contradiction_note STRING, prefer_source STRING)",
    # Note graph -- Note nodes + edges to Entity and Document
    "CREATE NODE TABLE IF NOT EXISTS Note("
    "id STRING PRIMARY KEY, note_id STRING, preview STRING, created_at STRING)",
    "CREATE REL TABLE IF NOT EXISTS WRITTEN_ABOUT(FROM Note TO Entity, confidence FLOAT)",
    "CREATE REL TABLE IF NOT EXISTS TAG_IS_CONCEPT(FROM Note TO Entity, tag STRING)",
    "CREATE REL TABLE IF NOT EXISTS DERIVED_FROM(FROM Note TO Document)",
    # Zettelkasten links -- explicit typed note-to-note connections
    "CREATE REL TABLE IF NOT EXISTS LINKS_TO(FROM Note TO Note, link_type STRING)",
    # --- Concept layer (the studyable atom; see docs/concepts.md) ---
    # A Concept is promoted from a cluster of Entities; it is NOT an Entity.
    # SQLite owns the hot learning state; this node owns the topology.
    "CREATE NODE TABLE IF NOT EXISTS Concept("
    "id STRING PRIMARY KEY, slug STRING, label STRING, kind STRING, status STRING)",
    # concept<->concept edges. Distinct names from the Entity-level RELATED_TO /
    # PREREQUISITE_OF (Kuzu rel tables are typed by endpoint pair).
    "CREATE REL TABLE IF NOT EXISTS CONCEPT_RELATED_TO("
    "FROM Concept TO Concept, weight FLOAT, status STRING)",
    "CREATE REL TABLE IF NOT EXISTS CONCEPT_PREREQUISITE_OF("
    "FROM Concept TO Concept, confidence FLOAT)",
    # provenance: availability (which docs extracted it) + the Entity bridge
    "CREATE REL TABLE IF NOT EXISTS EXTRACTED_FROM(FROM Concept TO Document)",
    "CREATE REL TABLE IF NOT EXISTS PROMOTED_FROM(FROM Concept TO Entity, confidence FLOAT)",
]


def legacy_graph(data_dir: Path) -> kuzu.Connection:
    """A writable `graph.kuzu` under `data_dir` with every table the app used to create."""
    conn = kuzu.Connection(kuzu.Database(str(data_dir / "graph.kuzu")))
    for stmt in _SCHEMA:
        conn.execute(stmt)
    return conn
