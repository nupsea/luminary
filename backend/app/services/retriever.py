import asyncio
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

# Content types eligible for context expansion.
_EXPANSION_TYPES = {"book", "conversation", "notes"}
# Score multiplier for neighbour chunks added by context expansion.
_EXPANSION_SCORE_FACTOR = 0.75


def _round_robin(
    candidates: list[ScoredChunk],
    group_key: str,
    k: int,
    threshold: float,
) -> list[ScoredChunk] | None:
    """Generic round-robin diversifier over an arbitrary group key.

    Returns the k-capped round-robin result if the top-k candidates exceed
    *threshold* concentration on a single group value, else returns None
    (meaning the caller should not apply this diversifier).
    """
    if len(candidates) <= k:
        return None

    top_k = candidates[:k]
    values = [getattr(c, group_key) or "" for c in top_k]
    if values:
        most_common_count = max(values.count(v) for v in set(values))
        concentration = most_common_count / len(values)
    else:
        concentration = 0.0

    if concentration <= threshold:
        return None  # already diverse

    # Group all candidates by value, preserving score order within each group.
    buckets: dict[str, list[ScoredChunk]] = defaultdict(list)
    for chunk in candidates:
        key = getattr(chunk, group_key) or ""
        buckets[key].append(chunk)

    # Visit groups in order of their highest-scoring chunk (most relevant first).
    ordered_groups = sorted(buckets, key=lambda v: buckets[v][0].score, reverse=True)
    indices: dict[str, int] = {v: 0 for v in ordered_groups}

    result: list[ScoredChunk] = []
    while len(result) < k:
        added_this_round = False
        for group in ordered_groups:
            if len(result) >= k:
                break
            idx = indices[group]
            if idx < len(buckets[group]):
                result.append(buckets[group][idx])
                indices[group] += 1
                added_this_round = True
        if not added_this_round:
            break

    logger.debug(
        "retrieval diversity (%s): concentration=%.2f → round-robin across %d groups",
        group_key,
        concentration,
        len(ordered_groups),
    )
    return result


def _diversify(candidates: list[ScoredChunk], k: int) -> list[ScoredChunk]:
    """Speaker-then-section diversity re-ranking for broad queries.

    1. If any chunk has speaker != None, apply speaker-diversity first.
       When > _DIVERSITY_THRESHOLD of top-k share the same speaker, do
       round-robin across speakers.
    2. Else fall through to section-diversity (same logic on section_heading).
    3. Falls back to normal top-k when results are already diverse.
    """
    if len(candidates) <= k:
        return candidates

    # Speaker-diversity path (conversation documents)
    has_speaker = any(c.speaker is not None for c in candidates)
    if has_speaker:
        speaker_result = _round_robin(candidates, "speaker", k, _DIVERSITY_THRESHOLD)
        if speaker_result is not None:
            return speaker_result
        return candidates[:k]

    # Section-diversity path (books / notes)
    section_result = _round_robin(candidates, "section_heading", k, _DIVERSITY_THRESHOLD)
    if section_result is not None:
        return section_result
    return candidates[:k]


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


