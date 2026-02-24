"""GET /graph endpoints for entity-relationship knowledge graph queries."""

import logging

from fastapi import APIRouter, Query

from app.services.graph import get_graph_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/{document_id}")
async def get_graph_for_document(
    document_id: str,
    type: str = Query(default="knowledge_graph"),
) -> dict:
    """Return nodes and edges for a single document.

    Pass ?type=call_graph to get the function call graph (code documents only).
    Default is the knowledge entity graph.
    """
    svc = get_graph_service()
    if type == "call_graph":
        return svc.get_call_graph(document_id)
    return svc.get_graph_for_document(document_id)


@router.get("")
async def get_graph(doc_ids: str = Query(default="")) -> dict:
    """Return merged nodes and edges for multiple documents.

    Pass ?doc_ids=id1,id2,id3 to filter by specific documents.
    Returns all graph data if doc_ids is empty.
    """
    svc = get_graph_service()
    if doc_ids:
        ids = [d.strip() for d in doc_ids.split(",") if d.strip()]
    else:
        ids = []
    return svc.get_graph_for_documents(ids)
