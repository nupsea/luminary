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
        await self._rollup_ancestors(session, row.parent_id)

    async def _rollup_ancestors(self, session: AsyncSession, node_id: str | None) -> None:
        """Bottom-up: a container's mastery = salience-weighted mean of its children,
        last_reviewed = max(children). Walks up galaxy<-constellation<-concept so studying
        a leaf warms its parents on the Universe (docs/concept-model-design.md §7)."""
        while node_id:
            node = await session.get(ConceptModel, node_id)
            if node is None:
                return
            children = (
                await session.execute(
                    select(
                        ConceptModel.mastery, ConceptModel.salience, ConceptModel.last_reviewed
                    ).where(ConceptModel.parent_id == node_id)
                )
            ).all()
            if children:
                wsum = sum((c[1] or 0.0) + 1e-6 for c in children)
                node.mastery = sum(c[0] * ((c[1] or 0.0) + 1e-6) for c in children) / wsum
                seen = [c[2] for c in children if c[2] is not None]
                if seen:
                    node.last_reviewed = max(seen)
            node_id = node.parent_id

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

    # -------------------------------------------------------------------------
    # Corrections -- the user's permanent voice over Lumen's guesses (docs/concepts.md).
    # Each mutates the concept AND records an Override keyed by slug so it survives
    # re-parse via apply_overrides (I-22). Callers commit.
    # -------------------------------------------------------------------------

    async def _record_override(
        self,
        session: AsyncSession,
        *,
        kind: str,
        target_key: str,
        payload: dict | None = None,
        target_type: str = "concept",
    ) -> None:
        from app.models import OverrideModel  # noqa: PLC0415

        session.add(
            OverrideModel(
                id=uuid.uuid4().hex,
                kind=kind,
                target_type=target_type,
                target_key=target_key,
                payload_json=payload or {},
            )
        )

    async def rename_concept(
        self, session: AsyncSession, concept_id: str, new_label: str
    ) -> ConceptModel | None:
        """Rename a concept. Slug (the stable identity) is preserved on purpose."""
        row = await session.get(ConceptModel, concept_id)
        if row is None:
            return None
        row.label = new_label
        try:
            get_graph_service().upsert_concept_node(
                row.id, row.slug, new_label, row.kind, row.status
            )
        except Exception:
            logger.debug("rename_concept: Kuzu update failed for %s", concept_id, exc_info=True)
        await self._record_override(
            session, kind="rename", target_key=row.slug, payload={"label": new_label}
        )
        return row

    async def reclassify_concept(
        self, session: AsyncSession, concept_id: str, kind: str
    ) -> ConceptModel | None:
        """Reclassify concept<->keyword."""
        if kind not in VALID_KINDS:
            raise ValueError(f"invalid kind: {kind}")
        row = await session.get(ConceptModel, concept_id)
        if row is None:
            return None
        row.kind = kind
        try:
            get_graph_service().upsert_concept_node(
                row.id, row.slug, row.label, kind, row.status
            )
        except Exception:
            logger.debug("reclassify: Kuzu update failed for %s", concept_id, exc_info=True)
        await self._record_override(
            session, kind="reclassify", target_key=row.slug, payload={"kind": kind}
        )
        return row

    async def confirm_concept(self, session: AsyncSession, concept_id: str) -> None:
        """Confirm a proposed/candidate concept (trust accrues)."""
        row = await session.get(ConceptModel, concept_id)
        if row is None:
            return
        await self.promote_status(session, concept_id)
        await self._record_override(session, kind="confirm_concept", target_key=row.slug)

    async def reject_concept(self, session: AsyncSession, concept_id: str) -> None:
        """Reject 'not a concept'. Records the override BEFORE deleting (slug needed)."""
        row = await session.get(ConceptModel, concept_id)
        if row is None:
            return
        await self._record_override(session, kind="reject_concept", target_key=row.slug)
        await self.delete_concept(session, concept_id)

    async def merge_concepts(
        self, session: AsyncSession, source_id: str, target_id: str
    ) -> ConceptModel | None:
        """Merge source into target: move cards + union evidence, delete source."""
        from app.models import FlashcardModel  # noqa: PLC0415

        if source_id == target_id:
            return await session.get(ConceptModel, target_id)
        source = await session.get(ConceptModel, source_id)
        target = await session.get(ConceptModel, target_id)
        if source is None or target is None:
            return None
        # reassign the source's mapped cards to the target
        cards = (
            await session.execute(
                select(FlashcardModel).where(FlashcardModel.concept_id == source_id)
            )
        ).scalars().all()
        for c in cards:
            c.concept_id = target_id
        # union evidence and refresh the target's centroid vector
        merged_evidence = list(target.evidence_json or []) + list(source.evidence_json or [])
        target.evidence_json = merged_evidence
        await self._record_override(
            session, kind="merge", target_key=source.slug, payload={"into": target.slug}
        )
        await self.delete_concept(session, source_id)
        await self.refresh_vector(target_id, merged_evidence)
        return target

    async def apply_overrides(self, session: AsyncSession) -> int:
        """Re-apply every stored override on top of the current concepts (I-22).

        Idempotent: matches concepts by stable slug. Called after a re-parse produces
        fresh proposals. Returns the number of overrides applied.
        """
        from app.models import OverrideModel  # noqa: PLC0415

        overrides = (
            await session.execute(select(OverrideModel).order_by(OverrideModel.created_at.asc()))
        ).scalars().all()
        applied = 0
        for ov in overrides:
            row = (
                await session.execute(
                    select(ConceptModel).where(ConceptModel.slug == ov.target_key)
                )
            ).scalars().first()
            payload = ov.payload_json or {}
            if ov.kind == "reject_concept":
                if row is not None:
                    await self.delete_concept(session, row.id)
                    applied += 1
            elif row is None:
                continue
            elif ov.kind == "rename":
                row.label = payload.get("label", row.label)
                applied += 1
            elif ov.kind == "reclassify":
                row.kind = payload.get("kind", row.kind)
                applied += 1
            elif ov.kind == "confirm_concept":
                row.status = "confirmed"
                applied += 1
            elif ov.kind == "merge":
                target = (
                    await session.execute(
                        select(ConceptModel).where(ConceptModel.slug == payload.get("into"))
                    )
                ).scalars().first()
                if target is not None:
                    await self.merge_concepts(session, row.id, target.id)
                    applied += 1
        return applied


_concept_service: ConceptService | None = None


def get_concept_service() -> ConceptService:
    global _concept_service
    if _concept_service is None:
        _concept_service = ConceptService()
    return _concept_service
