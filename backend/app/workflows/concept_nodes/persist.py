"""persist_concepts node -- write the flat concept layer to the stores (NW5).

Wipes the old concept layer, then persists concepts (level 2) as ConceptModel rows, Kuzu
Concept nodes + lateral RELATED_TO edges, and LanceDB centroid vectors. Identity is a STABLE
lineage-signature slug (hash of
member entities), not the volatile label -- so re-runs keep the same identity and user
overrides re-apply (docs/concept-model-design.md §6). Concept→chunk lineage is stashed in
evidence_json for downstream generation/mastery. No-ops on a dry run.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid

from sqlalchemy import delete, select, update

from app.database import get_session_factory
from app.models import ConceptModel, FlashcardModel
from app.services.graph import get_graph_service
from app.services.vector_store import get_lancedb_service
from app.workflows.concept_nodes._shared import (
    LEVEL_CONCEPT,
    ConceptPipelineState,
    record,
)

logger = logging.getLogger("concepts.pipeline")


def _sig_slug(entities: list[str]) -> str:
    """Stable identity: concept prefix + hash of the sorted member-entity signature."""
    sig = "".join(sorted(entities)).encode("utf-8")
    return f"c-{hashlib.sha1(sig).hexdigest()[:12]}"


async def persist_concepts(state: ConceptPipelineState) -> ConceptPipelineState:
    if state.get("dry_run"):
        record(state, "persist_concepts", {"persisted": 0, "skipped": "dry_run"})
        return state

    h = state.get("hierarchy")
    if not h or not h.get("concepts"):
        record(state, "persist_concepts", {"persisted": 0})
        return state

    concepts = h["concepts"]
    entity_chunks = state.get("entity_chunks", {})
    graph = get_graph_service()
    lance = get_lancedb_service()

    factory = get_session_factory()
    async with factory() as session:
        # --- detach cards from the about-to-be-deleted concepts. They KEEP concept_slug, the
        # durable binding we re-map below, so the learner's record survives the rebuild. ---
        await session.execute(
            update(FlashcardModel)
            .where(FlashcardModel.concept_id.is_not(None))
            .values(concept_id=None, mapping_status="unmapped")
        )
        await session.execute(delete(ConceptModel))
        await session.commit()
        graph.delete_all_concepts()
        await asyncio.to_thread(lance.clear_concept_vectors)

        used: set[str] = set()
        slug_to_id: dict[str, str] = {}      # stable slug -> new concept id (for card re-mapping)
        chunk_to_concept: dict[str, str] = {}  # source chunk -> concept id (re-grounding fallback)

        def _slug(entities: list[str]) -> str:
            base = _sig_slug(entities)
            slug, n = base, 2
            while slug in used:
                slug, n = f"{base}-{n}", n + 1
            used.add(slug)
            return slug

        # persist a concept -> returns its new id
        async def _persist(node: dict) -> str:
            cid = uuid.uuid4().hex
            slug = _slug(node.get("entities", [node.get("label", "")]))
            label = node.get("label") or node.get("sun") or slug
            # score_concepts marks low-quality concepts "candidate" (kept, but not studyable).
            status = node.get("status", "proposed")
            chunk_ids = sorted(
                {c for e in node.get("entities", []) for c in entity_chunks.get(e, [])}
            )[:25]
            evidence = [{
                "chunk_ids": chunk_ids,
                "document_ids": node.get("document_ids", []),
                "members": node.get("entities", [])[:12],
            }]
            session.add(
                ConceptModel(
                    id=cid, slug=slug, label=label, kind="concept", origin="document",
                    status=status, level=LEVEL_CONCEPT, parent_id=None,
                    salience=float(node.get("salience", 0.0)), evidence_json=evidence,
                )
            )
            slug_to_id[slug] = cid
            for ch in chunk_ids:
                chunk_to_concept.setdefault(ch, cid)
            try:
                graph.upsert_concept_node(cid, slug, label, "concept", status)
                for did in node.get("document_ids", []):
                    graph.add_extracted_from(cid, did)
            except Exception:
                pass
            if node.get("centroid"):
                await asyncio.to_thread(lance.upsert_concept_vector, cid, node["centroid"])
            return cid

        concept_ids: list[str] = [await _persist(c) for c in concepts]

        # lateral RELATED_TO concept edges
        for a, b, w in state.get("lateral_edges", []):
            try:
                graph.add_concept_relation(concept_ids[a], concept_ids[b], float(w), "proposed")
            except Exception:
                pass

        # --- re-map cards to the rebuilt concepts by STABLE slug, then re-derive mastery, so a
        # rebuild keeps the learner's record instead of orphaning it. ---
        rebound = 0
        id_to_slug = {cid: slug for slug, cid in slug_to_id.items()}
        for slug, new_id in slug_to_id.items():
            res = await session.execute(
                update(FlashcardModel)
                .where(FlashcardModel.concept_slug == slug)
                .values(concept_id=new_id, mapping_status="mapped")
            )
            rebound += res.rowcount or 0

        # fallback: a card whose slug vanished (concept drifted/merged) is re-grounded through its
        # source chunk -- ride the stable chunk layer, and correct its slug for the next rebuild.
        rebound_via_chunk = 0
        orphans = (
            await session.execute(
                select(FlashcardModel).where(
                    FlashcardModel.concept_slug.is_not(None),
                    FlashcardModel.concept_id.is_(None),
                )
            )
        ).scalars().all()
        for card in orphans:
            cid = chunk_to_concept.get(card.chunk_id) if card.chunk_id else None
            if cid:
                card.concept_id = cid
                card.concept_slug = id_to_slug.get(cid, card.concept_slug)
                card.mapping_status = "mapped"
                rebound_via_chunk += 1

        await session.commit()

        # re-derive concept mastery from the re-bound cards (card FSRS state was never lost)
        try:
            from app.services.mastery_service import get_mastery_service  # noqa: PLC0415

            await get_mastery_service().recompute_for_concepts(session, concept_ids)
            await session.commit()
        except Exception:
            logger.warning("persist: mastery recompute after rebuild failed", exc_info=True)

        # re-apply user corrections by stable slug
        try:
            from app.services.concept_service import get_concept_service  # noqa: PLC0415

            await get_concept_service().apply_overrides(session)
            await session.commit()
        except Exception:
            pass

    record(
        state,
        "persist_concepts",
        {
            "concepts": len(concept_ids),
            "persisted": len(concept_ids),
            "cards_rebound": rebound,
            "cards_rebound_via_chunk": rebound_via_chunk,
        },
    )
    return state
