import asyncio
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import text

from app import config as _config_module  # indirect: get_settings is patched
from app.database import get_session_factory
from app.services import embedder as _embedder_module  # indirect: get_embedding_service is patched
from app.services import graph as _graph_module  # indirect: get_graph_service is patched
from app.services import llm as _llm_module  # indirect: get_llm_service is patched
from app.services import ner as _ner_module  # indirect: get_entity_extractor is patched
from app.services import (
    vector_store as _vector_store_module,  # indirect: get_lancedb_service is patched
)
from app.services.entity_disambiguator import find_canonical
from app.telemetry import trace_retrieval
from app.types import ScoredChunk

logger = logging.getLogger(__name__)

RetrievalStrategy = Literal["rrf", "vector", "fts", "graph"]

RRF_K = 60
# Fraction of top-k chunks from one section that triggers diversity re-ranking.
_DIVERSITY_THRESHOLD = 0.6

# Content types eligible for context expansion.
_EXPANSION_TYPES = {"book", "conversation", "notes"}
# Score multiplier for neighbour chunks added by context expansion.
_EXPANSION_SCORE_FACTOR = 0.75

# Cross-encoder reranker (S212 iter 5). Direct query/chunk semantic scoring
# complements RRF: when question phrasing diverges from answer phrasing, a
# cross-encoder still surfaces chunks that contain the answer fact. Local-first
# per I-16 -- runs on CPU, ~80MB model, no external service. The model is
# loaded lazily on first use; failures fail-soft to the original RRF order so
# a missing model never breaks /search.
_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
# Top-N RRF candidates fed into the reranker. 50 is generous enough for the
# answer chunk to be reachable when its rank in either vector or BM25 is in
# the 30s, while keeping cross-encoder latency under ~250ms per query on CPU.
_RERANK_CANDIDATE_POOL = 50

# HyDE (Hypothetical Document Embeddings) prompt -- generates a brief, plausible
# answer to the user's question so retrieval can match on the *answer's*
# vocabulary, not the question's. Mitigates question/answer phrasing
# divergence (S212): e.g. "What was the name of the Eloi girl?" embeds far from
# the answer chunk "her name was Weena" because the question never mentions
# Weena. The hypothetical answer bridges that gap. Local Ollama default per I-16.
#
# Output is intentionally terse: a verbose hypothetical dilutes the BM25 signal
# with model-introduced filler vocabulary that does not exist in the source
# text. We want concrete answer keywords, not natural prose.
_HYDE_SYSTEM = (
    "You are a knowledgeable assistant. Given a question, write a brief 1-2 "
    "sentence factual answer that would plausibly appear in the source text. "
    "Make a reasonable guess based on common knowledge if uncertain -- do not "
    "refuse or say 'I don't know'. Output the answer only, no preamble."
)
# llama3.2:3b is fast (~1s warm) and produces usable hypotheticals for general
# questions. For domain-specific questions where the model lacks knowledge, the
# hypothetical at worst adds neutral noise; the call fails-soft so retrieval
# is never worse than the no-hyde baseline. Local-first per I-16.
_HYDE_MODEL = "ollama/llama3.2:3b"
_HYDE_TIMEOUT_S = 20.0

