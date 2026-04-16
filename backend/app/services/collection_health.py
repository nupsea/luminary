"""CollectionHealthService -- computes health metrics for a note collection.

Metrics:
  cohesion_score    -- mean pairwise cosine similarity of note vectors (LanceDB)
  orphaned_notes    -- notes library-wide with no collection membership
  uncovered_notes   -- collection notes with no flashcard (source='note', deck=collection.name)
  stale_notes       -- collection notes not edited in 90+ days
  hotspot_tags      -- top 5 tags by count across notes in this collection
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FlashcardModel,
    CollectionMemberModel,
    CollectionModel,
    NoteModel,
    NoteTagIndexModel,
)

logger = logging.getLogger(__name__)

_STALE_DAYS = 90
_COHESION_MIN_NOTES = 6
_HOTSPOT_TOP_N = 5


class UncoveredNote(TypedDict):
    note_id: str
    preview: str


class StaleNote(TypedDict):
    note_id: str
    preview: str
    last_updated: str


class HotspotTag(TypedDict):
    tag: str
    count: int


class CollectionHealthReport(TypedDict):
    collection_id: str
    collection_name: str
    cohesion_score: float | None
    note_count: int
    orphaned_notes: list[str]
    uncovered_notes: list[UncoveredNote]
    stale_notes: list[StaleNote]
    hotspot_tags: list[HotspotTag]


def _compute_cohesion(vectors: list[list[float]]) -> float | None:
    """Mean pairwise cosine similarity. Returns None when < 6 vectors."""
    if len(vectors) < _COHESION_MIN_NOTES:
        return None
    import numpy as np  # noqa: PLC0415

    mat = np.array(vectors, dtype=np.float32)
    # L2-normalise rows
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    mat = mat / norms
    # Similarity matrix: N x N
    sim = mat @ mat.T
    n = len(vectors)
    # Upper triangle (exclude diagonal)
    upper_indices = np.triu_indices(n, k=1)
    upper_values = sim[upper_indices]
    if len(upper_values) == 0:
        return None
    return float(np.mean(upper_values))


async def _fetch_cohesion_score(note_ids: list[str]) -> float | None:
    """Fetch vectors from LanceDB and compute cohesion score (asyncio.to_thread)."""
    if len(note_ids) < _COHESION_MIN_NOTES:
        return None

    def _sync_fetch(ids: list[str]) -> list[list[float]]:
        from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

        svc = get_lancedb_service()
        try:
            tbl = svc._get_or_create_note_table()  # noqa: SLF001
        except Exception as exc:
            logger.warning("Could not open note_vectors_v2 for cohesion: %s", exc)
            return []

        id_filter = ", ".join(f"'{nid}'" for nid in ids)
        try:
            df = tbl.to_pandas(filter=f"note_id IN ({id_filter})")
            vectors: list[list[float]] = []
            for row in df.itertuples():
                v = row.vector
                if hasattr(v, "tolist"):
                    vectors.append(v.tolist())
                else:
                    vectors.append(list(v))
            return vectors
        except Exception as exc:
            logger.warning("LanceDB note vector fetch failed: %s", exc)
            return []

    vectors = await asyncio.to_thread(_sync_fetch, note_ids)
    if len(vectors) < _COHESION_MIN_NOTES:
        return None
    return _compute_cohesion(vectors)


class CollectionHealthService:
    async def analyze(
        self, collection_id: str, session: AsyncSession
    ) -> CollectionHealthReport:
        """Compute all health metrics for the given collection."""
        # Fetch collection
        col_result = await session.execute(
            select(CollectionModel).where(CollectionModel.id == collection_id)
        )
        col = col_result.scalar_one_or_none()
        if col is None:
            raise ValueError(f"Collection {collection_id!r} not found")

        # Member note IDs
        member_result = await session.execute(
            select(CollectionMemberModel.member_id).where(
                CollectionMemberModel.collection_id == collection_id,
                CollectionMemberModel.member_type == "note",
            )
        )
        member_note_ids: list[str] = [row[0] for row in member_result.all()]
        note_count = len(member_note_ids)

        # Cohesion (async, uses LanceDB)
        cohesion_score = await _fetch_cohesion_score(member_note_ids)

        # Orphaned notes (library-wide: notes not in any collection)
        orphaned_result = await session.execute(
            select(NoteModel.id).where(
                NoteModel.archived.is_(False),
                NoteModel.id.not_in(
                    select(CollectionMemberModel.member_id).where(
                        CollectionMemberModel.member_type == "note"
                    ).distinct()
                ),
            )
        )
        orphaned_notes: list[str] = [row[0] for row in orphaned_result.all()]

        # Uncovered notes: notes in this collection with no flashcard row
        # (source='note', deck=collection.name, note_id=note_id)
        if member_note_ids:
            covered_result = await session.execute(
                select(FlashcardModel.note_id.distinct()).where(
                    FlashcardModel.source == "note",
                    FlashcardModel.deck == col.name,
                    FlashcardModel.note_id.in_(member_note_ids),
                    FlashcardModel.note_id.is_not(None),
                )
            )
            covered_ids: set[str] = {row[0] for row in covered_result.all()}
        else:
            covered_ids = set()

        uncovered_note_ids = [nid for nid in member_note_ids if nid not in covered_ids]
        uncovered_notes: list[UncoveredNote] = []
        if uncovered_note_ids:
            note_rows = await session.execute(
                select(NoteModel.id, NoteModel.content).where(
                    NoteModel.id.in_(uncovered_note_ids)
                )
            )
            for nid, content in note_rows.all():
                uncovered_notes.append(
                    UncoveredNote(note_id=nid, preview=content[:120])
                )

        # Stale notes: updated_at < now - 90 days, not archived
        stale_threshold = datetime.now(UTC) - timedelta(days=_STALE_DAYS)
        stale_notes: list[StaleNote] = []
        if member_note_ids:
            stale_result = await session.execute(
                select(NoteModel.id, NoteModel.content, NoteModel.updated_at).where(
                    NoteModel.id.in_(member_note_ids),
                    NoteModel.archived.is_(False),
                    NoteModel.updated_at < stale_threshold,
                )
            )
            for nid, content, updated_at in stale_result.all():
                stale_notes.append(
                    StaleNote(
                        note_id=nid,
                        preview=content[:120],
                        last_updated=updated_at.isoformat() if updated_at else "",
                    )
                )

        # Hotspot tags: top 5 tags by count for notes in this collection
        hotspot_tags: list[HotspotTag] = []
        if member_note_ids:
            tag_rows = await session.execute(
                select(NoteTagIndexModel.tag_full, func.count(NoteTagIndexModel.note_id))
                .where(NoteTagIndexModel.note_id.in_(member_note_ids))
                .group_by(NoteTagIndexModel.tag_full)
                .order_by(func.count(NoteTagIndexModel.note_id).desc())
                .limit(_HOTSPOT_TOP_N)
            )
            for tag_full, count in tag_rows.all():
                hotspot_tags.append(HotspotTag(tag=tag_full, count=count))

        return CollectionHealthReport(
            collection_id=collection_id,
            collection_name=col.name,
            cohesion_score=cohesion_score,
            note_count=note_count,
            orphaned_notes=orphaned_notes,
            uncovered_notes=uncovered_notes,
            stale_notes=stale_notes,
            hotspot_tags=hotspot_tags,
        )

    async def archive_stale(
        self, collection_id: str, session: AsyncSession
    ) -> int:
        """Set archived=True for stale notes in this collection. Returns count archived."""
        col_result = await session.execute(
            select(CollectionModel).where(CollectionModel.id == collection_id)
        )
        col = col_result.scalar_one_or_none()
        if col is None:
            raise ValueError(f"Collection {collection_id!r} not found")

        member_result = await session.execute(
            select(CollectionMemberModel.member_id).where(
                CollectionMemberModel.collection_id == collection_id,
                CollectionMemberModel.member_type == "note",
            )
        )
        member_note_ids = [row[0] for row in member_result.all()]

        if not member_note_ids:
            return 0

        stale_threshold = datetime.now(UTC) - timedelta(days=_STALE_DAYS)
        stale_result = await session.execute(
            select(NoteModel).where(
                NoteModel.id.in_(member_note_ids),
                NoteModel.archived.is_(False),
                NoteModel.updated_at < stale_threshold,
            )
        )
        stale_notes = list(stale_result.scalars().all())

        for note in stale_notes:
            note.archived = True
        await session.commit()
        logger.info(
            "Archived %d stale notes in collection id=%s", len(stale_notes), collection_id
        )
        return len(stale_notes)


_service: CollectionHealthService | None = None


def get_collection_health_service() -> CollectionHealthService:
    global _service
    if _service is None:
        _service = CollectionHealthService()
    return _service
