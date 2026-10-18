"""Cascading deletion service for a single document.

Owns the SQLite cascade (graph tables included), LanceDB vector cleanup, and
filesystem asset cleanup that `DELETE /documents/{id}` and
`POST /documents/bulk-delete` both need.

Caller (the router) is responsible for cancelling any in-flight ingestion
task before invoking, because the workflow writes to chunks / sections /
embeddings as it progresses; deleting mid-stage would either hit SQLite
locks or leave orphan rows in tables we just emptied.

Service vs repo: this is *not* a `DocumentRepo` method because the cascade
fans out to LanceDB and the filesystem on top of SQLite. The repo layer is
single-system; cross-system orchestration is a service responsibility.
"""

from __future__ import annotations

import logging
import shutil

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AnnotationModel,
    ChapterCardRunModel,
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
    GraphConceptDocumentModel,
    GraphDiagramDepictionModel,
    GraphDiagramEdgeModel,
    GraphDiagramNodeModel,
    GraphEntityEdgeModel,
    GraphEntityModel,
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
from app.repos.collection_repo import CollectionRepo
from app.repos.document_cascade_repo import DocumentCascadeRepo
from app.repos.flashcard_repo import FlashcardRepo
from app.repos.note_repo import NoteRepo

# indirect: get_lancedb_service is patched in tests
from app.services import vector_store as _vector_store_module
from app.services.documents_service import delete_raw_file
from app.storage import library_root

logger = logging.getLogger(__name__)

# Child tables that have a `document_id` column on the model. Ordered child -> parent
# so dependent rows go before their referents (matters when foreign-key constraints
# are enabled; harmless otherwise).
_DOCUMENT_ID_CHILD_TABLES: tuple[type, ...] = (
    ChapterCardRunModel,
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
    QAHistoryModel,
    ReadingProgressModel,
    AnnotationModel,
    LearningGoalModel,
    ClipModel,
    ChatSuggestionHistoryModel,
    DocumentTagIndexModel,
    DocumentTagProvenanceModel,
    GraphConceptDocumentModel,
    GraphDiagramDepictionModel,
    GraphDiagramEdgeModel,
    GraphDiagramNodeModel,
    GraphEntityEdgeModel,
    GraphEntityModel,
)