async def _expand_context(
    chunks: list[ScoredChunk],
    k: int,
    window: int = 1,
) -> list[ScoredChunk]:
    """Fetch adjacent chunks (±window) for eligible content types.

    For each ScoredChunk in the input list, queries SQLite for neighbouring
    chunks (chunk_index ± window) within the same document.  Neighbours get
    score = original_score * _EXPANSION_SCORE_FACTOR and source='context_expansion'.

    Rules:
    - Only applies to content types in _EXPANSION_TYPES ('book', 'conversation', 'notes').
    - Dedup: if a neighbour's chunk_id already exists in the result set, keep
      whichever has the higher score and discard the other.
    - Total result capped at k * 2 (sorted by score desc).
    """
    if not chunks:
        return chunks

    # Collect all document_ids to fetch content_types in a single query.
    doc_ids = list({c.document_id for c in chunks})

    async with get_session_factory()() as session:
        # Fetch content_type per document
        ct_result = await session.execute(
            text(
                "SELECT id, content_type FROM documents WHERE id IN ("
                + ", ".join(f"'{did}'" for did in doc_ids)
                + ")"
            )
        )
        content_types: dict[str, str] = {row[0]: row[1] for row in ct_result.fetchall()}

        # Check if any chunk qualifies for expansion
        eligible_docs = {did for did, ct in content_types.items() if ct in _EXPANSION_TYPES}
        if not eligible_docs:
            return chunks

        # Fetch chunk_index for all input chunks
        chunk_ids = [c.chunk_id for c in chunks]
        idx_result = await session.execute(
            text(
                "SELECT id, chunk_index FROM chunks WHERE id IN ("
                + ", ".join(f"'{cid}'" for cid in chunk_ids)
                + ")"
            )
        )
        chunk_index_map: dict[str, int] = {row[0]: row[1] for row in idx_result.fetchall()}

        # Gather all (document_id, target_index) pairs we need to fetch
        neighbor_queries: list[tuple[str, int, float]] = []
        for chunk in chunks:
            if chunk.document_id not in eligible_docs:
                continue
            cidx = chunk_index_map.get(chunk.chunk_id)
            if cidx is None:
                continue
            for delta in range(-window, window + 1):
                if delta == 0:
                    continue
                neighbor_queries.append(
                    (chunk.document_id, cidx + delta, chunk.score * _EXPANSION_SCORE_FACTOR)
                )

        # Build result set: start with original chunks
        result_map: dict[str, ScoredChunk] = {c.chunk_id: c for c in chunks}

        # Fetch neighbors
        for doc_id, target_idx, neighbor_score in neighbor_queries:
            nb_result = await session.execute(
                text(
                    "SELECT id, text, speaker, chunk_index FROM chunks "
                    "WHERE document_id = :doc_id AND chunk_index = :cidx"
                ),
                {"doc_id": doc_id, "cidx": target_idx},
            )
            row = nb_result.fetchone()
            if row is None:
                continue
            nb_id, nb_text, nb_speaker, nb_cidx = row

            if nb_id in result_map:
                # Dedup: keep higher score
                if neighbor_score > result_map[nb_id].score:
                    result_map[nb_id] = ScoredChunk(
                        chunk_id=nb_id,
                        document_id=doc_id,
                        text=nb_text,
                        section_heading="",
                        page=0,
                        score=neighbor_score,
                        source="context_expansion",
                        chunk_index=nb_cidx,
                        speaker=nb_speaker or None,
                    )
            else:
                result_map[nb_id] = ScoredChunk(
                    chunk_id=nb_id,
                    document_id=doc_id,
                    text=nb_text,
                    section_heading="",
                    page=0,
                    score=neighbor_score,
                    source="context_expansion",
                    chunk_index=nb_cidx,
                    speaker=nb_speaker or None,
                )

    # Sort by score desc, cap at k * 2
    expanded = sorted(result_map.values(), key=lambda c: c.score, reverse=True)
    return expanded[: k * 2]


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
                        chunk_index=int(row.get("chunk_index", 0)),
                        speaker=row.get("speaker") or None,
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
            fts_rows = result.fetchall()

            # Batch-fetch speaker and chunk_index from chunks table
            if fts_rows:
                fts_ids = [row.chunk_id for row in fts_rows]
                meta_result = await session.execute(
                    text(
                        "SELECT id, speaker, chunk_index FROM chunks WHERE id IN ("
                        + ", ".join(f"'{cid}'" for cid in fts_ids)
                        + ")"
                    )
                )
                meta_map: dict[str, tuple[str | None, int]] = {
                    row[0]: (row[1] or None, row[2] or 0) for row in meta_result.fetchall()
                }
            else:
                meta_map = {}

        return [
            ScoredChunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                text=row.text,
                section_heading="",
                page=0,
                score=float(row.score),
                source="keyword",
                chunk_index=meta_map.get(row.chunk_id, (None, 0))[1],
                speaker=meta_map.get(row.chunk_id, (None, 0))[0],
            )
            for row in fts_rows
        ]

    def rrf_merge(
        self,
        vector_results: list[ScoredChunk],
        keyword_results: list[ScoredChunk],
        k: int = 10,
        *,
        diversify: bool = True,
    ) -> list[ScoredChunk]:
        """Reciprocal Rank Fusion — combine, re-rank, then apply section diversity.

        When ``diversify=False``, returns the top-k by RRF score with no
        section/speaker re-ranking. Use this for focused per-document
        queries where breadth is undesirable -- diversification trades
        high-scoring chunks for section variety, which collapses HR@5
        when the question targets one section (S212 fix).
        """
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
                    chunk_index=chunk.chunk_index,
                    speaker=chunk.speaker,
                )
            )

        if not diversify:
            return candidates[:k]
        return _diversify(candidates, k)

    async def retrieve(
        self,
        query: str,
        document_ids: list[str] | None,
        k: int,
    ) -> list[ScoredChunk]:
        """Full hybrid retrieval: vector(k=20) + keyword(k=20) fused via RRF + context expansion.

        Diversity re-ranking is disabled when the query is scoped to a
        single document. In that case the user is asking a focused
        question and wants the highest-scoring chunks, not section
        breadth -- the diversifier was authored for broad cross-document
        queries where variety helps. Without this skip, top-scored
        chunks from one chapter get bumped down by less-relevant chunks
        from elsewhere in the same book and HR@5 collapses (S212).
        """
        scoped_single_doc = bool(document_ids) and len(document_ids or []) == 1
        # Widen the candidate pool when scoped to a single document. With a
        # cross-document corpus, 20+20 leaves enough headroom for RRF; with
        # a single book of ~500 chunks where the question phrasing diverges
        # from the answer phrasing, the right chunk can sit at rank 25-40
        # in vector or BM25 alone and never reach RRF (S212).
        candidate_pool = 50 if scoped_single_doc else 20
        with trace_retrieval("hybrid", query=query) as span:
            vector_results, keyword_results = await asyncio.gather(
                asyncio.to_thread(self.vector_search, query, document_ids, candidate_pool),
                self.keyword_search(query, document_ids, k=candidate_pool),
            )
            results = self.rrf_merge(
                vector_results,
                keyword_results,
                k=k,
                diversify=not scoped_single_doc,
            )
            results = await _expand_context(results, k=k)
            span.set_attribute("retrieval.chunk_count", len(results))
            if results:
                span.set_attribute("retrieval.top_score", round(results[0].score, 4))
        return results

    def _image_vector_search(
        self,
        query_vector: list[float],
        document_ids: list[str] | None,
        k: int = 5,
        threshold: float = 0.5,
    ) -> list[str]:
        """Search image_vectors_v1 by embedding similarity; return matching image_ids."""
        try:
            from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

            rows = get_lancedb_service().search_image_vectors(
                query_vector, document_ids, k=k, threshold=threshold
            )
            return [row["image_id"] for row in rows if row.get("image_id")]
        except Exception as exc:
            logger.warning("_image_vector_search failed: %s", exc)
            return []

    async def _image_keyword_search(
        self,
        query: str,
        document_ids: list[str] | None,
        k: int = 5,
    ) -> list[str]:
        """BM25 search images_fts; return matching image_ids."""
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            return []

        if document_ids:
            id_list = ", ".join(f"'{did}'" for did in document_ids)
            sql = text(
                "SELECT image_id FROM images_fts "
                f"WHERE images_fts MATCH :query AND document_id IN ({id_list}) "
                "LIMIT :k"
            )
        else:
            sql = text("SELECT image_id FROM images_fts WHERE images_fts MATCH :query LIMIT :k")

        try:
            async with get_session_factory()() as session:
                result = await session.execute(sql, {"query": safe_query, "k": k})
                return [row[0] for row in result.fetchall() if row[0]]
        except Exception as exc:
            logger.warning("_image_keyword_search failed: %s", exc)
            return []

    async def retrieve_with_images(
        self,
        query: str,
        document_ids: list[str] | None,
        k: int,
    ) -> tuple[list[ScoredChunk], list[str]]:
        """Hybrid retrieval returning chunks and matched image_ids.

        Runs the standard retrieve() pipeline and in parallel searches image
        embeddings and image FTS5 index for visually matching content.
        Returns (chunks, deduplicated_image_ids).
        """
        try:
            from app.services.embedder import get_embedding_service  # noqa: PLC0415

            chunks = await self.retrieve(query, document_ids, k)
            query_vector = get_embedding_service().encode([query])[0]
            image_ids_vec = self._image_vector_search(
                query_vector, document_ids, k=5, threshold=0.5
            )
            image_ids_fts = await self._image_keyword_search(query, document_ids, k=5)

            seen: set[str] = set()
            image_ids: list[str] = []
            for iid in image_ids_vec + image_ids_fts:
                if iid not in seen:
                    seen.add(iid)
                    image_ids.append(iid)

            return chunks, image_ids
        except Exception as exc:
            logger.warning("retrieve_with_images: falling back to retrieve() only: %s", exc)
            chunks = await self.retrieve(query, document_ids, k)
            return chunks, []


_retriever: HybridRetriever | None = None


def get_retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever
