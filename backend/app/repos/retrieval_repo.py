"""The reads the hybrid retriever runs against SQLite: FTS5 matches and chunk lookups."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


class RetrievalRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fts_chunks(
        self, fts_query: str, document_ids: Sequence[str] | None, k: int
    ) -> list[Row[Any]]:
        """(chunk_id, document_id, text, score) rows in BM25 order; scores are negative."""
        params: dict[str, object] = {"query": fts_query, "k": k}
        if document_ids:
            sql = text(
                "SELECT chunk_id, document_id, text, bm25(chunks_fts) AS score "
                "FROM chunks_fts "
                "WHERE chunks_fts MATCH :query AND document_id IN :doc_ids "
                "ORDER BY score LIMIT :k"
            ).bindparams(bindparam("doc_ids", expanding=True))
            params["doc_ids"] = list(document_ids)
        else:
            sql = text(
                "SELECT chunk_id, document_id, text, bm25(chunks_fts) AS score "
                "FROM chunks_fts "
                "WHERE chunks_fts MATCH :query "
                "ORDER BY score LIMIT :k"
            )
        result = await self.session.execute(sql, params)
        return list(result.fetchall())

    async def speakers_and_indexes(
        self, chunk_ids: Sequence[str]
    ) -> dict[str, tuple[str | None, int]]:
        result = await self.session.execute(
            text("SELECT id, speaker, chunk_index FROM chunks WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": list(chunk_ids)},
        )
        return {row[0]: (row[1] or None, row[2] or 0) for row in result.fetchall()}

    async def entry_dates(self, chunk_ids: Sequence[str]) -> list[Row[Any]]:
        """(id, entry_date) rows; SQLite may hand the date back as an ISO string."""
        result = await self.session.execute(
            text("SELECT id, entry_date FROM chunks WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": list(chunk_ids)},
        )
        return list(result.fetchall())

    async def image_fts_ids(
        self, fts_query: str, document_ids: Sequence[str] | None, k: int
    ) -> list[str]:
        params: dict[str, object] = {"query": fts_query, "k": k}
        if document_ids:
            sql = text(
                "SELECT image_id FROM images_fts "
                "WHERE images_fts MATCH :query AND document_id IN :doc_ids "
                "LIMIT :k"
            ).bindparams(bindparam("doc_ids", expanding=True))
            params["doc_ids"] = list(document_ids)
        else:
            sql = text("SELECT image_id FROM images_fts WHERE images_fts MATCH :query LIMIT :k")
        result = await self.session.execute(sql, params)
        return [row[0] for row in result.fetchall() if row[0]]

    async def chunk_window(self, document_id: str, start: int, end: int) -> list[Row[Any]]:
        """(id, chunk_index, text, page_number, speaker) for chunk_index in [start, end]."""
        result = await self.session.execute(
            text(
                "SELECT id, chunk_index, text, page_number, speaker FROM chunks "
                "WHERE document_id = :doc_id "
                "AND chunk_index >= :start_idx AND chunk_index <= :end_idx "
                "ORDER BY chunk_index ASC"
            ),
            {"doc_id": document_id, "start_idx": start, "end_idx": end},
        )
        return list(result.fetchall())
