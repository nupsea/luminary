"""ConceptService: create and maintain Concepts -- the studyable atom.

A Concept is distinct from a Kuzu Entity (a lexical NER mention). This service owns
the lifecycle that bridges the two: promoting an Entity cluster into a Concept,
proposing candidate concepts from non-document material, and keeping the four
representations in sync (SQLite state, Kuzu topology, LanceDB centroid vector;
the OKF projection is regenerated in Phase 5). See docs/concepts.md.

Mastery is NOT computed here by text match (I-19) -- the assessment pipeline writes
concepts.mastery; this service only persists what it is given via set_learning_state.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConceptModel
from app.services.graph import get_graph_service
from app.services.vector_store import get_lancedb_service

logger = logging.getLogger(__name__)

VALID_KINDS = {"concept", "keyword"}
VALID_ORIGINS = {"document", "note", "quiz", "chat", "import"}
VALID_STATUSES = {"candidate", "proposed", "confirmed"}


def slugify(label: str) -> str:
    """Lower-case-hyphenated slug; stable, OKF-filename-safe."""
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return s or "concept"


class ConceptService:
    async def _unique_slug(self, session: AsyncSession, label: str) -> str:
        base = slugify(label)
        slug = base
        n = 2
        while True:
            exists = await session.execute(
                select(ConceptModel.id).where(ConceptModel.slug == slug)
            )
            if exists.scalar_one_or_none() is None:
                return slug
            slug = f"{base}-{n}"
            n += 1

    async def get_by_label(self, session: AsyncSession, label: str) -> ConceptModel | None:
        result = await session.execute(
            select(ConceptModel).where(func.lower(ConceptModel.label) == label.lower())
        )
        return result.scalars().first()

    async def create_concept(
        self,
        session: AsyncSession,
        *,
        label: str,
        kind: str = "concept",
        origin: str = "document",
        status: str = "proposed",
        evidence: list[dict] | None = None,
        document_ids: list[str] | None = None,
        entity_ids: list[str] | None = None,
    ) -> ConceptModel:
        """Create a Concept across SQLite + Kuzu + LanceDB.

        evidence items are {document_id, chunk_id, quote}. The LanceDB centroid is
        derived from the evidence chunk_ids (free; no new embedding calls). Flushes
        the SQLite row but does not commit -- the caller owns the transaction.
        """
        if kind not in VALID_KINDS:
            raise ValueError(f"invalid kind: {kind}")
        if origin not in VALID_ORIGINS:
            raise ValueError(f"invalid origin: {origin}")
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")

        evidence = evidence or []
        document_ids = list(document_ids or [])
        entity_ids = list(entity_ids or [])

        concept_id = uuid.uuid4().hex
        slug = await self._unique_slug(session, label)
        row = ConceptModel(
            id=concept_id,
            slug=slug,
            label=label,
            kind=kind,
            origin=origin,
            status=status,
            evidence_json=evidence,
        )
        session.add(row)
        await session.flush()

        # Kuzu topology (sync, lock-serialized). Guarded so a graph hiccup never
        # blocks the SQLite source of truth.
        try:
            graph = get_graph_service()
            graph.upsert_concept_node(concept_id, slug, label, kind, status)
            for did in document_ids:
                graph.add_extracted_from(concept_id, did)
            for eid in entity_ids:
                graph.add_promoted_from(concept_id, eid)
        except Exception:
            logger.warning("create_concept: Kuzu writes failed for %s", concept_id, exc_info=True)

        await self.refresh_vector(concept_id, evidence)
        return row

    async def refresh_vector(self, concept_id: str, evidence: list[dict]) -> None:
        """Recompute and upsert the concept's centroid vector from its evidence chunks (I-2)."""
        chunk_ids = [e["chunk_id"] for e in evidence if e.get("chunk_id")]
        if not chunk_ids:
            return
        lance = get_lancedb_service()
        centroid = await asyncio.to_thread(lance.compute_centroid, chunk_ids)
        if centroid is not None:
            await asyncio.to_thread(lance.upsert_concept_vector, concept_id, centroid)

    async def set_learning_state(
        self,
        session: AsyncSession,
        concept_id: str,
        mastery: float,
        stability: float | None = None,
        last_reviewed: datetime | None = None,
    ) -> None:
        """Persist FSRS-derived learning state written by the assessment pipeline (I-19)."""
        row = await session.get(ConceptModel, concept_id)
        if row is None:
            return
        row.mastery = float(mastery)
        if stability is not None:
            row.stability = float(stability)
        if last_reviewed is not None:
            row.last_reviewed = last_reviewed

    async def promote_status(self, session: AsyncSession, concept_id: str) -> None:
        """A proposed/candidate concept becomes confirmed once used or confirmed (trust accrues)."""
        row = await session.get(ConceptModel, concept_id)
        if row is None or row.status == "confirmed":
            return
        row.status = "confirmed"
        try:
            get_graph_service().upsert_concept_node(
                row.id, row.slug, row.label, row.kind, "confirmed"
            )
        except Exception:
            logger.debug("promote_status: Kuzu update failed for %s", concept_id, exc_info=True)

    async def map_flashcard(
        self, session: AsyncSession, flashcard_id: str, concept_id: str | None
    ) -> None:
        """Set a flashcard's concept_id + mapping_status (mapped when a concept, else unmapped)."""
        from app.models import FlashcardModel  # noqa: PLC0415 -- avoid import cycle at module load

        card = await session.get(FlashcardModel, flashcard_id)
        if card is None:
            return
        card.concept_id = concept_id
        card.mapping_status = "mapped" if concept_id else "unmapped"

    async def delete_concept(self, session: AsyncSession, concept_id: str) -> None:
        """Remove a concept from all three stores. The caller commits SQLite."""
        row = await session.get(ConceptModel, concept_id)
        if row is not None:
            await session.delete(row)
        try:
            get_graph_service().delete_concept_node(concept_id)
        except Exception:
            logger.debug("delete_concept: Kuzu delete failed for %s", concept_id, exc_info=True)
        try:
            await asyncio.to_thread(get_lancedb_service().delete_concept_vector, concept_id)
        except Exception:
            logger.debug("delete_concept: vector delete failed for %s", concept_id, exc_info=True)


_concept_service: ConceptService | None = None


def get_concept_service() -> ConceptService:
    global _concept_service
    if _concept_service is None:
        _concept_service = ConceptService()
    return _concept_service
