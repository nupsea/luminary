"""GET /search endpoint — hybrid cross-document search with grouping by document."""

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DocumentModel
from app.services.retriever import HybridRetriever, get_retriever

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    content_type: str
    section_heading: str
    page: int
    text_excerpt: str
    relevance_score: float


class DocumentGroup(BaseModel):
    document_id: str
    document_title: str
    content_type: str
    matches: list[SearchResult]


class SearchResponse(BaseModel):
    results: list[DocumentGroup]


@router.get("")
async def search(
    q: str = Query(..., min_length=1),
    content_types: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    retriever: HybridRetriever = Depends(get_retriever),
) -> SearchResponse:
    """Hybrid search across all documents. Returns results grouped by document."""
    # Resolve document_ids for content_type filter
    document_ids: list[str] | None = None
    if content_types:
        type_list = [t.strip() for t in content_types.split(",") if t.strip()]
        if type_list:
            result = await session.execute(
                select(DocumentModel.id).where(DocumentModel.content_type.in_(type_list))
            )
            document_ids = [str(row[0]) for row in result.fetchall()]
            if not document_ids:
                return SearchResponse(results=[])

    # Hybrid retrieval (vector + BM25)
    scored_chunks = await retriever.retrieve(q, document_ids=document_ids, k=limit)

    if not scored_chunks:
        return SearchResponse(results=[])

    # Fetch document metadata for all matching document IDs
    doc_ids = list({c.document_id for c in scored_chunks})
    doc_result = await session.execute(
        select(
            DocumentModel.id,
            DocumentModel.title,
            DocumentModel.content_type,
        ).where(DocumentModel.id.in_(doc_ids))
    )
    doc_map: dict[str, tuple[str, str]] = {
        str(row[0]): (row[1] or "Untitled", row[2] or "notes")
        for row in doc_result.fetchall()
    }

    # Build grouped results
    groups: dict[str, list[SearchResult]] = {}
    for chunk in scored_chunks:
        doc_id = chunk.document_id
        if doc_id not in doc_map:
            continue
        title, ctype = doc_map[doc_id]
        result_item = SearchResult(
            chunk_id=chunk.chunk_id,
            document_id=doc_id,
            document_title=title,
            content_type=ctype,
            section_heading=chunk.section_heading or "",
            page=chunk.page or 0,
            text_excerpt=chunk.text[:200],
            relevance_score=round(chunk.score, 4),
        )
        groups.setdefault(doc_id, []).append(result_item)

    return SearchResponse(
        results=[
            DocumentGroup(
                document_id=doc_id,
                document_title=doc_map[doc_id][0],
                content_type=doc_map[doc_id][1],
                matches=matches,
            )
            for doc_id, matches in groups.items()
        ]
    )
