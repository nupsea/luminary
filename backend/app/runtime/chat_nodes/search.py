"""search_node and its retrieval-augmentation helpers.

intent='factual' / 'exploratory' (single-doc) path: hybrid retrieval
with parent-child context expansion (each chunk + its index-1 / +1
neighbors) and section-summary augmentation. For scope='all',
caps at 2 chunks per document so no single doc dominates context.
"""

import asyncio
import logging

from sqlalchemy import and_, or_, select

from app.database import get_session_factory
from app.models import ChunkModel, SectionSummaryModel
from app.services.context_packer import _cap_per_document
from app.services.retriever import get_retriever
from app.types import ChatState, ScoredChunk

logger = logging.getLogger(__name__)


async def _fetch_section_summaries(
    doc_heading_pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    """Batch-fetch SectionSummaryModel rows by (document_id, heading).

    Returns a dict mapping (document_id, heading) -> summary content.
    """
    if not doc_heading_pairs:
        return {}
    async with get_session_factory()() as session:
        # Build OR conditions for all (doc_id, heading) pairs

        conditions = [
            and_(
                SectionSummaryModel.document_id == doc_id,
                SectionSummaryModel.heading == heading,
            )
            for doc_id, heading in doc_heading_pairs
        ]
        rows = await session.execute(
            select(
                SectionSummaryModel.document_id,
                SectionSummaryModel.heading,
                SectionSummaryModel.content,
            ).where(or_(*conditions))
        )
        return {(row.document_id, row.heading): row.content for row in rows}


async def _fetch_neighbor_chunks(
    chunk_id: str, document_id: str, chunk_index: int
) -> list[tuple[int, str]]:
    """Fetch immediate neighbors (index-1, index+1) for a chunk to expand context."""
    async with get_session_factory()() as session:
        stmt = select(ChunkModel.chunk_index, ChunkModel.text).where(
            ChunkModel.document_id == document_id,
            ChunkModel.chunk_index.in_([chunk_index - 1, chunk_index + 1]),
        )
        rows = await session.execute(stmt)
        return [(row.chunk_index, row.text) for row in rows]


async def search_node(state: ChatState) -> dict:
    """Hybrid retrieval with context expansion and section summary augmentation.

    Context Expansion (Parent-Child):
    For each retrieved chunk, we fetch its immediate neighbors (index-1 and index+1)
    to provide a more coherent window to the LLM. This prevents "chopped up"
    information from hurting the answer quality.
    """
    q = state.get("rewritten_question") or state["question"]
    doc_ids = state.get("doc_ids") or []
    scope = state.get("scope", "all")
    effective_doc_ids = doc_ids if scope == "single" else None

    logger.info(
        "search_node: query=%r scope=%s filter_docs=%s",
        q[:80],
        scope,
        len(effective_doc_ids) if effective_doc_ids else "all",
    )

    # For library-wide queries use a tighter k to avoid scattered context
    k = 6 if scope == "all" else 10

    chunks_dicts: list[dict] = []
    image_ids: list[str] = []
    try:
        retriever = get_retriever()
        chunks: list[ScoredChunk]
        chunks, image_ids = await retriever.retrieve_with_images(q, effective_doc_ids, k=k)

        # Batch-fetch section summaries for all (document_id, section_heading) pairs
        pairs = [(c.document_id, c.section_heading) for c in chunks if c.section_heading]
        section_summary_map = await _fetch_section_summaries(pairs)

        # Context Expansion: fetch neighbors for each chunk
        neighbor_tasks = [
            _fetch_neighbor_chunks(c.chunk_id, c.document_id, c.chunk_index)
            if hasattr(c, "chunk_index")
            else asyncio.sleep(0, result=[])
            for c in chunks
        ]
        neighbors_list = await asyncio.gather(*neighbor_tasks)

        for c, neighbors in zip(chunks, neighbors_list, strict=False):
            # Sort and combine neighbors with the current chunk
            all_parts = [(c.chunk_index, c.text)] + (
                neighbors if isinstance(neighbors, list) else []
            )
            all_parts.sort(key=lambda x: x[0])
            expanded_text = "\n\n".join([p[1] for p in all_parts])

            section_summary = (
                section_summary_map.get((c.document_id, c.section_heading))
                if c.section_heading
                else None
            )
            augmented_text = expanded_text
            if section_summary:
                augmented_text = f"### {c.section_heading}\n{section_summary}\n---\n{expanded_text}"

            chunks_dicts.append(
                {
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "text": augmented_text,
                    "section_heading": c.section_heading,
                    "section_summary": section_summary,
                    "page": c.page,
                    "score": c.score,
                    "source": c.source,
                }
            )
    except Exception:
        logger.warning("search_node: retrieval failed", exc_info=True)

    # For scope='all': cap at 2 chunks per document so no single doc dominates context
    if scope == "all" and chunks_dicts:

        chunks_dicts = _cap_per_document(chunks_dicts, max_per_doc=2)

    logger.info("search_node: returning %d chunks, %d image_ids", len(chunks_dicts), len(image_ids))
    return {"chunks": chunks_dicts, "image_ids": image_ids}
