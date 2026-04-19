"""MasteryService: aggregates FSRS flashcard stability into concept-level mastery scores.

Mastery formula for concept C across document_ids:
  1. Find all ChunkModel rows where chunk.text contains C (case-insensitive LIKE).
  2. For each chunk, find FlashcardModel rows (two-hop: chunk_id -> ChunkModel.id -> section_id).
  3. Per card:
       weight = 1.5 if bloom_level in (4, 5) else 1.0
       capped_stability = min(fsrs_stability / 21.0, 1.0)
       contribution = capped_stability * weight
  4. weighted_mean = sum(contribution) / sum(weight)  (0.0 when no cards)
  5. prediction_errors = count PredictionEventModel rows where correct=False
       and chunk_id in (chunks containing C) and document_id in doc_ids
     penalty = min(error_count * 0.05, 0.20)
  6. mastery = max(0.0, weighted_mean - penalty)

Cross-book: SAME_CONCEPT clusters from S141 unify mastery across documents.

Performance guard: concept list capped at _MAX_CONCEPTS (100) per document call;
LIKE scan on ChunkModel.text is full-table -- acceptable for single-user local app.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, FlashcardModel, PredictionEventModel, SectionModel
from app.services.graph import get_graph_service
from app.types import ConceptMastery, HeatmapCell, MasteryHeatmapResponse

logger = logging.getLogger(__name__)

_MAX_CONCEPTS = 100  # per document; cap LIKE scans
_MAX_HEATMAP_SECTIONS = 20
_MAX_HEATMAP_CONCEPTS = 20
_MASTERY_FULL_DAYS = 21.0  # stability at which mastery = 1.0
_PREDICTION_PENALTY = 0.05
_MAX_PENALTY = 0.20
_BLOOM_HIGH_WEIGHT = 1.5  # weight for bloom_level 4 or 5
_BLOOM_DEFAULT_WEIGHT = 1.0
_DUE_SOON_DAYS = 3


class MasteryService:
    """Compute concept-level mastery from FSRS flashcard stability and prediction errors."""

    def _compute_weighted_mastery(self, cards: Sequence[FlashcardModel]) -> float:
        """Pure function: weighted mean mastery from flashcard list.

        Returns 0.0 when cards is empty.
        """
        if not cards:
            return 0.0
        total_weight = 0.0
        total_contribution = 0.0
        for card in cards:
            weight = (
                _BLOOM_HIGH_WEIGHT
                if card.bloom_level is not None and card.bloom_level >= 4
                else _BLOOM_DEFAULT_WEIGHT
            )
            capped = min(card.fsrs_stability / _MASTERY_FULL_DAYS, 1.0)
            total_contribution += capped * weight
            total_weight += weight
        return total_contribution / total_weight

    async def _get_chunk_ids_for_concept(
        self,
        concept_name: str,
        document_ids: list[str],
        session: AsyncSession,
    ) -> list[str]:
        """Return chunk IDs where chunk.text contains concept_name (case-insensitive).

        Scoped to document_ids. Returns [] when no matches found.
        """
        if not document_ids or not concept_name:
            return []
        pattern = f"%{concept_name.lower()}%"
        result = await session.execute(
            select(ChunkModel.id).where(
                ChunkModel.document_id.in_(document_ids),
                func.lower(ChunkModel.text).like(pattern),
            )
        )
        return list(result.scalars().all())

    async def _get_flashcards_for_chunks(
        self,
        chunk_ids: list[str],
        session: AsyncSession,
    ) -> list[FlashcardModel]:
        """Return flashcards whose chunk_id is in chunk_ids."""
        if not chunk_ids:
            return []
        result = await session.execute(
            select(FlashcardModel).where(FlashcardModel.chunk_id.in_(chunk_ids))
        )
        return list(result.scalars().all())

    async def _get_prediction_error_count(
        self,
        chunk_ids: list[str],
        session: AsyncSession,
    ) -> int:
        """Return count of PredictionEventModel rows with correct=False for these chunks."""
        if not chunk_ids:
            return 0
        result = await session.execute(
            select(func.count()).where(
                PredictionEventModel.chunk_id.in_(chunk_ids),
                PredictionEventModel.correct.is_(False),
            )
        )
        return result.scalar_one() or 0

    async def _due_soon_count(
        self,
        chunk_ids: list[str],
        session: AsyncSession,
    ) -> int:
        """Count flashcards due within the next _DUE_SOON_DAYS days."""
        if not chunk_ids:
            return 0
        cutoff = datetime.now(UTC) + timedelta(days=_DUE_SOON_DAYS)
        result = await session.execute(
            select(func.count()).where(
                FlashcardModel.chunk_id.in_(chunk_ids),
                FlashcardModel.due_date <= cutoff,
            )
        )
        return result.scalar_one() or 0

    async def compute_mastery(
        self,
        concept_name: str,
        document_ids: list[str],
        session: AsyncSession,
    ) -> ConceptMastery:
        """Compute mastery for concept_name across document_ids.

        Also checks SAME_CONCEPT clusters (S141) so cross-book variants contribute.
        Returns ConceptMastery with no_flashcards=True when no cards exist.
        """
        # Resolve cross-book cluster: expand document_ids to include cluster partners
        all_doc_ids = list(document_ids)
        cluster_concept = concept_name
        try:
            graph = get_graph_service()
            clusters = graph.get_concept_clusters()
            for cluster in clusters:
                names = []
                for eid in cluster["entity_ids"]:
                    row = graph._conn.execute(
                        "MATCH (e:Entity {id: $eid}) RETURN e.name",
                        {"eid": eid},
                    )
                    if row.has_next():
                        name = row.get_next()[0]
                        if name:
                            names.append(name)
                if concept_name.lower() in [n.lower() for n in names if n]:
                    all_doc_ids = list(set(all_doc_ids + cluster["document_ids"]))
                    # Use the canonical name from the cluster (longest form)
                    cluster_concept = cluster["concept_name"] or concept_name
                    break
        except Exception:
            logger.debug(
                "compute_mastery: cluster resolution failed for %r, using local only",
                concept_name,
                exc_info=True,
            )

        chunk_ids = await self._get_chunk_ids_for_concept(cluster_concept, all_doc_ids, session)
        cards = await self._get_flashcards_for_chunks(chunk_ids, session)
        weighted_mean = self._compute_weighted_mastery(cards)
        error_count = await self._get_prediction_error_count(chunk_ids, session)
        penalty = min(error_count * _PREDICTION_PENALTY, _MAX_PENALTY)
        mastery = max(0.0, weighted_mean - penalty)
        due_soon = await self._due_soon_count(chunk_ids, session)

        return ConceptMastery(
            concept=concept_name,
            mastery=mastery,
            card_count=len(cards),
            due_soon=due_soon,
            no_flashcards=len(cards) == 0,
            document_ids=list(document_ids),
        )

    async def get_all_concept_masteries(
        self,
        document_ids: list[str],
        session: AsyncSession,
    ) -> list[ConceptMastery]:
        """Return ConceptMastery for all Kuzu entities in the given documents.

        Sorted by mastery ascending (weakest first). Capped at _MAX_CONCEPTS.
        """
        try:
            graph = get_graph_service()
        except Exception:
            logger.warning("get_all_concept_masteries: graph service unavailable")
            return []

        all_concepts: set[str] = set()
        for doc_id in document_ids:
            by_type = graph.get_entities_by_type_for_document(doc_id)
            for names in by_type.values():
                all_concepts.update(names)

        # Deduplicate via SAME_CONCEPT clusters: keep canonical name per cluster
        clusters = graph.get_concept_clusters()
        cluster_members: set[str] = set()
        canonical_map: dict[str, str] = {}  # member -> canonical
        for cluster in clusters:
            canonical = cluster["concept_name"]
            try:
                members = []
                for eid in cluster["entity_ids"]:
                    row = graph._conn.execute(
                        "MATCH (e:Entity {id: $eid}) RETURN e.name", {"eid": eid}
                    )
                    if row.has_next():
                        name = row.get_next()[0]
                        if name:
                            members.append(name)
            except Exception:
                members = []
            for m in members:
                cluster_members.add(m)
                canonical_map[m] = canonical

        deduplicated: set[str] = set()
        for c in all_concepts:
            deduplicated.add(canonical_map.get(c, c))

        concepts_list = list(deduplicated)[:_MAX_CONCEPTS]

        # Compute mastery sequentially: AsyncSession is not safe for concurrent use.
        # SQLAlchemy docs: "AsyncSession is not safe for use in concurrent tasks."
        # Using gather with semaphore(1) keeps the code structure but forces serial execution.
        sem = asyncio.Semaphore(1)

        async def _compute(concept: str) -> ConceptMastery:
            async with sem:
                return await self.compute_mastery(concept, document_ids, session)

        results = await asyncio.gather(*[_compute(c) for c in concepts_list])
        return sorted(results, key=lambda cm: cm.mastery)

    async def get_heatmap(
        self,
        document_id: str,
        session: AsyncSession,
    ) -> MasteryHeatmapResponse:
        """Build a chapter x concept mastery grid for a single document.

        Capped at _MAX_HEATMAP_SECTIONS sections and _MAX_HEATMAP_CONCEPTS concepts.
        Sparse: most cells will be (mastery=None, card_count=0) meaning no flashcards.
        """
        # Fetch sections (ordered, capped)
        sections_result = await session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .order_by(SectionModel.section_order)
            .limit(_MAX_HEATMAP_SECTIONS)
        )
        sections = list(sections_result.scalars().all())
        chapter_names = [s.heading for s in sections]
        section_ids = [s.id for s in sections]

        if not sections:
            return MasteryHeatmapResponse(
                document_id=document_id,
                chapters=[],
                concepts=[],
                cells=[],
            )

        # Fetch top concepts for this document from Kuzu
        try:
            graph = get_graph_service()
            by_type = graph.get_entities_by_type_for_document(document_id)
        except Exception:
            by_type = {}

        all_entity_names: list[str] = []
        for names in by_type.values():
            all_entity_names.extend(names)
        # Cap concepts for the heatmap
        concept_names = list(dict.fromkeys(all_entity_names))[:_MAX_HEATMAP_CONCEPTS]

        if not concept_names:
            return MasteryHeatmapResponse(
                document_id=document_id,
                chapters=chapter_names,
                concepts=[],
                cells=[],
            )

        # For each section, get its chunk IDs
        section_chunk_ids: dict[str, list[str]] = {}
        for sid in section_ids:
            result = await session.execute(
                select(ChunkModel.id).where(
                    ChunkModel.document_id == document_id,
                    ChunkModel.section_id == sid,
                )
            )
            section_chunk_ids[sid] = list(result.scalars().all())

        # Build heatmap cells: (chapter, concept) pairs
        cells: list[HeatmapCell] = []
        for section in sections:
            s_chunk_ids = section_chunk_ids.get(section.id, [])
            for concept in concept_names:
                # Find chunk IDs for this section that mention the concept
                if s_chunk_ids:
                    pattern = f"%{concept.lower()}%"
                    result = await session.execute(
                        select(ChunkModel.id).where(
                            ChunkModel.id.in_(s_chunk_ids),
                            func.lower(ChunkModel.text).like(pattern),
                        )
                    )
                    matching_chunk_ids = list(result.scalars().all())
                else:
                    matching_chunk_ids = []

                cards = await self._get_flashcards_for_chunks(matching_chunk_ids, session)
                if not cards:
                    mastery_val: float | None = None
                    card_count = 0
                else:
                    error_count = await self._get_prediction_error_count(
                        matching_chunk_ids, session
                    )
                    penalty = min(error_count * _PREDICTION_PENALTY, _MAX_PENALTY)
                    mastery_val = max(0.0, self._compute_weighted_mastery(cards) - penalty)
                    card_count = len(cards)

                cells.append(
                    HeatmapCell(
                        chapter=section.heading,
                        concept=concept,
                        mastery=mastery_val,
                        card_count=card_count,
                    )
                )

        return MasteryHeatmapResponse(
            document_id=document_id,
            chapters=chapter_names,
            concepts=concept_names,
            cells=cells,
        )


@lru_cache
def get_mastery_service() -> MasteryService:
    return MasteryService()
