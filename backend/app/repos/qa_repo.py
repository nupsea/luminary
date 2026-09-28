"""Reads and writes behind a streamed answer: library counts, titles, history rows."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database import get_session_factory
from app.models import DocumentModel, QAHistoryModel


async def library_counts() -> tuple[int, int]:
    """(documents, documents not yet complete) across the whole library."""
    async with get_session_factory()() as session:
        total = (
            await session.execute(select(func.count()).select_from(DocumentModel))
        ).scalar_one()
        indexing = (
            await session.execute(
                select(func.count())
                .select_from(DocumentModel)
                .where(DocumentModel.stage != "complete")
            )
        ).scalar_one()
    return total, indexing


async def fetch_titles(document_ids: list[str]) -> dict[str, str]:
    if not document_ids:
        return {}
    async with get_session_factory()() as session:
        result = await session.execute(
            select(DocumentModel.id, DocumentModel.title).where(DocumentModel.id.in_(document_ids))
        )
        return {row.id: row.title for row in result}


async def insert_qa_history(
    question: str,
    answer: str | None,
    citations: list[dict],
    confidence: str,
    document_id: str | None,
    scope: str,
    model_used: str,
) -> str:
    qa_id = str(uuid.uuid4())
    async with get_session_factory()() as session:
        session.add(
            QAHistoryModel(
                id=qa_id,
                document_id=document_id,
                scope=scope,
                question=question,
                answer=answer or "",
                citations=citations,
                confidence=confidence,
                model_used=model_used,
            )
        )
        await session.commit()
    return qa_id
