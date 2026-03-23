"""In-document FTS5 search service (S151).

Returns section-grouped results scoped to a single document_id.
"""
import logging
import re
from collections import defaultdict

from sqlalchemy import bindparam, text

from app.database import get_session_factory

logger = logging.getLogger(__name__)

# Strip punctuation that confuses FTS5 query parser, and remove FTS5 boolean operators
_PUNCT_RE = re.compile(r"[^\w\s]")
_OP_RE = re.compile(r"\b(AND|OR|NOT)\b", re.IGNORECASE)


def _sanitize_fts_query(query: str) -> str:
    """Remove FTS5 special tokens and punctuation that cause parse errors."""
    cleaned = _PUNCT_RE.sub(" ", query)
    cleaned = _OP_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


class DocumentSearchService:
    async def search(
        self,
        document_id: str,
        query: str,
        limit: int = 50,
    ) -> list[dict]:
        """Search chunks_fts scoped to document_id.

        Returns a list of dicts with keys:
          section_id, section_heading, match_count, snippet
        Ordered by match_count DESC, limited to `limit` results.
        Returns [] for empty or whitespace-only query.
        """
        if not query or not query.strip():
            return []

        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            return []

        # SQLite FTS5 restriction: snippet() can ONLY be used in a simple FTS query
        # with no JOINs, no CTEs, no GROUP BY. We use two queries:
        #   1. Pure FTS5 query to get chunk_id + snippet pairs
        #   2. Regular SQL to group by section, get headings
        # Then combine in Python.

        # Query 1: get matching chunk_ids and snippets via pure FTS5 (no JOIN allowed)
        fts_sql = text(
            "SELECT chunks_fts.chunk_id, "
            "       snippet(chunks_fts, 0, '<mark>', '</mark>', '...', 24) AS snippet "
            "FROM chunks_fts "
            "WHERE chunks_fts MATCH :query "
            "  AND chunks_fts.document_id = :doc_id "
            "LIMIT :inner_limit"
        )
        # Query 2: given chunk_ids, get section_id and heading
        # expandable bindparam required for IN clause in raw SQL
        section_sql = text(
            "SELECT c.id AS chunk_id, c.section_id, COALESCE(s.heading, '') AS section_heading "
            "FROM chunks c "
            "LEFT JOIN sections s ON c.section_id = s.id "
            "WHERE c.id IN :chunk_ids"
        ).bindparams(bindparam("chunk_ids", expanding=True))
        async with get_session_factory()() as session:
            fts_rows = (
                await session.execute(
                    fts_sql,
                    {"query": safe_query, "doc_id": document_id, "inner_limit": limit * 4},
                )
            ).fetchall()

            if not fts_rows:
                return []

            chunk_ids = tuple(row[0] for row in fts_rows)
            chunk_snippets: dict[str, str] = {row[0]: row[1] or "" for row in fts_rows}

            section_rows = (
                await session.execute(
                    section_sql,
                    {"chunk_ids": chunk_ids},
                )
            ).fetchall()

        # Group by section_id in Python
        section_match_counts: dict[str, int] = defaultdict(int)
        section_headings: dict[str, str] = {}
        section_best_snippet: dict[str, str] = {}

        for row in section_rows:
            cid, sid, heading = row[0], row[1] or "", row[2] or ""
            section_match_counts[sid] += 1
            section_headings[sid] = heading
            if sid not in section_best_snippet:
                section_best_snippet[sid] = chunk_snippets.get(cid, "")

        results = [
            {
                "section_id": sid,
                "section_heading": section_headings.get(sid, ""),
                "match_count": count,
                "snippet": section_best_snippet.get(sid, ""),
            }
            for sid, count in section_match_counts.items()
        ]
        results.sort(key=lambda r: r["match_count"], reverse=True)
        return results[:limit]


_document_search_service: DocumentSearchService | None = None


def get_document_search_service() -> DocumentSearchService:
    global _document_search_service
    if _document_search_service is None:
        _document_search_service = DocumentSearchService()
    return _document_search_service
