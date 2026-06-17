"""Backfill Concepts from the existing Entity graph (one-time, idempotent).

Phase 0 of the Knowledge Universe redesign. Today the graph holds Entity (NER) nodes
and mastery is computed on the fly; this script promotes the graph's concepts into
first-class Concept rows so the two-lane model has something to route on.

For each canonical concept the current system would surface, it:
  1. Creates a Concept (origin=document, status=confirmed) across SQLite + Kuzu + LanceDB,
     with evidence + centroid derived from the chunks that mention it.
  2. Maps the concept's flashcards (legacy chunk.text LIKE match) to concept_id.
  3. Stores an initial mastery via the SAME legacy formula, so the number is preserved
     when the read path later switches to the stored scalar (I-19).
Finally, any existing flashcard still unmapped is marked mapping_status='unmapped'.

Idempotent: concepts are keyed by label (skip-if-exists); card mapping and mastery
are recomputed/overwritten, never duplicated. Safe to re-run.

Per I-1: a single AsyncSession (no gather with a shared session).
Per I-2: LanceDB centroid upserts run in asyncio.to_thread (inside create_concept).
Per I-3: Kuzu iteration is has_next-guarded in the graph repo.

CLI:
    cd backend && uv run python -m app.scripts.backfill_concepts
    cd backend && uv run python -m app.scripts.backfill_concepts --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import ChunkModel, FlashcardModel
from app.services.concept_service import get_concept_service
from app.services.graph import get_graph_service
from app.services.mastery_service import get_mastery_service

logger = logging.getLogger(__name__)

_EVIDENCE_PER_CONCEPT = 3
_QUOTE_LEN = 200


async def _build_canonical_map(graph) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """member entity name -> canonical concept name, from SAME_CONCEPT clusters."""
    canonical: dict[str, str] = {}
    for cluster in graph.get_concept_clusters():
        cname = cluster.get("concept_name") or ""
        for eid in cluster.get("entity_ids", []):
            try:
                res = graph._conn.execute(
                    "MATCH (e:Entity {id: $eid}) RETURN e.name", {"eid": eid}
                )
                if res.has_next():
                    name = res.get_next()[0]
                    if name:
                        canonical[name] = cname or name
            except Exception:
                logger.debug("canonical map: entity %s lookup failed", eid, exc_info=True)
    return canonical


async def _concept_to_docs(graph) -> dict[str, set[str]]:  # type: ignore[no-untyped-def]
    """canonical concept name -> set of document ids that mention it."""
    canonical = await _build_canonical_map(graph)
    out: dict[str, set[str]] = {}
    for doc_id in graph.get_all_document_ids():
        by_type = graph.get_entities_by_type_for_document(doc_id)
        for names in by_type.values():
            for name in names:
                key = canonical.get(name, name)
                out.setdefault(key, set()).add(doc_id)
    return out


async def backfill(session: AsyncSession, *, dry_run: bool = False) -> dict[str, int]:
    """Run the backfill. Returns counts {concepts_created, concepts_skipped, cards_mapped}."""
    graph = get_graph_service()
    concept_svc = get_concept_service()
    mastery_svc = get_mastery_service()

    concept_docs = await _concept_to_docs(graph)
    stats = {"concepts_created": 0, "concepts_skipped": 0, "cards_mapped": 0}

    for label, doc_set in concept_docs.items():
        if not label.strip():
            continue
        doc_ids = sorted(doc_set)

        # chunks + cards via the legacy mapping (same logic mastery used)
        chunk_ids = await mastery_svc._get_chunk_ids_for_concept(label, doc_ids, session)
        cards = await mastery_svc._get_flashcards_for_chunks(chunk_ids, session)

        existing = await concept_svc.get_by_label(session, label)
        if existing is not None:
            stats["concepts_skipped"] += 1
            concept = existing
        else:
            if dry_run:
                stats["concepts_created"] += 1
                continue
            evidence = await _evidence_for_chunks(session, chunk_ids[:_EVIDENCE_PER_CONCEPT])
            entity_ids = _resolve_entity_ids(graph, label, doc_ids)
            concept = await concept_svc.create_concept(
                session,
                label=label,
                kind="concept",
                origin="document",
                status="confirmed",
                evidence=evidence,
                document_ids=doc_ids,
                entity_ids=entity_ids,
            )
            stats["concepts_created"] += 1

        if dry_run:
            continue

        # map cards + store mastery (legacy formula -> stored scalar)
        for card in cards:
            if card.concept_id != concept.id:
                card.concept_id = concept.id
                card.mapping_status = "mapped"
                stats["cards_mapped"] += 1
        mastery, stability = _legacy_mastery(mastery_svc, cards)
        error_count = await mastery_svc._get_prediction_error_count(chunk_ids, session)
        penalty = min(error_count * 0.05, 0.20)
        last_reviewed = max((c.last_review for c in cards if c.last_review), default=None)
        await concept_svc.set_learning_state(
            session,
            concept.id,
            mastery=max(0.0, mastery - penalty) * 100.0,
            stability=stability,
            last_reviewed=last_reviewed,
        )

    if not dry_run:
        # every existing card that matched no concept is genuinely unmapped
        await session.execute(
            update(FlashcardModel)
            .where(FlashcardModel.concept_id.is_(None))
            .values(mapping_status="unmapped")
        )
        await session.commit()

    return stats


def _legacy_mastery(mastery_svc, cards) -> tuple[float, float]:  # type: ignore[no-untyped-def]
    """0..1 weighted mastery + mean stability, matching MasteryService."""
    if not cards:
        return 0.0, 0.0
    weighted = mastery_svc._compute_weighted_mastery(cards)
    stability = sum(c.fsrs_stability for c in cards) / len(cards)
    return weighted, stability


async def _evidence_for_chunks(session: AsyncSession, chunk_ids: list[str]) -> list[dict]:
    if not chunk_ids:
        return []
    rows = (
        await session.execute(
            select(ChunkModel.id, ChunkModel.document_id, ChunkModel.text).where(
                ChunkModel.id.in_(chunk_ids)
            )
        )
    ).all()
    return [
        {"document_id": r[1], "chunk_id": r[0], "quote": (r[2] or "")[:_QUOTE_LEN]}
        for r in rows
    ]


def _resolve_entity_ids(graph, label: str, doc_ids: list[str]) -> list[str]:  # type: ignore[no-untyped-def]
    ids: list[str] = []
    for did in doc_ids:
        try:
            eid = graph.match_entity_by_name(label, did)
            if eid:
                ids.append(eid)
        except Exception:
            logger.debug("entity id resolve failed for %r in %s", label, did, exc_info=True)
    return list(dict.fromkeys(ids))


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO)
    async with get_session_factory()() as session:
        stats = await backfill(session, dry_run=args.dry_run)
    logger.info("backfill_concepts done (dry_run=%s): %s", args.dry_run, stats)
    print(stats)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Concepts from the Entity graph.")
    parser.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
