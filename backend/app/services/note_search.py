"""Note search service: FTS5 keyword + BAAI/bge-m3 semantic + RRF fusion."""

import asyncio
import json
import logging
import re

from sqlalchemy import text

from app.database import get_session_factory
from app.types import NoteSearchResult

logger = logging.getLogger(__name__)

RRF_K = 60
_NOTE_SEARCH_K = 20  # per-arm candidate count before RRF


def _sanitize_fts_query(query: str) -> str:
    """Strip FTS5 operator chars from a natural-language query string."""
    cleaned = re.sub(r"[^\w\s]", " ", query)
    cleaned = re.sub(r"\b(AND|OR|NOT)\b", " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


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
            "SELECT nf.note_id, nf.content, nf.document_id, bm25(notes_fts) AS score "
            "FROM notes_fts AS nf "
            "WHERE notes_fts MATCH :query "
            "ORDER BY score LIMIT :k"
        )
        async with get_session_factory()() as session:
            rows = (await session.execute(sql, {"query": safe_query, "k": k})).fetchall()
            if not rows:
                return []
            note_ids = [r[0] for r in rows]
            # Use JSON-based parameterised lookup to avoid f-string SQL interpolation.
            # json_each(:ids) expands the JSON array into rows; SQLite parameterises the
            # entire array as a single bind value, eliminating any injection surface.
            meta_rows = (
                await session.execute(
                    text(
                        "SELECT n.id, n.tags, n.group_name "
                        "FROM notes AS n "
                        "JOIN json_each(:ids) AS j ON n.id = j.value"
                    ),
                    {"ids": json.dumps(note_ids)},
                )
            ).fetchall()
        meta_map = {r[0]: (r[1], r[2]) for r in meta_rows}

        results = []
        for row in rows:
            note_id, content, document_id, score = row
            raw_tags, group_name = meta_map.get(note_id, ("[]", None))
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
        """Cosine similarity search over note_vectors using BAAI/bge-m3."""
        try:
            from app.services.embedder import get_embedding_service  # noqa: PLC0415
            from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

            svc = get_lancedb_service()
            table = svc._get_note_table()
            if table.count_rows() == 0:
                return []
            vector = get_embedding_service().encode([query])[0]
            rows = table.search(vector).metric("cosine").limit(k).to_list()
            return [
                NoteSearchResult(
                    note_id=row["note_id"],
                    content=row["content"],
                    tags=[],
                    group_name=None,
                    document_id=row["document_id"] or None,
                    score=1.0 - float(row.get("_distance", 0.0)),
                    source="vector",
                )
                for row in rows
            ]
        except Exception as exc:
            logger.warning("semantic_search failed: %s", exc)
            return []

    async def search(self, query: str, k: int = 10) -> list[NoteSearchResult]:
        """Hybrid search: FTS5 + semantic, fused via RRF.

        Semantic search is CPU-bound; run in thread pool so the event loop stays free.
        """
        loop = asyncio.get_running_loop()
        fts_task = asyncio.create_task(self.fts_search(query, k=_NOTE_SEARCH_K))
        vector_results = await loop.run_in_executor(
            None, self.semantic_search, query, _NOTE_SEARCH_K
        )
        fts_results = await fts_task
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
