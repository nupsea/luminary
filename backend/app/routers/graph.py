"""GET /graph endpoints for entity-relationship knowledge graph queries."""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.graph import get_graph_service
from app.types import LearningPathResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/learning-path")
async def get_learning_path(
    start_entity: str = Query(..., description="Entity name to start path from"),
    document_id: str = Query(..., description="Document scope"),
) -> LearningPathResponse:
    """Return topologically sorted prerequisite chain for a concept.

    Returns LearningPathResponse with nodes sorted from deepest prerequisite
    toward the start node (start has highest depth index).
    Returns empty nodes/edges if the entity is not found or has no edges.

    IMPORTANT: This route must be declared before GET /{document_id} to prevent
    FastAPI from matching 'learning-path' as a document_id path parameter.
    """
    svc = get_graph_service()
    return svc.get_learning_path(start_entity, document_id)


class EntityItem(BaseModel):
    id: str
    name: str
    type: str
    frequency: int


class EntityListResponse(BaseModel):
    entities: list[EntityItem]


class ConceptClusterItem(BaseModel):
    concept_name: str
    entity_ids: list[str]
    document_ids: list[str]
    has_contradiction: bool
    contradiction_note: str


class ConceptLinkedResponse(BaseModel):
    clusters: list[ConceptClusterItem]


@router.get("/concepts/linked")
async def get_concept_clusters() -> ConceptLinkedResponse:
    """Return concept clusters: groups of Entity nodes linked by SAME_CONCEPT edges.

    Returns all cross-document concept clusters. Each cluster represents one concept
    that appears in multiple documents, with contradiction status if detected.
    Empty clusters list when no SAME_CONCEPT edges exist.

    IMPORTANT: This route must be declared before GET /{document_id} to prevent
    FastAPI from matching 'concepts' as a document_id path parameter.
    """
    svc = get_graph_service()
    raw = svc.get_concept_clusters()
    return ConceptLinkedResponse(
        clusters=[ConceptClusterItem(**c) for c in raw]
    )


@router.get("/entities/{document_id}")
async def get_entities_by_type(
    document_id: str,
    type: str = Query(..., description="Entity type to filter by (e.g. LIBRARY, ALGORITHM)"),
) -> EntityListResponse:
    """Return entities of a specific type for a document.

    IMPORTANT: This route must be declared before GET /{document_id} to prevent
    FastAPI from matching 'entities' as a document_id path parameter.
    """
    svc = get_graph_service()
    raw = svc.get_entities_by_type(document_id, type)
    return EntityListResponse(entities=[EntityItem(**e) for e in raw])


@router.get("/{document_id}")
async def get_graph_for_document(
    document_id: str,
    type: str = Query(default="knowledge_graph"),
    include_notes: bool = Query(default=False),
) -> dict:
    """Return nodes and edges for a single document.

    Pass ?type=call_graph to get the function call graph (code documents only).
    Default is the knowledge entity graph.
    Pass ?include_notes=true to overlay Note nodes connected to entities in scope (S172).
    """
    svc = get_graph_service()
    if type == "call_graph":
        return svc.get_call_graph(document_id)
    return svc.get_graph_for_document(document_id, include_notes=include_notes)


@router.get("")
async def get_graph(
    doc_ids: str = Query(default=""),
    include_same_concept: bool = Query(default=False),
    include_notes: bool = Query(default=False),
) -> dict:
    """Return merged nodes and edges for multiple documents.

    Pass ?doc_ids=id1,id2,id3 to filter by specific documents.
    Returns all graph data if doc_ids is empty.
    Pass ?include_same_concept=true to include SAME_CONCEPT cross-book edges (S141).
    Pass ?include_notes=true to overlay Note nodes connected to entities in scope (S172).
    """
    svc = get_graph_service()
    if doc_ids:
        ids = [d.strip() for d in doc_ids.split(",") if d.strip()]
    else:
        ids = []
    return svc.get_graph_for_documents(
        ids,
        include_same_concept=include_same_concept,
        include_notes=include_notes,
    )
