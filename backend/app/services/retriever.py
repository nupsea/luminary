import asyncio
import logging
from datetime import date
from typing import Literal

from sqlalchemy import text

from app import config as _config_module  # indirect: get_settings is patched
from app.database import get_session_factory
from app.services import embedder as _embedder_module  # indirect: get_embedding_service is patched
from app.services import query_spellcorrect as _spellcorrect_module
from app.services import (
    vector_store as _vector_store_module,  # indirect: get_lancedb_service is patched
)
from app.services.retriever_strategies import (  # noqa: F401
    _GRAPH_EXPAND_MAX_TOKENS,
    _diversify,
    _expand_context,
    _get_reranker,
    _graph_expand,
    _hyde_expand,
    _sanitize_fts_query,
)
from app.telemetry import trace_retrieval
from app.types import ScoredChunk

logger = logging.getLogger(__name__)

RetrievalStrategy = Literal["rrf", "vector", "fts", "graph"]

RRF_K = 60
# Guardrail on request-supplied rerank depth: cross-encoder latency is linear
# in depth (~5ms/pair CPU), so an unbounded value turns /search into a DoS
# vector against local CPUs.
_RERANK_DEPTH_MAX = 200


def _parse_iso_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _minmax(xs: list[float]) -> list[float]:
    lo, hi = min(xs), max(xs)
    if hi - lo < 1e-9:
        return [0.5 for _ in xs]
    return [(x - lo) / (hi - lo) for x in xs]


# Signal-adaptive blend ("guard-when-CE-weak"). A fixed RRF-heavy alpha helps
# only when the cross-encoder is weaker than RRF; a broad 12-doc sweep showed
# it drags a *strong* CE down on most content. So instead of a constant alpha,
# scale it by CE CONFIDENCE: when the top CE score sits many std devs above the
# pool mean (a clear winner), trust the CE (alpha -> 0); when the CE scores are
# flat/uncertain, fall back toward RRF (alpha -> alpha_max). z-score is scale-
# invariant, so this needs no CE-model-specific threshold.
_ADAPTIVE_Z_LOW = 1.0  # top CE this flat above the mean -> lean fully on RRF
_ADAPTIVE_Z_HIGH = 3.0  # top CE this peaked -> trust CE, no RRF pull


def _adaptive_alpha(ce: list[float], alpha_max: float) -> float:
    n = len(ce)
    if n < 3:
        return alpha_max
    mean = sum(ce) / n
    std = (sum((x - mean) ** 2 for x in ce) / n) ** 0.5
    if std < 1e-9:
        return alpha_max
    z = (max(ce) - mean) / std
    t = (z - _ADAPTIVE_Z_LOW) / (_ADAPTIVE_Z_HIGH - _ADAPTIVE_Z_LOW)
    t = max(0.0, min(1.0, t))
    return alpha_max * (1.0 - t)


