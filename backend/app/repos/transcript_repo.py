"""A media document's transcript inputs and the rows a correction rewrites."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import ChunkModel, DocumentModel, SectionModel
from app.repos._helpers import get_or_404
from app.repos.document_repo import index_chunks_fts
from app.repos.settings_repo import SettingsRepo

PERSONAL_VOCABULARY_KEY = "transcript_vocabulary"


async def fetch_transcript_inputs(document_id: str) -> tuple[list[str], list[dict], list[str]]:
    """(document vocabulary, recorded corrections, personal vocabulary). Own session."""
    async with get_session_factory()() as session:
        row = (
            await session.execute(
                select(
                    DocumentModel.transcript_vocabulary, DocumentModel.transcript_corrections
                ).where(DocumentModel.id == document_id)
            )
        ).one_or_none()
        personal = await TranscriptRepo(session).personal_vocabulary()
    vocabulary, corrections = row if row is not None else (None, None)
    return list(vocabulary or []), list(corrections or []), personal


async def save_transcript_corrections(document_id: str, corrections: list[dict]) -> None:
    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel)
            .where(DocumentModel.id == document_id)
            .values(transcript_corrections=corrections or None)
        )
        await session.commit()


class TranscriptRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def document(self, document_id: str) -> DocumentModel:
        return await get_or_404(self.session, DocumentModel, document_id, name="Document")

    async def chunks(self, document_id: str) -> list[ChunkModel]:
        rows = await self.session.execute(
            select(ChunkModel)
            .where(ChunkModel.document_id == document_id)
            .order_by(ChunkModel.chunk_index)
        )
        return list(rows.scalars())

    async def sections(self, document_id: str) -> list[SectionModel]:
        rows = await self.session.execute(
            select(SectionModel).where(SectionModel.document_id == document_id)
        )
        return list(rows.scalars())

    async def reindex_keywords(self, document_id: str) -> None:
        await index_chunks_fts(self.session, document_id)

    async def personal_vocabulary(self) -> list[str]:
        value = await SettingsRepo(self.session).get(PERSONAL_VOCABULARY_KEY)
        return [t for t in value if isinstance(t, str)] if isinstance(value, list) else []

    async def set_personal_vocabulary(self, terms: list[str]) -> None:
        await SettingsRepo(self.session).put(PERSONAL_VOCABULARY_KEY, terms)

    async def commit(self) -> None:
        await self.session.commit()
