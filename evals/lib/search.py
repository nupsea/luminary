"""Reading a /search response in the retriever's order."""

from __future__ import annotations


def ranked_matches(body: dict, document_id: str | None = None) -> list[dict]:
    """Every match in the response, ordered by `global_rank`, tagged with `_doc_id`.

    Never sort by `relevance_score`: FTS BM25 is more negative for more relevant,
    and rrf diversification deviates from score order on purpose. A match without
    `global_rank` keeps its grouped position (stable sort, inf default).
    """
    matches: list[dict] = []
    for group in body.get("results", []):
        doc_id = group.get("document_id")
        if document_id and doc_id != document_id:
            continue
        matches.extend({**m, "_doc_id": doc_id} for m in group.get("matches", []))
    matches.sort(key=lambda m: m.get("global_rank", float("inf")))
    return matches
