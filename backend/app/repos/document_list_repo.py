"""The library list: one page of documents with every per-card aggregate, in one query.

Each aggregate is a correlated scalar subquery so the page costs one round trip however
many cards it shows; filters and sort are pushed into the same SQL so `total` and the
page agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChunkModel,
    CollectionMemberModel,
    DocumentModel,
    DocumentTagIndexModel,
    EnrichmentJobModel,
    FlashcardModel,
    LearningObjectiveModel,
    PredictionEventModel,
    ReadingProgressModel,
    SectionModel,
    StudySessionModel,
    SummaryModel,
)

DocumentSort = Literal[
    "newest", "oldest", "alphabetical", "most-studied", "last_accessed", "weakest-first"
]


@dataclass(frozen=True)
class DocumentListFilters:
    formats: list[str]
    content_types: list[str]
    tag: str | None = None
    collection_id: str | None = None
    favorite: bool | None = None


@dataclass(frozen=True)
class DocumentListRow:
    doc: DocumentModel
    summary_one_sentence: str | None
    flashcard_count: int
    summary_count: int
    study_session_count: int
    chunk_count: int
    section_count: int
    read_section_count: int
    enrichment_priority: int | None
    objectives_total: int
    objectives_covered: int
    mastery_sum_contribution: float | None
    mastery_sum_weight: float | None
    prediction_error_count: int


def _count(model, *where: ColumnElement[bool]):
    return (
        select(func.count())
        .where(model.document_id == DocumentModel.id, *where)
        .correlate(DocumentModel)
        .scalar_subquery()
    )


def _per_document(expr, model):
    return (
        select(expr)
        .where(model.document_id == DocumentModel.id)
        .correlate(DocumentModel)
        .scalar_subquery()
    )


# Precedence is by what the reader can act on, not by job type: outstanding work, then a
# failure, then a skip (a model never installed), then done. One job's state is not the
# document's: six job types run per document.
_ENRICHMENT_PRIORITY = func.min(
    case(
        (EnrichmentJobModel.status.in_(("pending", "running")), 1),
        (EnrichmentJobModel.status == "failed", 2),
        (EnrichmentJobModel.status == "skipped", 3),
        (EnrichmentJobModel.status == "done", 4),
        else_=5,
    )
)

# Mirrors MasteryService._compute_weighted_mastery: stability capped at 21 days, Bloom 4+
# weighted 1.5.
_BLOOM_WEIGHT = case((FlashcardModel.bloom_level >= 4, 1.5), else_=1.0)
_CAPPED_STABILITY = func.min(FlashcardModel.fsrs_stability / 21.0, 1.0)


class DocumentListRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def page(
        self, filters: DocumentListFilters, sort: DocumentSort, page: int, page_size: int
    ) -> tuple[int, list[DocumentListRow]]:
        """(total under the filters, the requested page of rows)."""
        where = _where(filters)

        count_stmt = select(func.count()).select_from(DocumentModel).where(*where)
        total = int((await self.session.execute(count_stmt)).scalar_one())

        columns = {
            "summary_one_sentence": (
                select(SummaryModel.content)
                .where(
                    SummaryModel.document_id == DocumentModel.id,
                    SummaryModel.mode == "one_sentence",
                )
                .limit(1)
                .correlate(DocumentModel)
                .scalar_subquery()
            ),
            "flashcard_count": _count(FlashcardModel),
            "summary_count": _count(SummaryModel),
            "study_session_count": _count(StudySessionModel),
            "chunk_count": _count(ChunkModel),
            "section_count": _count(SectionModel),
            "read_section_count": _count(ReadingProgressModel),
            "enrichment_priority": _per_document(_ENRICHMENT_PRIORITY, EnrichmentJobModel),
            "objectives_total": _count(LearningObjectiveModel),
            "objectives_covered": _count(
                LearningObjectiveModel, LearningObjectiveModel.covered.is_(True)
            ),
            "mastery_sum_contribution": _per_document(
                func.sum(_CAPPED_STABILITY * _BLOOM_WEIGHT), FlashcardModel
            ),
            "mastery_sum_weight": _per_document(func.sum(_BLOOM_WEIGHT), FlashcardModel),
            "prediction_error_count": _count(
                PredictionEventModel, PredictionEventModel.correct.is_(False)
            ),
        }
        stmt = (
            select(DocumentModel, *(c.label(name) for name, c in columns.items()))
            .where(*where)
            .order_by(*_order(sort, columns))
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = (await self.session.execute(stmt)).all()
        return total, [_row(r) for r in rows]


def _where(filters: DocumentListFilters) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if filters.formats:
        clauses.append(DocumentModel.format.in_(filters.formats))
    if filters.content_types:
        clauses.append(DocumentModel.content_type.in_(filters.content_types))
    if filters.tag:
        # Prefix match, as the note tag filter: ?tag=science also matches 'science/biology'.
        clauses.append(
            select(DocumentTagIndexModel.document_id)
            .where(
                DocumentTagIndexModel.document_id == DocumentModel.id,
                or_(
                    DocumentTagIndexModel.tag_full == filters.tag,
                    DocumentTagIndexModel.tag_full.like(f"{filters.tag}/%"),
                ),
            )
            .exists()
        )
    if filters.collection_id:
        clauses.append(
            select(CollectionMemberModel.id)
            .where(
                CollectionMemberModel.collection_id == filters.collection_id,
                CollectionMemberModel.member_id == DocumentModel.id,
                CollectionMemberModel.member_type == "document",
            )
            .exists()
        )
    if filters.favorite is not None:
        clauses.append(DocumentModel.is_favorite == filters.favorite)
    return clauses


def _order(sort: DocumentSort, c: dict) -> list:
    if sort == "newest":
        return [DocumentModel.created_at.desc()]
    if sort == "oldest":
        return [DocumentModel.created_at.asc()]
    if sort == "alphabetical":
        return [func.lower(DocumentModel.title).asc()]
    if sort == "last_accessed":
        return [DocumentModel.last_accessed_at.desc()]
    if sort == "weakest-first":
        # No cards sorts last: a document with nothing to master is not a weak one.
        weight = c["mastery_sum_weight"]
        return [
            case((weight > 0, 0), else_=1).asc(),
            (c["mastery_sum_contribution"] / weight).asc(),
            DocumentModel.created_at.desc(),
        ]
    learning_status = case(
        (c["study_session_count"] > 0, 3),
        (c["flashcard_count"] > 0, 2),
        (c["summary_count"] > 0, 1),
        else_=0,
    )
    return [learning_status.desc(), DocumentModel.created_at.desc()]


def _row(r) -> DocumentListRow:
    m = r._mapping
    return DocumentListRow(
        doc=r[0],
        summary_one_sentence=m["summary_one_sentence"],
        flashcard_count=m["flashcard_count"] or 0,
        summary_count=m["summary_count"] or 0,
        study_session_count=m["study_session_count"] or 0,
        chunk_count=m["chunk_count"] or 0,
        section_count=m["section_count"] or 0,
        read_section_count=m["read_section_count"] or 0,
        enrichment_priority=m["enrichment_priority"],
        objectives_total=m["objectives_total"] or 0,
        objectives_covered=m["objectives_covered"] or 0,
        mastery_sum_contribution=m["mastery_sum_contribution"],
        mastery_sum_weight=m["mastery_sum_weight"],
        prediction_error_count=m["prediction_error_count"] or 0,
    )
