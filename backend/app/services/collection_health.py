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

from sqlalchemy.ext.asyncio import AsyncSession

from app.repos.collection_repo import CollectionRepo
from app.repos.note_repo import NoteRepo

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
        from app.services.vector_store import (  # noqa: PLC0415
            get_lancedb_service,
            id_predicate,
        )

        svc = get_lancedb_service()
        try:
            tbl = svc._get_or_create_note_table()  # noqa: SLF001
        except Exception as exc:
            logger.warning("Could not open note_vectors_v2 for cohesion: %s", exc)
            return []

        pred = id_predicate("note_id", ids, context="collection_cohesion")
        if pred is None:
            return []
        try:
            df = tbl.to_pandas(filter=pred)
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
    async def analyze(self, collection_id: str, session: AsyncSession) -> CollectionHealthReport:
        """Compute all health metrics for the given collection."""
        collections = CollectionRepo(session)
        notes = NoteRepo(session)
        col = await collections.find(collection_id)
        if col is None:
            raise ValueError(f"Collection {collection_id!r} not found")

        member_note_ids = await collections.note_ids(collection_id)
        cohesion_score = await _fetch_cohesion_score(member_note_ids)
        orphaned_notes = await notes.ids_outside_collections()

        covered_ids = await notes.ids_with_deck_cards(col.name, member_note_ids)
        uncovered_note_ids = [nid for nid in member_note_ids if nid not in covered_ids]
        uncovered_notes = [
            UncoveredNote(note_id=nid, preview=preview)
            for nid, preview, _length in await notes.snippets(uncovered_note_ids, 120)
        ]

        stale_threshold = datetime.now(UTC) - timedelta(days=_STALE_DAYS)
        stale_notes = [
            StaleNote(
                note_id=note.id,
                preview=note.content[:120],
                last_updated=note.updated_at.isoformat() if note.updated_at else "",
            )
            for note in await notes.stale_among(member_note_ids, stale_threshold)
        ]

        hotspot_tags = [
            HotspotTag(tag=tag, count=count)
            for tag, count in await notes.top_tags_among(member_note_ids, _HOTSPOT_TOP_N)
        ]

        return CollectionHealthReport(
            collection_id=collection_id,
            collection_name=col.name,
            cohesion_score=cohesion_score,
            note_count=len(member_note_ids),
            orphaned_notes=orphaned_notes,
            uncovered_notes=uncovered_notes,
            stale_notes=stale_notes,
            hotspot_tags=hotspot_tags,
        )

    async def archive_stale(self, collection_id: str, session: AsyncSession) -> int:
        """Set archived=True for stale notes in this collection. Returns count archived."""
        collections = CollectionRepo(session)
        if await collections.find(collection_id) is None:
            raise ValueError(f"Collection {collection_id!r} not found")

        stale_threshold = datetime.now(UTC) - timedelta(days=_STALE_DAYS)
        stale_notes = await NoteRepo(session).stale_among(
            await collections.note_ids(collection_id), stale_threshold
        )
        if not stale_notes:
            return 0
        for note in stale_notes:
            note.archived = True
        await session.commit()
        logger.info("Archived %d stale notes in collection id=%s", len(stale_notes), collection_id)
        return len(stale_notes)


_service: CollectionHealthService | None = None


def get_collection_health_service() -> CollectionHealthService:
    global _service
    if _service is None:
        _service = CollectionHealthService()
    return _service
