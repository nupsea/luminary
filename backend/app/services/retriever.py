import logging
from typing import Literal

from sqlalchemy import text

from app.database import get_session_factory
from app.telemetry import trace_retrieval
from app.types import ScoredChunk

logger = logging.getLogger(__name__)

RRF_K = 60


class HybridRetriever:
    def vector_search(
        self,
        query: str,
        document_ids: list[str] | None,
        k: int,
    ) -> list[ScoredChunk]:
        """Embed query and search LanceDB; optionally filter by document_ids."""
        from app.services.embedder import get_embedding_service
        from app.services.vector_store import get_lancedb_service

        vector = get_embedding_service().encode([query])[0]
        table = get_lancedb_service()._get_table()
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

    async def keyword_search(
        self,
        query: str,
        document_ids: list[str] | None,
        k: int,
    ) -> list[ScoredChunk]:
        """BM25 search via SQLite FTS5; optionally filter by document_ids."""
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
            result = await session.execute(sql, {"query": query, "k": k})
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
        """Reciprocal Rank Fusion — combine and re-rank vector + keyword results."""
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

        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:k]

        merged: list[ScoredChunk] = []
        for cid in sorted_ids:
            chunk = meta[cid]
            src_set = sources[cid]
            source: Literal["vector", "keyword", "both"] = (
                "both" if len(src_set) > 1 else next(iter(src_set))  # type: ignore[assignment]
            )
            merged.append(
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
        return merged

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