def _rerank_candidates(
    query: str,
    candidates: list[ScoredChunk],
    k: int,
    threshold: float | None = None,
    blend_alpha: float | None = None,
    adaptive: bool = False,
) -> list[ScoredChunk]:
    """Re-score *candidates* with a cross-encoder and return the top *k*.

    The cross-encoder reads each (query, chunk_text) pair jointly, unlike
    bi-encoder retrieval which embeds them independently. This catches
    chunks whose vocabulary diverges from the question's surface form but
    semantically answer it -- the dominant failure mode.

    When *threshold* is set, candidates scoring below it are dropped after
    re-ranking -- a precision cut so generation is not fed confidently-ranked
    junk. The top candidate always survives: an all-empty context would
    silently break the chat flow, and "nothing relevant" belongs to the
    generation layer's honesty handling, not a retrieval-side cliff.

    Fails soft: any model load or inference error logs a warning and falls
    back to ``candidates[:k]`` (threshold unapplied -- there are no
    cross-encoder scores to cut on) so retrieval is never harder than the
    no-rerank baseline.
    """
    if not candidates:
        return candidates
    try:
        ce = [float(s) for s in _get_reranker().score(query, [c.text for c in candidates])]
    except Exception as exc:
        logger.warning("rerank failed, falling back to RRF order: %s", exc)
        return candidates[:k]

    # blend_alpha convex-combines the RRF score (candidates still carry it here)
    # with the CE score so a confident RRF hit resists a weak CE demotion.
    # None == 0.0 == pure CE. Scores are ALWAYS minmax-normalised to [0, 1]:
    # raw ms-marco logits are often negative, and downstream consumers assume
    # non-negative scores -- _expand_context's `score * factor` neighbour
    # discount silently PROMOTED neighbours above their reranked parents on
    # negative logits, inverting the cross-encoder's ordering.
    alpha = blend_alpha if blend_alpha is not None else 0.0
    if adaptive:
        alpha = _adaptive_alpha(ce, alpha)
    ce_n = _minmax(ce)
    if alpha > 0.0:
        rrf_n = _minmax([c.score for c in candidates])
        final = [alpha * rrf_n[i] + (1.0 - alpha) * ce_n[i] for i in range(len(ce))]
    else:
        final = ce_n

    order = sorted(range(len(candidates)), key=lambda i: final[i], reverse=True)
    # The threshold is a precision cut on the CE logit's native scale, so it
    # applies to CE regardless of how the ordering was scored.
    if threshold is not None:
        kept = [i for i in order if ce[i] >= threshold]
        if len(kept) < len(order):
            logger.info(
                "rerank threshold %.2f cut %d/%d candidates",
                threshold,
                len(order) - len(kept),
                len(order),
            )
        order = kept or order[:1]
    return [
        ScoredChunk(
            chunk_id=candidates[i].chunk_id,
            document_id=candidates[i].document_id,
            text=candidates[i].text,
            section_heading=candidates[i].section_heading,
            page=candidates[i].page,
            score=final[i],
            source=candidates[i].source,
            chunk_index=candidates[i].chunk_index,
            speaker=candidates[i].speaker,
        )
        for i in order[:k]
    ]


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

            svc = _vector_store_module.get_lancedb_service()
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

            vector = _embedder_module.embed_query(query)
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

    async def _fts_match(
        self,
        session,
        fts_query: str,
        document_ids: list[str] | None,
        k: int,
    ) -> list[ScoredChunk]:
        """Run one FTS5 MATCH and hydrate ScoredChunks (BM25 order preserved)."""
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
        result = await session.execute(sql, {"query": fts_query, "k": k})
        fts_rows = result.fetchall()
        if not fts_rows:
            return []
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

    async def keyword_search(
        self,
        query: str,
        document_ids: list[str] | None,
        k: int,
    ) -> list[ScoredChunk]:
        """BM25 search via SQLite FTS5, precision-first with OR backfill.

        FTS5 treats space-separated terms as an implicit AND (every term must be
        in one chunk), which is precise but returns nothing for a full-sentence
        query. So we run the AND form first for precision; if it under-fills k, an
        OR pass (match any term, BM25-ranked) backfills the remaining slots while
        keeping the exact AND hits ranked on top.
        """
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            logger.debug("keyword_search: query sanitized to empty string, skipping FTS")
            return []
        terms = safe_query.split()
        async with get_session_factory()() as session:
            rows = await self._fts_match(session, safe_query, document_ids, k)
            if len(rows) < k and len(terms) > 1:
                or_rows = await self._fts_match(
                    session, " OR ".join(terms), document_ids, k
                )
                seen = {r.chunk_id for r in rows}
                for r in or_rows:
                    if r.chunk_id not in seen:
                        rows.append(r)
                        seen.add(r.chunk_id)
                        if len(rows) >= k:
                            break
        return rows[:k]

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
        when the question targets one section
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

    async def _filter_by_entry_date(
        self,
        results: list[ScoredChunk],
        date_from: date | None,
        date_to: date | None,
    ) -> list[ScoredChunk]:
        """Keep only chunks whose content date (entry_date) falls in the range.
        Undated chunks are DROPPED -- a temporal query wants dated content."""
        if not results:
            return results
        ids = [c.chunk_id for c in results]
        id_list = ", ".join(f"'{i}'" for i in ids)
        async with get_session_factory()() as session:
            rows = (
                await session.execute(
                    text(f"SELECT id, entry_date FROM chunks WHERE id IN ({id_list})")
                )
            ).fetchall()
        dmap: dict[str, date] = {}
        for cid, ed in rows:
            if ed is None:
                continue
            d = ed if isinstance(ed, date) else _parse_iso_date(ed)
            if d is not None:
                dmap[cid] = d

        def _ok(cid: str) -> bool:
            d = dmap.get(cid)
            if d is None:
                return False
            if date_from is not None and d < date_from:
                return False
            return not (date_to is not None and d > date_to)

        return [c for c in results if _ok(c.chunk_id)]

    async def retrieve(
        self,
        query: str,
        document_ids: list[str] | None,
        k: int,
        *,
        hyde: bool = False,
        rerank: bool = False,
        rerank_depth: int | None = None,
        rerank_threshold: float | None = None,
        rerank_blend: float | None = None,
        rerank_adaptive: bool | None = None,
        spell_correct: bool | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        graph_expand: bool = True,
        expand_context: bool = True,
        strategy: RetrievalStrategy = "rrf",
    ) -> list[ScoredChunk]:
        """Full hybrid retrieval: vector(k=20) + keyword(k=20) fused via RRF + context expansion.

        *expand_context=False* skips the neighbour-window expansion and returns
        the raw ranked list. The eval harness needs this to measure L1 pool
        recall exactly: expansion appends neighbours the cross-encoder never
        saw, which would leak past the "reranked HR@k is bounded by pool
        recall@depth" invariant the ablation exists to test.

        Diversity re-ranking is disabled when the query is scoped to a
        single document. In that case the user is asking a focused
        question and wants the highest-scoring chunks, not section
        breadth -- the diversifier was authored for broad cross-document
        queries where variety helps. Without this skip, top-scored
        chunks from one chapter get bumped down by less-relevant chunks
        from elsewhere in the same book and HR@5 collapses

        When *hyde* is True, generates a hypothetical answer via the local
        LLM and uses ``"<query> <answer>"`` as the search query for both
        vector and BM25. This bridges question/answer phrasing divergence
       : the hypothetical contains likely answer vocabulary that
        the bare question lacks. Falls back to the original query on LLM
        failure so retrieval is never harder than the no-hyde baseline.

        When *rerank* is True, the top-N RRF candidates are re-scored by a
        cross-encoder and the top-k of that re-ranking is returned. The
        cross-encoder reads (query, chunk) pairs jointly, so it catches
        answer chunks whose vocabulary diverges from the question's surface
        form -- the dominant remaining failure mode. Diversification
        is skipped when reranking (the cross-encoder already optimises for
        relevance, and section breadth would dilute the rerank signal).
        Fails soft: any reranker error returns the RRF order unchanged.

        *rerank_depth* overrides the settings-default candidate pool fed to
        the cross-encoder; *rerank_threshold* overrides the settings-default
        score cut. Both are per-request so the eval harness can sweep them
        without process restarts.
        """
        settings = _config_module.get_settings()
        # Correct typo'd query tokens to their nearest corpus term BEFORE any
        # leg runs, so a mistyped proper noun can't collapse corpus-wide search
        # to the wrong documents. Threaded: the first call builds a vocab.
        do_spell = spell_correct if spell_correct is not None else settings.QUERY_SPELL_CORRECT
        if do_spell:
            corrected = await asyncio.to_thread(_spellcorrect_module.correct_query, query)
            if corrected != query:
                logger.info("spell-corrected query: %r -> %r", query, corrected)
                query = corrected
        scoped_single_doc = bool(document_ids) and len(document_ids or []) == 1
        # Widen the candidate pool when scoped to a single document. With a
        # cross-document corpus, 20+20 leaves enough headroom for RRF; with
        # a single book of ~500 chunks where the question phrasing diverges
        # from the answer phrasing, the right chunk can sit at rank 25-40
        # in vector or BM25 alone and never reach RRF.
        # When rerank=True the pool IS the L2 depth: the cross-encoder can
        # only recover chunks L1 hands it, so depth bounds reranked HR@k.
        # Without rerank the pool still floors at k: a caller asking for
        # limit=200 (the eval harness measuring L1 pool recall) must get legs
        # that deep, not a fused 50+50 pool silently truncating the request.
        if rerank:
            depth = rerank_depth if rerank_depth is not None else settings.RERANK_DEPTH
            candidate_pool = max(k, min(depth, _RERANK_DEPTH_MAX))
        elif scoped_single_doc:
            candidate_pool = max(k, 50)
        else:
            candidate_pool = max(k, 20)
        # Deepen the pool when date-filtering so enough date-valid chunks
        # survive the post-merge cut (the legs can't filter entry_date directly).
        date_filtering = date_from is not None or date_to is not None
        if date_filtering:
            candidate_pool = min(max(candidate_pool, 60) * 2, _RERANK_DEPTH_MAX)
        threshold = (
            rerank_threshold if rerank_threshold is not None else settings.RERANK_SCORE_THRESHOLD
        )
        blend = rerank_blend if rerank_blend is not None else settings.RERANK_BLEND_ALPHA
        adaptive = (
            rerank_adaptive if rerank_adaptive is not None else settings.RERANK_BLEND_ADAPTIVE
        )

        # graph_expand flows only into the dense vector search. Embeddings
        # reward semantic similarity, so appending canonical entity tokens
        # helps match chunks whose surface form differs from the question.
        # SQLite FTS5 MATCH uses AND semantics across terms, so appending
        # tokens that may be absent from the corpus collapses BM25 recall to
        # zero -- keep the keyword side on the unexpanded query.
        # HyDE, by contrast, augments with a full hypothetical answer that is
        # designed to share vocabulary with the source text, so it flows into
        # both vector and keyword (preserving the behavior).
        vector_query = await _graph_expand(query) if graph_expand and strategy == "rrf" else query
        keyword_query = query
        if hyde:
            vector_query = await _hyde_expand(vector_query)
            keyword_query = vector_query

        with trace_retrieval("hybrid", query=query) as span:
            span.set_attribute("retrieval.hyde", hyde)
            span.set_attribute("retrieval.rerank", rerank)
            span.set_attribute("retrieval.graph_expand", graph_expand)
            span.set_attribute("retrieval.strategy", strategy)
            if rerank:
                span.set_attribute("retrieval.rerank_depth", candidate_pool)
                if threshold is not None:
                    span.set_attribute("retrieval.rerank_threshold", threshold)
            if strategy == "vector":
                results = await asyncio.to_thread(
                    self.vector_search, query, document_ids, candidate_pool
                )
                results = results[:k]
                span.set_attribute("retrieval.chunk_count", len(results))
                return results
            if strategy == "fts":
                results = await self.keyword_search(query, document_ids, k=candidate_pool)
                results = results[:k]
                span.set_attribute("retrieval.chunk_count", len(results))
                return results
            if strategy == "graph":
                expanded_query = await _graph_expand(query)
                results = await asyncio.to_thread(
                    self.vector_search, expanded_query, document_ids, candidate_pool
                )
                results = results[:k]
                span.set_attribute("retrieval.chunk_count", len(results))
                return results

            vector_results, keyword_results = await asyncio.gather(
                asyncio.to_thread(self.vector_search, vector_query, document_ids, candidate_pool),
                self.keyword_search(keyword_query, document_ids, k=candidate_pool),
            )
            # When reranking, ask rrf_merge for the full candidate pool so the
            # cross-encoder can re-score them. Skip diversification regardless
            # of single-doc scope -- relevance reranking and section breadth
            # are orthogonal goals; mixing them dilutes the rerank signal.
            merge_k = candidate_pool if (rerank or date_filtering) else k
            diversify = (not rerank) and (not scoped_single_doc)
            results = self.rrf_merge(
                vector_results,
                keyword_results,
                k=merge_k,
                diversify=diversify,
            )
            if date_filtering:
                results = await self._filter_by_entry_date(results, date_from, date_to)
                if not rerank:
                    results = results[:k]
            if rerank:
                # Use the original query (not the HyDE-augmented one) for the
                # cross-encoder. Iteration 6 verified that passing the augmented
                # query regresses Time Machine HR@5 (0.50 -> 0.43): the LLM
                # hypothetical introduces vocabulary that does not appear in the
                # source text, and the cross-encoder rewards chunks containing
                # that hallucinated vocabulary over the answer chunks. The
                # original query is the user's authoritative intent.
                results = await asyncio.to_thread(
                    _rerank_candidates, query, results, k, threshold, blend, adaptive
                )
            if expand_context:
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

            rows = _vector_store_module.get_lancedb_service().search_image_vectors(
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
        *,
        rerank: bool = False,
        rerank_depth: int | None = None,
        rerank_threshold: float | None = None,
        rerank_blend: float | None = None,
        rerank_adaptive: bool | None = None,
        spell_correct: bool | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[list[ScoredChunk], list[str]]:
        """Hybrid retrieval returning chunks and matched image_ids.

        Runs the standard retrieve() pipeline and in parallel searches image
        embeddings and image FTS5 index for visually matching content.
        Returns (chunks, deduplicated_image_ids).
        """
        try:

            chunks = await self.retrieve(
                query,
                document_ids,
                k,
                rerank=rerank,
                rerank_depth=rerank_depth,
                rerank_threshold=rerank_threshold,
                rerank_blend=rerank_blend,
                rerank_adaptive=rerank_adaptive,
                spell_correct=spell_correct,
                date_from=date_from,
                date_to=date_to,
            )
            # An image reference must come from a document that actually
            # contributed to the answer. For a library-wide query (document_ids
            # is None) an unscoped image search matches the whole corpus and can
            # attach an unrelated document's image — e.g. a tech diagram on an
            # Odyssey answer. Scope image search to the retrieved chunks' docs.
            answer_doc_ids = list({c.document_id for c in chunks if c.document_id})
            if not answer_doc_ids:
                return chunks, []
            query_vector = _embedder_module.embed_query(query)
            image_ids_vec = self._image_vector_search(
                query_vector, answer_doc_ids, k=5, threshold=0.5
            )
            image_ids_fts = await self._image_keyword_search(query, answer_doc_ids, k=5)

            seen: set[str] = set()
            image_ids: list[str] = []
            for iid in image_ids_vec + image_ids_fts:
                if iid not in seen:
                    seen.add(iid)
                    image_ids.append(iid)

            return chunks, image_ids
        except Exception as exc:
            logger.warning("retrieve_with_images: falling back to retrieve() only: %s", exc)
            chunks = await self.retrieve(
                query,
                document_ids,
                k,
                rerank=rerank,
                rerank_depth=rerank_depth,
                rerank_threshold=rerank_threshold,
                rerank_blend=rerank_blend,
                rerank_adaptive=rerank_adaptive,
                spell_correct=spell_correct,
                date_from=date_from,
                date_to=date_to,
            )
            return chunks, []


_retriever: HybridRetriever | None = None


def get_retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever
