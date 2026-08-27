"""Note search service: FTS5 keyword + BAAI/bge-small-en-v1.5 semantic + RRF fusion."""

import json
import logging

from sqlalchemy import select, text

from app.database import get_session_factory
from app.models import NoteModel
from app.services.fts_query import sanitize_fts_query as _sanitize_fts_query
from app.types import NoteSearchResult

logger = logging.getLogger(__name__)

RRF_K = 60
_NOTE_SEARCH_K = 20  # per-arm candidate count before RRF

# Minimum cosine similarity for the semantic arm to return a note at all.
# `table.search(...).limit(k)` is a nearest-neighbour query with no floor, so in
# a library smaller than k it returns EVERY note however unrelated -- which is
# why a "search for the old term, expect a miss" test could never pass without
# one. Measured with BAAI/bge-small-en-v1.5, the two cases that bracket it:
#
#   0.5004  "photosynthesis chloroplast" vs a note reading "baroque fugue
#           counterpoint harpsichord sonata" -- unrelated, must be dropped
#   0.7516  "feline that disappears" vs "Cheshire Cat can vanish leaving only
#           its grin" -- a hit with ZERO words in common, which is the entire
#           reason this arm exists and must be kept
#
# Every keep-case measured lands in 0.7516-0.9140 and every drop-case in
# 0.4186-0.5004, so 0.62 sits in a 0.25-wide gap with ~0.12 either side.
# Do NOT replace this with a literal-term check on the content: that was the
# previous behaviour and it dropped the 0.7516 case, which is the one the arm
# is for.
NOTE_SEMANTIC_MIN_SIMILARITY = 0.62


def _rrf_merge(
    fts_results: list[NoteSearchResult],
    vector_results: list[NoteSearchResult],
    k: int,
) -> list[NoteSearchResult]:
    """Pure RRF fusion of FTS and vector result lists.

    Score = sum(1 / (RRF_K + rank)) across lists the note appears in.
    Source field reflects whether the note appeared in one or both arms.
    """
    scores: dict[str, float] = {}
    meta: dict[str, NoteSearchResult] = {}
    sources: dict[str, set[str]] = {}

    for rank, result in enumerate(fts_results, start=1):
        scores[result.note_id] = scores.get(result.note_id, 0.0) + 1.0 / (RRF_K + rank)
        meta.setdefault(result.note_id, result)
        sources.setdefault(result.note_id, set()).add("fts")

    for rank, result in enumerate(vector_results, start=1):
        scores[result.note_id] = scores.get(result.note_id, 0.0) + 1.0 / (RRF_K + rank)
        meta.setdefault(result.note_id, result)
        sources.setdefault(result.note_id, set()).add("vector")

    sorted_ids = sorted(scores, key=lambda nid: scores[nid], reverse=True)
    out: list[NoteSearchResult] = []
    for nid in sorted_ids[:k]:
        r = meta[nid]
        src_set = sources[nid]
        source = "both" if len(src_set) > 1 else next(iter(src_set))
        out.append(
            NoteSearchResult(
                note_id=r.note_id,
                content=r.content,
                tags=r.tags,
                group_name=r.group_name,
                document_id=r.document_id,
                score=scores[nid],
                source=source,  # type: ignore[arg-type]
            )
        )
    return out


class NoteSearchService:
    async def fts_search(self, query: str, k: int = _NOTE_SEARCH_K) -> list[NoteSearchResult]:
        """BM25 keyword search over notes_fts."""
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            return []

        sql = text(
            "SELECT nf.note_id, nf.content, nf.document_id, bm25(notes_fts) AS score, "
            "       n.tags, n.group_name "
            "FROM notes_fts AS nf "
            "JOIN notes AS n ON nf.note_id = n.id "
            "WHERE notes_fts MATCH :query "
            "ORDER BY score LIMIT :k"
        )
        async with get_session_factory()() as session:
            rows = (await session.execute(sql, {"query": safe_query, "k": k})).fetchall()
            if not rows:
                return []

        results = []
        for row in rows:
            note_id, content, document_id, score, raw_tags, group_name = row
            try:
                tags = json.loads(raw_tags) if isinstance(raw_tags, str) else (raw_tags or [])
            except Exception:
                tags = []
            results.append(
                NoteSearchResult(
                    note_id=note_id,
                    content=content,
                    tags=tags,
                    group_name=group_name,
                    document_id=document_id or None,
                    score=float(score),
                    source="fts",
                )
            )
        return results

    def semantic_search(self, query: str, k: int = _NOTE_SEARCH_K) -> list[NoteSearchResult]:
        """Cosine similarity search over note_vectors using BAAI/bge-small-en-v1.5."""
        try:
            from app.services.embedder import get_embedding_service  # noqa: PLC0415
            from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

            svc = get_lancedb_service()
            table = svc._get_or_create_note_table()
            if table.count_rows() == 0:
                return []
            vector = get_embedding_service().encode([query])[0]
            rows = table.search(vector).metric("cosine").limit(k).to_list()
            # LanceDB's cosine `_distance` is 1 - cosine_similarity, verified
            # against a manual dot product, so this score IS the similarity.
            results = []
            for row in rows:
                similarity = 1.0 - float(row.get("_distance", 0.0))
                if similarity < NOTE_SEMANTIC_MIN_SIMILARITY:
                    continue
                results.append(
                    NoteSearchResult(
                        note_id=row["note_id"],
                        content=row["content"],
                        tags=[],
                        group_name=None,
                        document_id=row["document_id"] or None,
                        score=similarity,
                        source="vector",
                    )
                )
            return results
        except Exception as exc:
            logger.warning("semantic_search failed: %s", exc)
            return []

    async def _drop_deleted(self, results: list[NoteSearchResult]) -> list[NoteSearchResult]:
        """Keep only results whose note still exists, with the note's own fields.

        The FTS arm gets this free -- its SQL joins notes_fts against notes, so a
        stale index row can never surface. The vector arm reads LanceDB directly
        and had no equivalent, so anything left in that table was returned as a
        live note: `delete_note_vector` swallows its exceptions (deliberately --
        a vector-store hiccup must not fail a user's delete), and a swallowed
        failure therefore kept serving a note the user had deleted.

        This is the join the vector arm was missing. A ghost row is now invisible
        whatever put it there, which is also what makes the swallow above safe.

        Hydrating rather than only filtering, because the vector table's copy of
        content goes stale on an edit and it carries no tags or group at all --
        so a note found by the semantic arm used to come back with tags=[].
        """
        if not results:
            return []
        ids = [r.note_id for r in results]
        # ORM `in_`, not a built IN list: the placeholders would be ours rather
        # than the caller's, but a string-built WHERE is the shape this repo is
        # trying to be rid of and ruff S608 says so.
        stmt = select(
            NoteModel.id,
            NoteModel.content,
            NoteModel.tags,
            NoteModel.group_name,
            NoteModel.document_id,
        ).where(NoteModel.id.in_(ids))
        async with get_session_factory()() as session:
            rows = (await session.execute(stmt)).all()

        live = {row[0]: row for row in rows}
        out: list[NoteSearchResult] = []
        for r in results:
            row = live.get(r.note_id)
            if row is None:
                logger.debug("note search: dropping deleted note_id=%s", r.note_id)
                continue
            _, content, raw_tags, group_name, document_id = row
            try:
                tags = json.loads(raw_tags) if isinstance(raw_tags, str) else (raw_tags or [])
            except Exception:
                tags = []
            out.append(
                NoteSearchResult(
                    note_id=r.note_id,
                    content=content,
                    tags=tags,
                    group_name=group_name,
                    document_id=document_id or None,
                    score=r.score,
                    source=r.source,
                )
            )
        return out

    async def search(self, query: str, k: int = 10) -> list[NoteSearchResult]:
        """Hybrid search: FTS5 + semantic, fused via RRF."""
        # Run sequentially to avoid potential race conditions or DB isolation
        # issues in tests/sqlite. Sequential is fine given our low concurrency.
        fts_results = await self.fts_search(query, k=_NOTE_SEARCH_K)
        vector_results = self.semantic_search(query, _NOTE_SEARCH_K)

        # Before the merge, so a deleted note cannot take a slot in the top k.
        # The FTS arm needs no such pass -- it joins notes in SQL already.
        vector_results = await self._drop_deleted(vector_results)

        merged = _rrf_merge(fts_results, vector_results, k=k)

        logger.debug(
            "note search q=%r fts=%d vector=%d merged=%d",
            query[:50],
            len(fts_results),
            len(vector_results),
            len(merged),
        )
        return merged


_note_search_service: NoteSearchService | None = None


def get_note_search_service() -> NoteSearchService:
    global _note_search_service
    if _note_search_service is None:
        _note_search_service = NoteSearchService()
    return _note_search_service