# Graph-augmented deterministic query expansion (S225). Detect entities in the
# query via GLiNER, resolve to canonical labels via EntityDisambiguator, then
# fetch alias surface forms from the Kuzu Entity.aliases column. The expanded
# query bridges the question/answer vocabulary gap deterministically (no LLM
# in the query path -> no hallucination, no run-to-run variance, I-16 clean).
# Pairs with S224 index-time entity injection so both sides speak the same
# canonical-entity vocabulary.
_GRAPH_EXPAND_TYPES = {"PERSON", "ORGANIZATION", "PLACE", "CONCEPT"}
_GRAPH_EXPAND_MAX_ALIASES_PER_ENTITY = 5
_GRAPH_EXPAND_MAX_TOKENS = 30


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

    expanded_by_id: dict[str, ScoredChunk] = {chunk.chunk_id: chunk for chunk in chunks}

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

        for chunk in chunks:
            if chunk.document_id not in eligible_docs:
                continue

            surrounding_result = await session.execute(
                text(
                    "SELECT id, chunk_index, text, page_number, speaker FROM chunks "
                    "WHERE document_id = :doc_id "
                    "AND chunk_index >= :start_idx AND chunk_index <= :end_idx "
                    "ORDER BY chunk_index ASC"
                ),
                {
                    "doc_id": chunk.document_id,
                    "start_idx": chunk.chunk_index - window,
                    "end_idx": chunk.chunk_index + window,
                },
            )

            for row in surrounding_result.fetchall():
                neighbor_id = row[0]
                if neighbor_id == chunk.chunk_id:
                    continue

                neighbor_score = chunk.score * _EXPANSION_SCORE_FACTOR
                existing = expanded_by_id.get(neighbor_id)
                if existing is not None and existing.score >= neighbor_score:
                    continue

                expanded_by_id[neighbor_id] = ScoredChunk(
                    chunk_id=neighbor_id,
                    document_id=chunk.document_id,
                    text=row[2],
                    section_heading=chunk.section_heading,
                    page=row[3] or 0,
                    score=neighbor_score,
                    source="context_expansion",
                    chunk_index=row[1],
                    speaker=row[4],
                )

    return sorted(expanded_by_id.values(), key=lambda c: c.score, reverse=True)[: k * 2]


class _CrossEncoderReranker:
    """Lazy singleton wrapping the sentence-transformers CrossEncoder.

    Held at module level so the (slow) model load happens once per process.
    The model file is cached under ``$DATA_DIR/models/ms-marco-minilm`` -- same
    pattern as the embedder so all ML weights live under one folder.
    """

    def __init__(self) -> None:
        self._model: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import CrossEncoder  # noqa: PLC0415


        settings = _config_module.get_settings()
        cache_dir = Path(settings.DATA_DIR).expanduser() / "models" / "ms-marco-minilm"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._model = CrossEncoder(_RERANK_MODEL, cache_folder=str(cache_dir), device="cpu")
        logger.info("Loaded cross-encoder reranker %s", _RERANK_MODEL)

    def score(self, query: str, texts: list[str]) -> list[float]:
        self._load()
        if not texts:
            return []
        pairs = [(query, t) for t in texts]
        raw = self._model.predict(pairs, batch_size=32, show_progress_bar=False)
        return [float(s) for s in raw]


_reranker: _CrossEncoderReranker | None = None


def _get_reranker() -> _CrossEncoderReranker:
    global _reranker
    if _reranker is None:
        _reranker = _CrossEncoderReranker()
    return _reranker


def _rerank_candidates(
    query: str,
    candidates: list[ScoredChunk],
    k: int,
) -> list[ScoredChunk]:
    """Re-score *candidates* with a cross-encoder and return the top *k*.

    The cross-encoder reads each (query, chunk_text) pair jointly, unlike
    bi-encoder retrieval which embeds them independently. This catches
    chunks whose vocabulary diverges from the question's surface form but
    semantically answer it -- the dominant S212 failure mode.

    Fails soft: any model load or inference error logs a warning and falls
    back to ``candidates[:k]`` so retrieval is never harder than the no-rerank
    baseline.
    """
    if not candidates:
        return candidates
    try:
        scores = _get_reranker().score(query, [c.text for c in candidates])
    except Exception as exc:
        logger.warning("rerank failed, falling back to RRF order: %s", exc)
        return candidates[:k]

    rescored = [
        ScoredChunk(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            text=c.text,
            section_heading=c.section_heading,
            page=c.page,
            score=s,
            source=c.source,
            chunk_index=c.chunk_index,
            speaker=c.speaker,
        )
        for c, s in zip(candidates, scores, strict=True)
    ]
    rescored.sort(key=lambda c: c.score, reverse=True)
    return rescored[:k]


async def _hyde_expand(query: str, timeout: float = _HYDE_TIMEOUT_S) -> str:
    """Generate a hypothetical answer to *query* and return *query + " " + answer*.

    Used to bridge question/answer phrasing divergence in retrieval. Fails
    soft: any LLM error (Ollama down, timeout, model missing) returns the
    original query unchanged so the eval can still proceed and the user
    still gets standard hybrid retrieval.
    """
    try:

        llm = _llm_module.get_llm_service()
        result = await llm.generate(
            prompt=f"Question: {query}\n\nAnswer:",
            system=_HYDE_SYSTEM,
            model=_HYDE_MODEL,
            timeout=timeout,
        )
        if isinstance(result, str) and result.strip():
            return f"{query} {result.strip()}"
    except Exception as exc:
        logger.warning("hyde_expand failed, falling back to original query: %s", exc)
    return query


async def _graph_expand(query: str) -> str:
    """Expand *query* with canonical entity labels and aliases from the graph.

    Detects entities in the query via GLiNER, resolves them to canonical
    surface forms via :func:`find_canonical`, and fetches up to
    :data:`_GRAPH_EXPAND_MAX_ALIASES_PER_ENTITY` aliases per entity from the
    Kuzu ``Entity.aliases`` column. The total appended tokens are capped at
    :data:`_GRAPH_EXPAND_MAX_TOKENS` to bound BM25 dilution.

    Fails soft -- returns *query* unchanged when GLiNER finds no entities,
    when Kuzu is unreachable, or when any error occurs in the pipeline. No
    LLM is called and no external API is touched (I-16 clean).
    """
    try:
        # I-5: lazy imports to avoid retriever <-> services circular chains.

        extractor = _ner_module.get_entity_extractor()
        # Direct sync call -- single short query, GLiNER inference takes ~30ms
        # warm. Wrapping in asyncio.to_thread here causes ThreadPoolExecutor /
        # LanceDB BackgroundLoop contention in pytest that surfaces as an
        # IO Spill error during prior ingestion steps (S225 iter).
        entities = extractor.extract(
            [{"id": "q", "document_id": "q", "text": query}],
            "general",
        )
        # Filter to query-relevant types and dedupe by canonical label.
        canonical_seen: set[str] = set()
        canonical_entities: list[tuple[str, str]] = []
        for ent in entities:
            etype = ent.get("type", "")
            ename = (ent.get("name") or "").strip()
            if etype not in _GRAPH_EXPAND_TYPES or not ename:
                continue
            canonical = find_canonical(ename, etype, []).lower()
            if canonical in canonical_seen:
                continue
            canonical_seen.add(canonical)
            canonical_entities.append((canonical, etype))

        if not canonical_entities:
            logger.debug("graph_expand: no entities detected; passthrough")
            return query

        graph = _graph_module.get_graph_service()
        existing_query_tokens = {t.lower() for t in query.split()}
        expansion_tokens: list[str] = []

        def _lookup_aliases(name: str) -> str:
            with graph._lock:
                result = graph._conn.execute(
                    "MATCH (e:Entity) WHERE toLower(e.name) = $name"
                    " RETURN e.aliases LIMIT 1",
                    {"name": name},
                )
                if not result.has_next():
                    return ""
                row = result.get_next()
                return (row[0] or "") if row else ""

        for canonical, _etype in canonical_entities:
            for tok in canonical.split():
                tok_lc = tok.lower()
                if tok_lc and tok_lc not in existing_query_tokens:
                    expansion_tokens.append(tok)
                    existing_query_tokens.add(tok_lc)

            try:
                # I-2: Kuzu is synchronous and not thread-safe; offload to a
                # worker thread so the event loop is not blocked.
                aliases_str = await asyncio.to_thread(_lookup_aliases, canonical)
            except Exception as exc:
                logger.warning(
                    "graph_expand: kuzu lookup failed for %r, skipping: %s",
                    canonical,
                    exc,
                )
                continue

            if not aliases_str:
                continue

            alias_forms = [a.strip() for a in aliases_str.split("|") if a.strip()]
            for alias in alias_forms[:_GRAPH_EXPAND_MAX_ALIASES_PER_ENTITY]:
                for tok in alias.split():
                    tok_lc = tok.lower()
                    if tok_lc and tok_lc not in existing_query_tokens:
                        expansion_tokens.append(tok)
                        existing_query_tokens.add(tok_lc)

        if not expansion_tokens:
            return query

        capped = expansion_tokens[:_GRAPH_EXPAND_MAX_TOKENS]
        logger.info(
            "graph_expand: entities_detected=%d aliases_added=%d expanded_query_tokens=%d",
            len(canonical_entities),
            len(expansion_tokens),
            len(capped),
        )
        return f"{query} {' '.join(capped)}"
    except Exception as exc:
        logger.warning("graph_expand failed, falling back to original query: %s", exc)
        return query


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

            vector = _embedder_module.get_embedding_service().encode([query])[0]
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
        *,
        hyde: bool = False,
        rerank: bool = False,
        graph_expand: bool = True,
        strategy: RetrievalStrategy = "rrf",
    ) -> list[ScoredChunk]:
        """Full hybrid retrieval: vector(k=20) + keyword(k=20) fused via RRF + context expansion.

        Diversity re-ranking is disabled when the query is scoped to a
        single document. In that case the user is asking a focused
        question and wants the highest-scoring chunks, not section
        breadth -- the diversifier was authored for broad cross-document
        queries where variety helps. Without this skip, top-scored
        chunks from one chapter get bumped down by less-relevant chunks
        from elsewhere in the same book and HR@5 collapses (S212).

        When *hyde* is True, generates a hypothetical answer via the local
        LLM and uses ``"<query> <answer>"`` as the search query for both
        vector and BM25. This bridges question/answer phrasing divergence
        (S212): the hypothetical contains likely answer vocabulary that
        the bare question lacks. Falls back to the original query on LLM
        failure so retrieval is never harder than the no-hyde baseline.

        When *rerank* is True, the top-N RRF candidates are re-scored by a
        cross-encoder and the top-k of that re-ranking is returned. The
        cross-encoder reads (query, chunk) pairs jointly, so it catches
        answer chunks whose vocabulary diverges from the question's surface
        form -- the dominant remaining S212 failure mode. Diversification
        is skipped when reranking (the cross-encoder already optimises for
        relevance, and section breadth would dilute the rerank signal).
        Fails soft: any reranker error returns the RRF order unchanged.
        """
        scoped_single_doc = bool(document_ids) and len(document_ids or []) == 1
        # Widen the candidate pool when scoped to a single document. With a
        # cross-document corpus, 20+20 leaves enough headroom for RRF; with
        # a single book of ~500 chunks where the question phrasing diverges
        # from the answer phrasing, the right chunk can sit at rank 25-40
        # in vector or BM25 alone and never reach RRF (S212).
        # When rerank=True we always need a wide pool (50) so the cross-encoder
        # has enough headroom to recover answer chunks at deep ranks.
        if rerank:
            candidate_pool = _RERANK_CANDIDATE_POOL
        elif scoped_single_doc:
            candidate_pool = 50
        else:
            candidate_pool = 20

        # graph_expand flows only into the dense vector search. Embeddings
        # reward semantic similarity, so appending canonical entity tokens
        # helps match chunks whose surface form differs from the question.
        # SQLite FTS5 MATCH uses AND semantics across terms, so appending
        # tokens that may be absent from the corpus collapses BM25 recall to
        # zero (S225 iter 8) -- keep the keyword side on the unexpanded query.
        # HyDE, by contrast, augments with a full hypothetical answer that is
        # designed to share vocabulary with the source text, so it flows into
        # both vector and keyword (preserving the S212 iter 4 behavior).
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
            merge_k = candidate_pool if rerank else k
            diversify = (not rerank) and (not scoped_single_doc)
            results = self.rrf_merge(
                vector_results,
                keyword_results,
                k=merge_k,
                diversify=diversify,
            )
            if rerank:
                # Use the original query (not the HyDE-augmented one) for the
                # cross-encoder. Iteration 6 verified that passing the augmented
                # query regresses Time Machine HR@5 (0.50 -> 0.43): the LLM
                # hypothetical introduces vocabulary that does not appear in the
                # source text, and the cross-encoder rewards chunks containing
                # that hallucinated vocabulary over the answer chunks. The
                # original query is the user's authoritative intent. (S212)
                results = await asyncio.to_thread(_rerank_candidates, query, results, k)
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
    ) -> tuple[list[ScoredChunk], list[str]]:
        """Hybrid retrieval returning chunks and matched image_ids.

        Runs the standard retrieve() pipeline and in parallel searches image
        embeddings and image FTS5 index for visually matching content.
        Returns (chunks, deduplicated_image_ids).
        """
        try:

            chunks = await self.retrieve(query, document_ids, k)
            query_vector = _embedder_module.get_embedding_service().encode([query])[0]
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
