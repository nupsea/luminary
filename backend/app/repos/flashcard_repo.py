"""Flashcard reads and writes, the cards' FTS5 index, and filtered search."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import case, delete, false, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    ChapterCardRunModel,
    ChunkModel,
    CollectionMemberModel,
    FlashcardModel,
    MisconceptionModel,
    NoteTagIndexModel,
    TeachbackResultModel,
)
from app.repos._helpers import get_or_404
from app.types import CARD_HELD


def collection_card_filter(collection_id: str):
    """A collection's flashcards are those sourced from its document members OR
    its note members. Shared by search and delete so both target the same set."""
    doc_members = select(CollectionMemberModel.member_id).where(
        CollectionMemberModel.collection_id == collection_id,
        CollectionMemberModel.member_type == "document",
    )
    note_members = select(CollectionMemberModel.member_id).where(
        CollectionMemberModel.collection_id == collection_id,
        CollectionMemberModel.member_type == "note",
    )
    return or_(
        FlashcardModel.document_id.in_(doc_members),
        FlashcardModel.note_id.in_(note_members),
    )


# Rows keyed to one card that become unreadable without it: a graded explanation
# of a question nobody can see, a correction note against an answer that is gone.
# Deleting a card takes them with it, matching what deleting a document already
# does to misconceptions.
_CARD_CHILD_TABLES: tuple[type, ...] = (
    MisconceptionModel,
    TeachbackResultModel,
)

# `review_events` is deliberately NOT in that list. It is the activity record --
# streaks, XP and per-day accuracy read it -- and it records what the learner did,
# not what the card says. Deleting a card must not rewrite the history of the days
# it was studied, so these rows keep a flashcard_id that no longer resolves and
# every reader of them has to tolerate that. Same rule as
# `document_deletion_service._LEARNER_RECORD_TABLES`.


class FlashcardRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- single-row reads --------------------------------------------------

    async def get_or_404(self, card_id: str) -> FlashcardModel:
        return await get_or_404(self.session, FlashcardModel, card_id, name="Flashcard")

    # -- list reads --------------------------------------------------------

    async def list_for_document(
        self,
        document_id: str,
        *,
        bloom_level_min: int | None = None,
        newest_first: bool = True,
    ) -> Sequence[FlashcardModel]:
        stmt = select(FlashcardModel).where(FlashcardModel.document_id == document_id)
        if bloom_level_min is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level >= bloom_level_min,
            )
        if newest_first:
            stmt = stmt.order_by(FlashcardModel.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_for_section(
        self,
        document_id: str,
        section_id: str,
        *,
        bloom_level_min: int | None = None,
    ) -> list[tuple[FlashcardModel, str]]:
        """Return (card, section_id) pairs joined through ChunkModel."""
        stmt = (
            select(FlashcardModel, ChunkModel.section_id)
            .join(ChunkModel, FlashcardModel.chunk_id == ChunkModel.id)
            .where(
                FlashcardModel.document_id == document_id,
                ChunkModel.section_id == section_id,
            )
        )
        if bloom_level_min is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level >= bloom_level_min,
            )
        stmt = stmt.order_by(FlashcardModel.created_at.desc())
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def find(self, card_id: str) -> FlashcardModel | None:
        return await self.session.get(FlashcardModel, card_id)

    async def questions(
        self,
        *,
        note_id: str | None = None,
        document_id: str | None = None,
        member_ids: Sequence[str] = (),
        deck: str | None = None,
    ) -> list[str]:
        """Questions of a note's cards; else of a document's and its `member_ids`' (documents
        or notes); else of a deck's."""
        if note_id is not None:
            scope = FlashcardModel.note_id == note_id
        elif document_id is not None:
            scope = or_(
                FlashcardModel.document_id == document_id,
                FlashcardModel.document_id.in_(list(member_ids)) if member_ids else false(),
                FlashcardModel.note_id.in_(list(member_ids)) if member_ids else false(),
            )
        else:
            scope = FlashcardModel.deck == deck
        result = await self.session.execute(select(FlashcardModel.question).where(scope))
        return [row[0] for row in result.all()]

    async def source_chunks_by_card(
        self, *, document_id: str | None = None, note_id: str | None = None
    ) -> list[tuple[str, list | None]]:
        """(card id, source_chunk_ids) for a document's cards, else a note's."""
        owner = (
            FlashcardModel.document_id == document_id
            if document_id
            else FlashcardModel.note_id == note_id
        )
        result = await self.session.execute(
            select(FlashcardModel.id, FlashcardModel.source_chunk_ids).where(owner)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def deck_has_note_content(self, deck: str, content_hash: str) -> bool:
        result = await self.session.execute(
            select(func.count())
            .select_from(FlashcardModel)
            .where(
                FlashcardModel.deck == deck,
                FlashcardModel.source == "note",
                FlashcardModel.source_content_hash == content_hash,
            )
        )
        return result.scalar_one() > 0

    async def list_for_deck(self, deck: str) -> list[FlashcardModel]:
        result = await self.session.execute(
            select(FlashcardModel).where(FlashcardModel.deck == deck)
        )
        return list(result.scalars().all())

    async def all_ids(self) -> set[str]:
        return set((await self.session.execute(select(FlashcardModel.id))).scalars().all())

    async def all_for(self, document_id: str | None) -> list[FlashcardModel]:
        """Every card of one document, or of the library when `document_id` is None."""
        stmt = select(FlashcardModel)
        if document_id is not None:
            stmt = stmt.where(FlashcardModel.document_id == document_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def detach_from_concepts(self) -> None:
        """Unmap every card from its concept; each keeps `concept_slug` to be re-mapped by."""
        await self.session.execute(
            update(FlashcardModel)
            .where(FlashcardModel.concept_id.is_not(None))
            .values(concept_id=None, mapping_status="unmapped")
        )

    async def map_slug_to_concept(self, slug: str, concept_id: str) -> int:
        """Map the cards carrying `slug` to `concept_id`; the number mapped."""
        result = await self.session.execute(
            update(FlashcardModel)
            .where(FlashcardModel.concept_slug == slug)
            .values(concept_id=concept_id, mapping_status="mapped")
        )
        return result.rowcount or 0

    async def slugged_but_unmapped(self) -> list[FlashcardModel]:
        result = await self.session.execute(
            select(FlashcardModel).where(
                FlashcardModel.concept_slug.is_not(None),
                FlashcardModel.concept_id.is_(None),
            )
        )
        return list(result.scalars().all())

    async def list_for_concept(self, concept_id: str) -> list[FlashcardModel]:
        result = await self.session.execute(
            select(FlashcardModel).where(FlashcardModel.concept_id == concept_id)
        )
        return list(result.scalars().all())

    async def due_in_scope(
        self,
        now: datetime,
        limit: int,
        *,
        concept_ids: Sequence[str] = (),
        document_ids: Sequence[str] = (),
        note_ids: Sequence[str] = (),
    ) -> list[FlashcardModel]:
        """Cards due by `now` on any of these concepts, documents or notes, most overdue first."""
        conds = []
        if concept_ids:
            conds.append(FlashcardModel.concept_id.in_(list(concept_ids)))
        if document_ids:
            conds.append(FlashcardModel.document_id.in_(list(document_ids)))
        if note_ids:
            conds.append(FlashcardModel.note_id.in_(list(note_ids)))
        if not conds:
            return []
        result = await self.session.execute(
            select(FlashcardModel)
            .where(FlashcardModel.due_date <= now, or_(*conds))
            .order_by(FlashcardModel.due_date.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_many(self, card_ids: Sequence[str]) -> dict[str, FlashcardModel]:
        """The cards among these ids that still exist, by id."""
        if not card_ids:
            return {}
        result = await self.session.execute(
            select(FlashcardModel).where(FlashcardModel.id.in_(list(card_ids)))
        )
        return {card.id: card for card in result.scalars().all()}

    async def grounding_counts(self, document_id: str | None = None) -> dict[str, int]:
        stmt = select(FlashcardModel.grounding, func.count()).group_by(FlashcardModel.grounding)
        if document_id is not None:
            stmt = stmt.where(FlashcardModel.document_id == document_id)
        return dict((await self.session.execute(stmt)).tuples().all())

    async def used_chunk_ids(self, document_id: str) -> set[str]:
        """Chunks some card of this document was written from."""
        result = await self.session.execute(
            select(FlashcardModel.source_chunk_ids).where(FlashcardModel.document_id == document_id)
        )
        return {cid for row in result.scalars() for cid in (row or []) if isinstance(cid, str)}

    async def deck_rollup(self) -> list[tuple[str | None, str, int, str | None]]:
        """(deck, a source, cards, a document_id) per deck."""
        result = await self.session.execute(
            select(
                FlashcardModel.deck,
                FlashcardModel.source,
                func.count(),
                func.max(FlashcardModel.document_id),
            ).group_by(FlashcardModel.deck)
        )
        return [tuple(r) for r in result.all()]

    async def list_existing_ids_in(self, card_ids: Sequence[str]) -> list[str]:
        if not card_ids:
            return []
        result = await self.session.execute(
            select(FlashcardModel.id).where(FlashcardModel.id.in_(list(card_ids)))
        )
        return list(result.scalars().all())

    async def list_ids_for_document(self, document_id: str) -> list[str]:
        result = await self.session.execute(
            select(FlashcardModel.id).where(FlashcardModel.document_id == document_id)
        )
        return list(result.scalars().all())

    async def chapters_written(self, document_id: str) -> set[str]:
        result = await self.session.execute(
            select(ChapterCardRunModel.chapter_id).where(
                ChapterCardRunModel.document_id == document_id
            )
        )
        return set(result.scalars().all())

    async def record_chapter_written(self, document_id: str, chapter_id: str, cards: int) -> None:
        self.session.add(
            ChapterCardRunModel(document_id=document_id, chapter_id=chapter_id, cards=cards)
        )

    async def chapter_counts(self, document_id: str) -> dict[str, tuple[int, int, int]]:
        """{chapter_id: (cards, held, due now)} for a document's chapter cards."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(
                FlashcardModel.chapter_id,
                func.count(FlashcardModel.id),
                func.sum(case((FlashcardModel.fsrs_state == CARD_HELD, 1), else_=0)),
                func.sum(case((FlashcardModel.due_date <= now, 1), else_=0)),
            )
            .where(
                FlashcardModel.document_id == document_id,
                FlashcardModel.chapter_id.is_not(None),
            )
            .group_by(FlashcardModel.chapter_id)
        )
        return {cid: (int(n), int(held or 0), int(due or 0)) for cid, n, held, due in result.all()}

    async def list_for_chapter(self, document_id: str, chapter_id: str) -> list[FlashcardModel]:
        result = await self.session.execute(
            select(FlashcardModel)
            .where(
                FlashcardModel.document_id == document_id,
                FlashcardModel.chapter_id == chapter_id,
            )
            .order_by(FlashcardModel.created_at, FlashcardModel.id)
        )
        return list(result.scalars().all())

    async def release_held(self, card_ids: Sequence[str]) -> int:
        """Move these cards, those still held, into the review schedule, due now."""
        if not card_ids:
            return 0
        result = await self.session.execute(
            update(FlashcardModel)
            .where(FlashcardModel.id.in_(list(card_ids)), FlashcardModel.fsrs_state == CARD_HELD)
            .values(fsrs_state="new", due_date=datetime.now(UTC))
        )
        await self.session.commit()
        return result.rowcount or 0

    async def list_document_ids_for_cards(self, card_ids: Sequence[str]) -> list[str]:
        """Distinct documents these cards belong to. Note-sourced cards have none."""
        if not card_ids:
            return []
        result = await self.session.execute(
            select(FlashcardModel.document_id)
            .where(FlashcardModel.id.in_(list(card_ids)))
            .where(FlashcardModel.document_id.is_not(None))
            .distinct()
        )
        return list(result.scalars().all())

    async def scope_stats(
        self, document_ids: Sequence[str], note_ids: Sequence[str], *, mastered_above: float
    ) -> tuple[int, int, int, int]:
        """(total, due now, new, mastered) over cards from these documents or notes."""
        clauses = []
        if document_ids:
            clauses.append(FlashcardModel.document_id.in_(list(document_ids)))
        if note_ids:
            clauses.append(FlashcardModel.note_id.in_(list(note_ids)))
        if not clauses:
            return 0, 0, 0, 0
        now = datetime.now(UTC)
        row = (
            await self.session.execute(
                select(
                    func.count(FlashcardModel.id),
                    func.sum(
                        case(
                            (
                                FlashcardModel.due_date.is_not(None)
                                & (FlashcardModel.due_date <= now),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(case((FlashcardModel.fsrs_state == "new", 1), else_=0)),
                    func.sum(case((FlashcardModel.fsrs_stability > mastered_above, 1), else_=0)),
                ).where(or_(*clauses))
            )
        ).one()
        total, due, new, mastered = (int(v or 0) for v in row)
        return total, due, new, mastered

    async def scheduled_document_cards(self) -> list[tuple[str, float, datetime]]:
        """(document id, stability, due date) for every reviewed, scheduled document card."""
        result = await self.session.execute(
            select(
                FlashcardModel.document_id,
                FlashcardModel.fsrs_stability,
                FlashcardModel.due_date,
            ).where(
                FlashcardModel.document_id.is_not(None),
                FlashcardModel.fsrs_stability > 0,
                FlashcardModel.due_date.is_not(None),
            )
        )
        return [(doc_id, stability, due) for doc_id, stability, due in result.all()]

    async def counts_by_document(self, document_ids: Sequence[str]) -> dict[str, int]:
        return await self._counts_by(FlashcardModel.document_id, document_ids)

    async def counts_by_note(self, note_ids: Sequence[str]) -> dict[str, int]:
        return await self._counts_by(FlashcardModel.note_id, note_ids)

    async def _counts_by(self, column, ids: Sequence[str]) -> dict[str, int]:  # type: ignore[no-untyped-def]
        if not ids:
            return {}
        result = await self.session.execute(
            select(column, func.count(FlashcardModel.id))
            .where(column.in_(list(ids)))
            .group_by(column)
        )
        return {key: int(n) for key, n in result.all()}

    async def concept_ids_for_cards(self, card_ids: Sequence[str]) -> list[str]:
        if not card_ids:
            return []
        result = await self.session.execute(
            select(FlashcardModel.concept_id).where(
                FlashcardModel.id.in_(list(card_ids)), FlashcardModel.concept_id.is_not(None)
            )
        )
        return [c for c in result.scalars().all() if c]

    async def list_ids_for_collection(self, collection_id: str) -> list[str]:
        result = await self.session.execute(
            select(FlashcardModel.id).where(collection_card_filter(collection_id))
        )
        return list(result.scalars().all())

    # -- writes ------------------------------------------------------------

    # -- FTS5 index: rows are found by rowid through the content shadow table (I-4) --

    async def _fts_rowid(self, card_id: str) -> int | None:
        row = (
            await self.session.execute(
                text("SELECT rowid FROM flashcards_fts_content WHERE c2 = :fid"),
                {"fid": card_id},
            )
        ).first()
        return row[0] if row else None

    async def fts_index(self) -> dict[str, int]:
        """{card id: rowid} for every row in the index."""
        rows = await self.session.execute(text("SELECT rowid, c2 FROM flashcards_fts_content"))
        return {card_id: rowid for rowid, card_id in rows.all()}

    async def delete_fts_row(self, rowid: int) -> None:
        await self.session.execute(
            text("DELETE FROM flashcards_fts WHERE rowid = :rid"), {"rid": rowid}
        )

    async def delete_fts(self, card_id: str) -> None:
        rowid = await self._fts_rowid(card_id)
        if rowid is not None:
            await self.delete_fts_row(rowid)

    async def sync_fts(self, card: FlashcardModel) -> None:
        """Index the card's question and answer, replacing any earlier row."""
        await self.delete_fts(card.id)
        await self.session.execute(
            text(
                "INSERT INTO flashcards_fts(flashcard_id, question, answer) VALUES (:fid, :q, :a)"
            ),
            {"fid": card.id, "q": card.question, "a": card.answer},
        )

    async def search(
        self,
        *,
        fts_match: str | None = None,
        like: str | None = None,
        document_id: str | None = None,
        collection_id: str | None = None,
        tag: str | None = None,
        bloom_level_min: int | None = None,
        bloom_level_max: int | None = None,
        fsrs_state: str | None = None,
        flashcard_type: str | None = None,
        section_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FlashcardModel], int]:
        """(one page newest first, total). `fts_match` is an FTS5 expression, `like` a substring."""
        stmt = select(FlashcardModel)
        if fts_match:
            fts_ids = (
                select(text("flashcard_id"))
                .select_from(text("flashcards_fts"))
                .where(text("flashcards_fts MATCH :q"))
            )
            stmt = stmt.where(FlashcardModel.id.in_(fts_ids)).params(q=fts_match)
        elif like:
            pattern = f"%{like}%"
            stmt = stmt.where(
                or_(FlashcardModel.question.ilike(pattern), FlashcardModel.answer.ilike(pattern))
            )
        if document_id:
            stmt = stmt.where(FlashcardModel.document_id == document_id)
        if collection_id:
            stmt = stmt.where(collection_card_filter(collection_id))
        if tag:
            tagged_notes = select(NoteTagIndexModel.note_id).where(
                or_(NoteTagIndexModel.tag_full == tag, NoteTagIndexModel.tag_full.like(tag + "/%"))
            )
            stmt = stmt.where(FlashcardModel.note_id.in_(tagged_notes))
        if bloom_level_min is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level >= bloom_level_min,
            )
        if bloom_level_max is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level <= bloom_level_max,
            )
        if fsrs_state:
            stmt = stmt.where(FlashcardModel.fsrs_state == fsrs_state)
        if flashcard_type:
            stmt = stmt.where(FlashcardModel.flashcard_type == flashcard_type)
        if section_id:
            # Through the chunk, so note-sourced cards (no chunk) never match a section.
            section_chunks = select(ChunkModel.id).where(ChunkModel.section_id == section_id)
            stmt = stmt.where(FlashcardModel.chunk_id.in_(section_chunks))

        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        if not total:
            return [], 0
        page_stmt = (
            stmt.order_by(FlashcardModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await self.session.execute(page_stmt)).scalars().all()), total

    async def commit_refresh(self, card: FlashcardModel) -> FlashcardModel:
        await self.session.commit()
        await self.session.refresh(card)
        return card

    async def delete_orphan_children(self) -> int:
        """Delete child rows whose card no longer exists; how many went."""
        removed = 0
        for model in _CARD_CHILD_TABLES:
            result = await self.session.execute(
                delete(model).where(model.flashcard_id.notin_(select(FlashcardModel.id)))
            )
            removed += result.rowcount or 0
        return removed

    async def _delete_children_of(self, card_ids: Sequence[str]) -> None:
        for model in _CARD_CHILD_TABLES:
            await self.session.execute(delete(model).where(model.flashcard_id.in_(list(card_ids))))

    async def delete_by_id(self, card_id: str) -> None:
        await self._delete_children_of([card_id])
        await self.session.execute(delete(FlashcardModel).where(FlashcardModel.id == card_id))
        await self.session.commit()

    async def delete_by_ids(self, card_ids: Sequence[str]) -> None:
        if not card_ids:
            await self.session.commit()
            return
        await self._delete_children_of(card_ids)
        await self.session.execute(
            delete(FlashcardModel).where(FlashcardModel.id.in_(list(card_ids)))
        )
        await self.session.commit()

    async def delete_for_document(self, document_id: str) -> None:
        ids = await self.list_ids_for_document(document_id)
        if ids:
            await self._delete_children_of(ids)
        await self.session.execute(
            delete(FlashcardModel).where(FlashcardModel.document_id == document_id)
        )
        await self.session.commit()


def get_flashcard_repo(session: AsyncSession = Depends(get_db)) -> FlashcardRepo:
    return FlashcardRepo(session)
