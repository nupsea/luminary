import logging
import re
from collections import defaultdict
from typing import Literal

from sqlalchemy import text

from app.database import get_session_factory
from app.telemetry import trace_retrieval
from app.types import ScoredChunk

logger = logging.getLogger(__name__)

RRF_K = 60
# Fraction of top-k chunks from one section that triggers diversity re-ranking.
_DIVERSITY_THRESHOLD = 0.6


def _diversify(candidates: list[ScoredChunk], k: int) -> list[ScoredChunk]:
    """Section-diversity re-ranking for broad queries.

    When more than ``_DIVERSITY_THRESHOLD`` of the top-k candidates share the
    same section_heading the results are biased toward one part of the document.
    In that case, switch to a round-robin pick across sections (ordered by each
    section's best RRF score) so the final k chunks span the document breadth.

    Falls back to normal top-k when results are already diverse.
    """
    if len(candidates) <= k:
        return candidates

    top_k = candidates[:k]
    headings = [c.section_heading or "" for c in top_k]
    if headings:
        most_common_count = max(headings.count(h) for h in set(headings))
        concentration = most_common_count / len(headings)
    else:
        concentration = 0.0

    if concentration <= _DIVERSITY_THRESHOLD:
        return top_k

    # Group all candidates by section, preserving RRF-score order within each group.
    buckets: dict[str, list[ScoredChunk]] = defaultdict(list)
    for chunk in candidates:
        buckets[chunk.section_heading or ""].append(chunk)

    # Visit sections in order of their highest-scoring chunk (most relevant first).
    ordered_sections = sorted(buckets, key=lambda h: buckets[h][0].score, reverse=True)
    indices: dict[str, int] = {h: 0 for h in ordered_sections}

    result: list[ScoredChunk] = []
    while len(result) < k:
        added_this_round = False
        for heading in ordered_sections:
            if len(result) >= k:
                break
            idx = indices[heading]
            if idx < len(buckets[heading]):
                result.append(buckets[heading][idx])
                indices[heading] += 1
                added_this_round = True
        if not added_this_round:
            break

    logger.debug(
        "retrieval diversity: concentration=%.2f → round-robin across %d sections",
        concentration,
        len(ordered_sections),
    )
    return result


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a natural-language query for safe use in an FTS5 MATCH expression.

    FTS5 interprets punctuation (?, *, ^, (, ), ", +) and bare keywords
    AND/OR/NOT as query operators, causing syntax errors on ordinary questions.
    Strip everything except word characters and spaces, then remove FTS5 boolean
    operators so the query is treated as a plain term search.
    """
    # Remove all characters that are not word chars or whitespace
    cleaned = re.sub(r"[^\w\s]", " ", query)
    # Remove bare AND / OR / NOT (FTS5 boolean operators, case-insensitive)
    cleaned = re.sub(r"\b(AND|OR|NOT)\b", " ", cleaned, flags=re.IGNORECASE)
    # Collapse runs of whitespace
    return " ".join(cleaned.split())


class HybridRetriever:
    def vector_search(
        self,
        query: str,
        document_ids: list[str] | None,
        k: int,
    ) -> list[ScoredChunk]:
        """Embed query and search LanceDB; optionally filter by document_ids.

        Returns [] (not raises) when LanceDB table is empty or unavailable so that
        hybrid retrieval can fall back to keyword-only results gracefully.
        """
        try:
            from app.services.embedder import get_embedding_service
            from app.services.vector_store import get_lancedb_service

            svc = get_lancedb_service()
            # Check if any vectors exist before running a search.
            if svc.count_for_document(document_ids[0] if document_ids else "") == 0:
                # Table may be empty or doc not yet indexed; check total row count.
                try:
                    table = svc._get_table()
                    total = table.count_rows()
                except Exception:
                    total = 0
                if total == 0:
                    logger.debug("vector_search: LanceDB table empty, returning []")
                    return []

            vector = get_embedding_service().encode([query])[0]
            table = svc._get_table()
            search = table.search(vector).metric("cosine").limit(k)
            if document_ids:
                id_list = ", ".join(f"'{did}'" for did in document_ids)
                search = search.where(f"document_id IN ({id_list})", prefilter=True)
            rows = search.to_list()

            results: list[ScoredChunk] = []
            for row in rows:
                distance = float(row.get("_distance", 0.0))
                results.append(
                    ScoredChunk(
                        chunk_id=row["chunk_id"],
                        document_id=row["document_id"],
                        text=row["text"],
                        section_heading=row.get("section_heading", ""),
                        page=int(row.get("page", 0)),
                        score=1.0 - distance,
                        source="vector",
                    )
                )
            return results
        except Exception as exc:
            logger.warning("vector_search failed, returning []", exc_info=exc)
            return []

    async def keyword_search(
        self,
        query: str,
        document_ids: list[str] | None,
        k: int,
    ) -> list[ScoredChunk]:
        """BM25 search via SQLite FTS5; optionally filter by document_ids."""
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            # Query was entirely punctuation/operators — skip FTS and return empty
            logger.debug("keyword_search: query sanitized to empty string, skipping FTS")
            return []

        if document_ids:
            id_list = ", ".join(f"'{did}'" for did in document_ids)
            sql = text(
                "SELECT chunk_id, document_id, text, bm25(chunks_fts) AS score "
                "FROM chunks_fts "
                f"WHERE chunks_fts MATCH :query AND document_id IN ({id_list}) "
                "ORDER BY score LIMIT :k"
            )
        else:
            sql = text(
                "SELECT chunk_id, document_id, text, bm25(chunks_fts) AS score "
                "FROM chunks_fts "
                "WHERE chunks_fts MATCH :query "
                "ORDER BY score LIMIT :k"
            )

        async with get_session_factory()() as session:
            result = await session.execute(sql, {"query": safe_query, "k": k})
            rows = result.fetchall()

        return [
            ScoredChunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                text=row.text,
                section_heading="",
                page=0,
                score=float(row.score),
                source="keyword",
            )
            for row in rows
        ]

    def rrf_merge(
        self,
        vector_results: list[ScoredChunk],
        keyword_results: list[ScoredChunk],
        k: int = 10,
    ) -> list[ScoredChunk]:
        """Reciprocal Rank Fusion — combine, re-rank, then apply section diversity."""
        scores: dict[str, float] = {}
        meta: dict[str, ScoredChunk] = {}
        sources: dict[str, set[str]] = {}

        for rank, chunk in enumerate(vector_results, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            meta.setdefault(chunk.chunk_id, chunk)
            sources.setdefault(chunk.chunk_id, set()).add("vector")

        for rank, chunk in enumerate(keyword_results, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            meta.setdefault(chunk.chunk_id, chunk)
            sources.setdefault(chunk.chunk_id, set()).add("keyword")

        # Build ALL candidates sorted by RRF score (not truncated yet).
        # _diversify will pick the final k with section breadth in mind.
        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)

        candidates: list[ScoredChunk] = []
        for cid in sorted_ids:
            chunk = meta[cid]
            src_set = sources[cid]
            source: Literal["vector", "keyword", "both"] = (
                "both" if len(src_set) > 1 else next(iter(src_set))  # type: ignore[assignment]
            )
            candidates.append(
                ScoredChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    text=chunk.text,
                    section_heading=chunk.section_heading,
                    page=chunk.page,
                    score=scores[cid],
                    source=source,
                )
            )

        return _diversify(candidates, k)

    async def retrieve(
        self,
        query: str,
        document_ids: list[str] | None,
        k: int,
    ) -> list[ScoredChunk]:
        """Full hybrid retrieval: vector(k=20) + keyword(k=20) fused via RRF."""
        with trace_retrieval("hybrid", query=query) as span:
            vector_results = self.vector_search(query, document_ids, k=20)
            keyword_results = await self.keyword_search(query, document_ids, k=20)
            results = self.rrf_merge(vector_results, keyword_results, k=k)
            span.set_attribute("retrieval.chunk_count", len(results))
            if results:
                span.set_attribute("retrieval.top_score", round(results[0].score, 4))
        return results


_retriever: HybridRetriever | None = None


def get_retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever
