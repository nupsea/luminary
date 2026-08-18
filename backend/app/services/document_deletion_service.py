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
service responsibility.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AnnotationModel,
    ChatSessionModel,
    ChatSuggestionHistoryModel,
    ChunkModel,
    ClipModel,
    CodeSnippetModel,
    CollectionMemberModel,
    DocumentModel,
    DocumentTagIndexModel,
    DocumentTagProvenanceModel,
    EnrichmentJobModel,
    FeynmanSessionModel,
    FlashcardModel,
    ImageModel,
    LearningGoalModel,
    LearningObjectiveModel,
    MisconceptionModel,
    NoteModel,
    NoteSourceModel,
    PomodoroSessionModel,
    PredictionEventModel,
    QAHistoryModel,
    ReadingPositionModel,
    ReadingProgressModel,
    SectionModel,
    SectionSummaryModel,
    StudySessionModel,
    SummaryModel,
    WebReferenceModel,
)
from app.services import graph as _graph_module  # indirect: get_graph_service is patched

# indirect: get_lancedb_service is patched in tests
from app.services import vector_store as _vector_store_module
from app.services.documents_service import delete_raw_file
from app.services.flashcard_search import _delete_flashcard_fts

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
    SectionSummaryModel,
    SectionModel,
    SummaryModel,
    FlashcardModel,
    MisconceptionModel,
    NoteSourceModel,
    NoteModel,
    QAHistoryModel,
    ReadingProgressModel,
    AnnotationModel,
    LearningGoalModel,
    ClipModel,
    ChatSuggestionHistoryModel,
    DocumentTagIndexModel,
    DocumentTagProvenanceModel,
)

# Deleted by the explicit statements in `delete_sqlite_cascade` rather than by the
# loop above: their condition is not a plain `document_id ==`.
_SPECIAL_CASE_TABLES: tuple[type, ...] = (
    ReadingPositionModel,
    StudySessionModel,
    CollectionMemberModel,
)

# Carries a document_id and is deliberately kept. The learner record outlives the
# document it was earned against -- deleting a book must not erase the evidence
# that someone studied it -- so these rows keep a document_id that may no longer
# resolve, and every reader of them has to tolerate that.
_LEARNER_RECORD_TABLES: tuple[type, ...] = (
    FeynmanSessionModel,
    PomodoroSessionModel,
    PredictionEventModel,
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

        # Drop document_tag_index rows + decrement canonical_tags counts. Local
        # import keeps notes_service from importing the deletion service.
        from app.services.notes_service import sync_document_tag_index

        await sync_document_tag_index(document_id, [], session)

        # FTS5 virtual tables -- use raw DELETE because they don't have an ORM model.
        await session.execute(
            text("DELETE FROM chunks_fts WHERE document_id = :doc_id"),
            {"doc_id": document_id},
        )
        await session.execute(
            text("DELETE FROM images_fts WHERE document_id = :doc_id"),
            {"doc_id": document_id},
        )

        # flashcards_fts carries no document_id for the two deletes above to match,
        # and an FTS5 UNINDEXED column cannot be filtered on directly (I-4) -- so the
        # card ids have to be read first. Skipping this is why 228 rows in that index
        # pointed at cards that no longer existed: flashcard search matches the index,
        # so a deleted document's cards kept turning up in results.
        card_ids = (
            (
                await session.execute(
                    select(FlashcardModel.id).where(FlashcardModel.document_id == document_id)
                )
            )
            .scalars()
            .all()
        )
        for card_id in card_ids:
            await _delete_flashcard_fts(card_id, session)

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
        # Chat sessions hold their scope as a JSON array, so no document_id column
        # exists for the loop above to match. Leaving the id behind is not cosmetic:
        # a chat scoped to a deleted document filters every question down to a row
        # that no longer exists and answers nothing, which is what happened for nine
        # days before it was found. A session left with no documents becomes
        # library-wide rather than scoped to nothing.
        sessions = (
            await session.execute(
                select(ChatSessionModel).where(
                    ChatSessionModel.document_ids.like(f"%{document_id}%")
                )
            )
        ).scalars()
        for chat in sessions:
            remaining = [d for d in (chat.document_ids or []) if d != document_id]
            if remaining == list(chat.document_ids or []):
                continue
            chat.document_ids = remaining
            if not remaining:
                chat.scope = "all"

        # Keyed on (member_id, member_type), not document_id, so the loop above
        # misses it; orphaned rows inflate every collection's badge.
        await session.execute(
            delete(CollectionMemberModel).where(
                CollectionMemberModel.member_id == document_id,
                CollectionMemberModel.member_type == "document",
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
