"""Shared Kuzu database + connection wrapper.

Owns the `kuzu.Database`, `kuzu.Connection`, the serialization lock, and
the schema-creation DDL. Repos under `app.services.graph_*` take a
`KuzuConnection` and use its `.conn` attribute (the raw kuzu connection).

Schema creation is idempotent (`CREATE ... IF NOT EXISTS`).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import kuzu

logger = logging.getLogger(__name__)


class KuzuConnection:
    """Thin wrapper around a Kuzu DB + Connection pair.

    `.conn` is the raw `kuzu.Connection`; repos call `.conn.execute(...)`
    so that the existing query strings can be lifted unchanged.
    """

    def __init__(self, data_dir: str) -> None:
        db_path = str(Path(data_dir).expanduser() / "graph.kuzu")
        self.db = kuzu.Database(db_path)
        self.conn = kuzu.Connection(self.db)
        # Kuzu connection is not thread-safe. Serialise execute() calls.
        self.lock = threading.Lock()
        self._create_schema()
        logger.info("KuzuConnection initialized", extra={"db_path": db_path})

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
            "CREATE REL TABLE IF NOT EXISTS MENTIONED_IN(FROM Entity TO Document, count INT64)",
            "CREATE REL TABLE IF NOT EXISTS CO_OCCURS("
            "FROM Entity TO Entity, weight FLOAT, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS RELATED_TO("
            "FROM Entity TO Entity, relation_label STRING, confidence FLOAT)",
            "CREATE REL TABLE IF NOT EXISTS CALLS(FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS PREREQUISITE_OF("
            "FROM Entity TO Entity, document_id STRING, confidence FLOAT)",
            # Tech relation edges (S135)
            "CREATE REL TABLE IF NOT EXISTS IMPLEMENTS(FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS EXTENDS(FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS USES(FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS REPLACES(FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS DEPENDS_ON(FROM Entity TO Entity, document_id STRING)",
            "CREATE REL TABLE IF NOT EXISTS VERSION_OF(FROM Entity TO Entity, document_id STRING)",
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
            "CREATE REL TABLE IF NOT EXISTS WRITTEN_ABOUT(FROM Note TO Entity, confidence FLOAT)",
            "CREATE REL TABLE IF NOT EXISTS TAG_IS_CONCEPT(FROM Note TO Entity, tag STRING)",
            "CREATE REL TABLE IF NOT EXISTS DERIVED_FROM(FROM Note TO Document)",
            # Zettelkasten links (S171) -- explicit typed note-to-note connections
            "CREATE REL TABLE IF NOT EXISTS LINKS_TO(FROM Note TO Note, link_type STRING)",
        ]
        for stmt in stmts:
            self.conn.execute(stmt)
