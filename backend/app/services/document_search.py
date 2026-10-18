"""In-document FTS5 search service

Returns section-grouped results scoped to a single document_id.
"""

import logging
from collections import defaultdict

from app.database import get_session_factory
from app.repos.document_repo import DocumentRepo
from app.services.fts_query import sanitize_fts_query as _sanitize_fts_query

logger = logging.getLogger(__name__)

# Strip punctuation that confuses FTS5 query parser, and remove FTS5 boolean operators


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

        async with get_session_factory()() as session:
            docs = DocumentRepo(session)
            fts_rows = await docs.chunk_snippets(document_id, safe_query, limit * 4)
            # Strict AND found nothing: try OR, so composite or parenthesised names still match.
            words = safe_query.split()
            if not fts_rows and len(words) > 1:
                fts_rows = await docs.chunk_snippets(document_id, " OR ".join(words), limit * 4)
            if not fts_rows:
                return []
            chunk_snippets = dict(fts_rows)
            section_rows = await docs.chunk_section_headings(list(chunk_snippets))

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