# Deleted by the explicit statements in `delete_sqlite_cascade` rather than by the
# loop above: their condition is not a plain `document_id ==`.
_SPECIAL_CASE_TABLES: tuple[type, ...] = (
    ReadingPositionModel,
    StudySessionModel,
    CollectionMemberModel,
    NoteModel,
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


async def _retire_auto_collection(session: AsyncSession, document_id: str) -> None:
    """Drop a deleted document's auto-collection, or keep it as a plain one if it holds notes."""
    repo = CollectionRepo(session)
    col = await repo.find_by_auto_document_id(document_id)
    if col is None:
        return
    if await repo.count_members(col.id) or await repo.child_ids(col.id):
        col.auto_document_id = None
    else:
        await session.delete(col)


async def _release_notes(session: AsyncSession, document_id: str, *, delete_notes: bool) -> None:
    """Detach the document's notes, or delete them with their index and memberships."""
    from app.services.notes_service import fts_delete, fts_update, sync_tag_index

    repo = NoteRepo(session)
    notes = await repo.contents_for_document(document_id)
    if not delete_notes:
        for note_id, content in notes:
            await fts_update(note_id, content, None, session)
        await repo.detach_from_document(document_id)
        return
    for note_id, _ in notes:
        await fts_delete(note_id, session)
        await sync_tag_index(note_id, [], session)
    await repo.delete_for_document(document_id, [note_id for note_id, _ in notes])


class DocumentDeletionService:
    """Orchestrates the multi-system cascade for deleting a single document."""

    async def delete_sqlite_cascade(
        self, session: AsyncSession, doc: DocumentModel, *, delete_notes: bool = False
    ) -> None:
        """Delete the document row + every child row keyed by document_id.

        The document's notes are the user's writing, so by default they survive
        as standalone notes; `delete_notes` removes them with it.

        Caller owns the session (so this can run inside the existing transaction
        used by bulk-delete) and is responsible for `await session.commit()`.
        """
        document_id = doc.id
        cascade = DocumentCascadeRepo(session)

        # Drop document_tag_index rows + decrement canonical_tags counts. Local
        # import keeps notes_service from importing the deletion service.
        from app.services.notes_service import sync_document_tag_index

        await sync_document_tag_index(document_id, [], session)

        await cascade.delete_fts_rows(document_id)

        # flashcards_fts carries no document_id for the two deletes above to match,
        # and an FTS5 UNINDEXED column cannot be filtered on directly (I-4) -- so the
        # card ids have to be read first. Skipping this is why 228 rows in that index
        # pointed at cards that no longer existed: flashcard search matches the index,
        # so a deleted document's cards kept turning up in results.
        for card_id in await FlashcardRepo(session).list_ids_for_document(document_id):
            await FlashcardRepo(session).delete_fts(card_id)

        await cascade.delete_keyed_rows(document_id, _DOCUMENT_ID_CHILD_TABLES)
        await _release_notes(session, document_id, delete_notes=delete_notes)

        # ReadingPositionModel and StudySessionModel are separated because their
        # FK relationship to DocumentModel uses a different column name in some
        # historical migrations; safer to spell them out.
        await cascade.delete_keyed_rows(document_id, (ReadingPositionModel, StudySessionModel))
        # Chat sessions hold their scope as a JSON array, so no document_id column
        # exists for the loop above to match. Leaving the id behind is not cosmetic:
        # a chat scoped to a deleted document filters every question down to a row
        # that no longer exists and answers nothing, which is what happened for nine
        # days before it was found. A session left with no documents becomes
        # library-wide rather than scoped to nothing.
        for chat in await cascade.chats_mentioning(document_id):
            remaining = [d for d in (chat.document_ids or []) if d != document_id]
            if remaining == list(chat.document_ids or []):
                continue
            chat.document_ids = remaining
            if not remaining:
                chat.scope = "all"

        # Keyed on (member_id, member_type), not document_id, so the loop above
        # misses it; orphaned rows inflate every collection's badge.
        await cascade.delete_collection_membership(document_id)
        await _retire_auto_collection(session, document_id)
        # The library summary describes every document, so a delete drops it (#140).
        # The caller schedules the regeneration once the transaction commits.
        await cascade.delete_library_summary()
        await session.delete(doc)

    async def delete_derived_for_reparse(
        self, session: AsyncSession, document_id: str
    ) -> dict[str, int]:
        """Clear only what the parser produces, so ingestion can rebuild it.

        Re-parsing is not deletion: notes, annotations, clips, flashcards,
        collection membership and the learner record all survive. Sections and
        chunks are rebuilt with fresh ids, which is the cost the caller has to
        state up front -- anything anchored to a `section_id` or `chunk_id` from
        the old parse no longer resolves.

        Nothing here runs unless the caller has already established consent; the
        endpoint reports the counts below before it is invoked a second time.
        """
        cascade = DocumentCascadeRepo(session)
        counts = await cascade.delete_keyed_rows(
            document_id,
            (
                ChunkModel,
                SectionSummaryModel,
                SectionModel,
                SummaryModel,
                ImageModel,
                LearningObjectiveModel,
                CodeSnippetModel,
                WebReferenceModel,
            ),
        )
        await cascade.delete_fts_rows(document_id)
        return counts

    async def count_anchored_rows(self, session: AsyncSession, document_id: str) -> dict[str, int]:
        """What a re-parse would strand, so the user can decide before it runs.

        These rows are kept, but they point at section/chunk ids that the rebuild
        replaces. Reporting zero when the answer is "your 40 highlights" would be
        the silent kind of damage this codebase exists to avoid.
        """
        cascade = DocumentCascadeRepo(session)
        return {
            label: await cascade.count_keyed_rows(document_id, model)
            for label, model in (
                ("flashcards", FlashcardModel),
                ("annotations", AnnotationModel),
                ("clips", ClipModel),
            )
        }

    def delete_lancedb_vectors(self, document_id: str, *, delete_notes: bool = False) -> None:
        """Drop chunk + image vectors and release note vectors. Non-fatal: failures are logged."""
        try:
            _vector_store_module.get_lancedb_service().delete_document(document_id)
        except Exception:
            logger.warning("Failed to delete LanceDB vectors for document %s", document_id)
        try:
            _vector_store_module.get_lancedb_service().release_document_notes(
                document_id, delete_notes=delete_notes
            )
        except Exception:
            logger.warning("Failed to release note vectors for document %s", document_id)

    def delete_filesystem_assets(self, document_id: str) -> None:
        """Drop extracted images dir + raw file. Non-fatal."""
        settings = get_settings()
        images_dir = library_root(settings) / "images" / document_id
        if images_dir.exists():
            shutil.rmtree(images_dir, ignore_errors=True)
        delete_raw_file(document_id)


def get_document_deletion_service() -> DocumentDeletionService:
    return DocumentDeletionService()
