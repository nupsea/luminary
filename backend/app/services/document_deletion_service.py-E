"""Cascading deletion service for a single document.

Owns the 18-table SQLite cascade, LanceDB vector cleanup, Kuzu graph node
removal, and filesystem asset cleanup that `DELETE /documents/{id}` and
`POST /documents/bulk-delete` both need.

Caller (the router) is responsible for cancelling any in-flight ingestion
task before invoking, because the workflow writes to chunks / sections /
embeddings as it progresses; deleting mid-stage would either hit SQLite
locks or leave orphan rows in tables we just emptied.

Service vs repo: this is *not* a `DocumentRepo` method because the cascade
fans out to three external systems (LanceDB, Kuzu, filesystem) on top of
SQLite. The repo layer is single-system; cross-system orchestration is a
service responsibility per audit #9's design principle.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AnnotationModel,
    ChunkModel,
    ClipModel,
    CodeSnippetModel,
    DocumentModel,
    EnrichmentJobModel,
    FlashcardModel,
    ImageModel,
    LearningGoalModel,
    LearningObjectiveModel,
    MisconceptionModel,
    NoteModel,
    QAHistoryModel,
    ReadingPositionModel,
    ReadingProgressModel,
    SectionModel,
    StudySessionModel,
    SummaryModel,
    WebReferenceModel,
)
from app.services import graph as _graph_module  # indirect: get_graph_service is patched

# indirect: get_lancedb_service is patched in tests
from app.services import vector_store as _vector_store_module
from app.services.documents_service import delete_raw_file

logger = logging.getLogger(__name__)

# Child tables that have a `document_id` column on the model. Ordered child -> parent
# so dependent rows go before their referents (matters when foreign-key constraints
# are enabled; harmless otherwise).
_DOCUMENT_ID_CHILD_TABLES: tuple[type, ...] = (
    EnrichmentJobModel,
    ImageModel,
    LearningObjectiveModel,
    CodeSnippetModel,
    WebReferenceModel,
    ChunkModel,
    SectionModel,
    SummaryModel,
    FlashcardModel,
    MisconceptionModel,
    NoteModel,
    QAHistoryModel,
    ReadingProgressModel,
    AnnotationModel,
    LearningGoalModel,
    ClipModel,
)


class DocumentDeletionService:
    """Orchestrates the multi-system cascade for deleting a single document."""

    async def delete_sqlite_cascade(
        self, session: AsyncSession, doc: DocumentModel
    ) -> None:
        """Delete the document row + every child row keyed by document_id.

        Caller owns the session (so this can run inside the existing transaction
        used by bulk-delete) and is responsible for `await session.commit()`.
        """
        document_id = doc.id

        # FTS5 virtual tables -- use raw DELETE because they don't have an ORM model.
        await session.execute(
            text("DELETE FROM chunks_fts WHERE document_id = :doc_id"),
            {"doc_id": document_id},
        )
        await session.execute(
            text("DELETE FROM images_fts WHERE document_id = :doc_id"),
            {"doc_id": document_id},
        )

        for model in _DOCUMENT_ID_CHILD_TABLES:
            await session.execute(
                delete(model).where(model.document_id == document_id)  # type: ignore[attr-defined]
            )

        # ReadingPositionModel and StudySessionModel are separated because their
        # FK relationship to DocumentModel uses a different column name in some
        # historical migrations; safer to spell them out.
        await session.execute(
            delete(ReadingPositionModel).where(
                ReadingPositionModel.document_id == document_id
            )
        )
        await session.execute(
            delete(StudySessionModel).where(
                StudySessionModel.document_id == document_id
            )
        )
        await session.delete(doc)

    def delete_lancedb_vectors(self, document_id: str) -> None:
        """Drop chunk + image vectors. Non-fatal: failures are logged."""
        try:
            _vector_store_module.get_lancedb_service().delete_document(document_id)
        except Exception:
            logger.warning("Failed to delete LanceDB vectors for document %s", document_id)

    def delete_kuzu_nodes(self, document_id: str) -> None:
        """Drop Document node + edges. Non-fatal: failures are logged."""
        try:
            _graph_module.get_graph_service().delete_document(document_id)
        except Exception:
            logger.warning("Failed to delete Kuzu graph nodes for document %s", document_id)

    def delete_filesystem_assets(self, document_id: str) -> None:
        """Drop extracted images dir + raw file. Non-fatal."""
        settings = get_settings()
        images_dir = Path(settings.DATA_DIR).expanduser() / "images" / document_id
        if images_dir.exists():
            shutil.rmtree(images_dir, ignore_errors=True)
        delete_raw_file(document_id)


def get_document_deletion_service() -> DocumentDeletionService:
    return DocumentDeletionService()
