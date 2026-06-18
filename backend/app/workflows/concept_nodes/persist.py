"""persist_concepts node -- write the named hierarchy to the stores (NW5).

Wipes the old concept layer, then persists galaxies (level 0) / constellations (1) /
concepts (2) as ConceptModel rows with parent_id chains, Kuzu Concept nodes + lateral
edges, and LanceDB centroid vectors. Identity is a STABLE lineage-signature slug (hash of
member entities), not the volatile label -- so re-runs keep the same identity and user
overrides re-apply (docs/concept-model-design.md §6). Concept→chunk lineage is stashed in
evidence_json for downstream generation/mastery. No-ops on a dry run.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid

from sqlalchemy import delete, update

from app.database import get_session_factory
from app.models import ConceptModel, FlashcardModel
from app.services.graph import get_graph_service
from app.services.vector_store import get_lancedb_service
from app.workflows.concept_nodes._shared import (
    LEVEL_CONCEPT,
    LEVEL_CONSTELLATION,
    LEVEL_GALAXY,
    ConceptPipelineState,
    record,
)

_PREFIX = {LEVEL_GALAXY: "g", LEVEL_CONSTELLATION: "k", LEVEL_CONCEPT: "c"}


def _sig_slug(level: int, entities: list[str]) -> str:
    """Stable identity: level prefix + hash of the sorted member-entity signature."""
    sig = "".join(sorted(entities)).encode("utf-8")
    return f"{_PREFIX[level]}-{hashlib.sha1(sig).hexdigest()[:12]}"


async def persist_concepts(state: ConceptPipelineState) -> ConceptPipelineState:
    if state.get("dry_run"):
        record(state, "persist_concepts", {"persisted": 0, "skipped": "dry_run"})
        return state

    h = state.get("hierarchy")
    if not h or not h.get("concepts"):
        record(state, "persist_concepts", {"persisted": 0})
        return state

    galaxies, constellations, concepts = h["galaxies"], h["constellations"], h["concepts"]
    entity_chunks = state.get("entity_chunks", {})
    graph = get_graph_service()
    lance = get_lancedb_service()

    factory = get_session_factory()
    async with factory() as session:
        # --- wipe the old concept layer (cards preserved, just unmapped) ---
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

        def _slug(level: int, entities: list[str]) -> str:
            base = _sig_slug(level, entities)
            slug, n = base, 2
            while slug in used:
                slug, n = f"{base}-{n}", n + 1
            used.add(slug)
            return slug

        # persist a node -> returns its new id
        async def _persist(node: dict, level: int, parent_id: str | None) -> str:
            cid = uuid.uuid4().hex
            slug = _slug(level, node.get("entities", [node.get("label", "")]))
            label = node.get("label") or node.get("sun") or slug
            evidence = []
            if level == LEVEL_CONCEPT:
                chunk_ids = sorted(
                    {c for e in node.get("entities", []) for c in entity_chunks.get(e, [])}
                )[:25]
                evidence = [{"chunk_ids": chunk_ids, "members": node.get("entities", [])[:12]}]
            session.add(
                ConceptModel(
                    id=cid, slug=slug, label=label, kind="concept", origin="document",
                    status="proposed", level=level, parent_id=parent_id,
                    salience=float(node.get("salience", 0.0)), evidence_json=evidence,
                )
            )
            try:
                graph.upsert_concept_node(cid, slug, label, "concept", "proposed")
                for did in node.get("document_ids", []):
                    graph.add_extracted_from(cid, did)
            except Exception:
                pass
            if node.get("centroid"):
                await asyncio.to_thread(lance.upsert_concept_vector, cid, node["centroid"])
            return cid

        # galaxies -> constellations -> concepts, threading parent ids
        gal_ids = [await _persist(g, LEVEL_GALAXY, None) for g in galaxies]
        con_ids: list[str] = []
        for con in constellations:
            con_ids.append(await _persist(con, LEVEL_CONSTELLATION, gal_ids[con["parent_idx"]]))
        concept_ids: list[str] = []
        for c in concepts:
            concept_ids.append(await _persist(c, LEVEL_CONCEPT, con_ids[c["parent_idx"]]))

        # lateral concept edges + thin galaxy edges
        for a, b, w in state.get("lateral_edges", []):
            try:
                graph.add_concept_relation(concept_ids[a], concept_ids[b], float(w), "proposed")
            except Exception:
                pass
        for a, b, w in state.get("galaxy_edges", []):
            try:
                graph.add_concept_relation(gal_ids[a], gal_ids[b], float(w), "proposed")
            except Exception:
                pass

        await session.commit()

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
            "galaxies": len(gal_ids),
            "constellations": len(con_ids),
            "concepts": len(concept_ids),
            "persisted": len(gal_ids) + len(con_ids) + len(concept_ids),
        },
    )
    return state
