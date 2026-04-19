"""StudyPathService: FSRS-aware study path computation.

Provides:
  - get_study_path(document_id, concept, db_session)
      Returns ordered path from earliest prerequisite to start concept,
      with FSRS-based skip decisions and mastery scores.
  - get_start_concepts(document_id, db_session)
      Returns up to 3 entry-point concepts with highest learning ROI.

Pure helper functions (no I/O) are module-level for testability.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, FlashcardModel
from app.services.graph import get_graph_service
from app.types import StartConceptItem, StartConceptsResponse, StudyPathItem, StudyPathResponse

logger = logging.getLogger(__name__)

_SKIP_STABILITY_THRESHOLD = 14.0  # days -- avg fsrs_stability >= this means "skip"
_MASTERY_FULL_STABILITY = 21.0  # days -- stability >= this = mastery 1.0


# ---------------------------------------------------------------------------
# Pure functions (no I/O, all inputs explicit)
# ---------------------------------------------------------------------------


def compute_mastery(stability_values: list[float]) -> float:
    """Return avg(stability / 21.0) capped at 1.0. 0.0 if empty."""
    if not stability_values:
        return 0.0
    avg = sum(stability_values) / len(stability_values)
    return min(1.0, avg / _MASTERY_FULL_STABILITY)


def should_skip(avg_stability_days: float, threshold: float = _SKIP_STABILITY_THRESHOLD) -> bool:
    """Return True when avg_stability_days >= threshold."""
    return avg_stability_days >= threshold


def build_skip_reason(avg_stability_days: float) -> str:
    """Format the reason string for a skip decision."""
    return f"avg_stability={avg_stability_days:.0f}d"


# ---------------------------------------------------------------------------
# StudyPathService
# ---------------------------------------------------------------------------


class StudyPathService:
    """Compute FSRS-aware study paths and entry-point suggestions."""

    async def get_study_path(
        self,
        document_id: str,
        concept: str,
        db_session: AsyncSession,
    ) -> StudyPathResponse:
        """Return FSRS-aware ordered study path for a concept in a document.

        Algorithm:
        1. Call KuzuService.get_learning_path(concept, document_id) to get topo-ordered nodes.
        2. For each node (prerequisite-first order):
           a. Find all flashcards in the document whose chunk text contains the concept name.
           b. Compute avg fsrs_stability across those flashcards.
           c. skip = avg_stability >= 14 days; mastery = avg(stability / 21.0) capped at 1.0.
        3. Return StudyPathResponse with path ordered from earliest unskipped prerequisite.

        Concept-to-flashcard linkage is approximate: uses ChunkModel.text.ilike(f"%{concept}%").
        """
        graph_svc = get_graph_service()
        lp = graph_svc.get_learning_path(concept, document_id)

        path_items: list[StudyPathItem] = []
        for node in lp.get("nodes", []):
            node_name: str = node.name if hasattr(node, "name") else node.get("name", "")  # type: ignore[union-attr]
            if not node_name:
                continue

            stabilities = await self._get_stabilities_for_concept(
                document_id, node_name, db_session
            )

            if stabilities:
                avg_stab = sum(stabilities) / len(stabilities)
                mastery = compute_mastery(stabilities)
                skip = should_skip(avg_stab)
                reason = build_skip_reason(avg_stab) if skip else f"avg_stability={avg_stab:.0f}d"
            else:
                avg_stab = 0.0
                mastery = 0.0
                skip = False
                reason = "no flashcards"

            path_items.append(
                StudyPathItem(
                    concept=node_name,
                    mastery=round(mastery, 3),
                    skip=skip,
                    reason=reason,
                    avg_stability_days=round(avg_stab, 1),
                )
            )

        return StudyPathResponse(
            concept=concept,
            document_id=document_id,
            path=path_items,
        )

    async def get_start_concepts(
        self,
        document_id: str,
        db_session: AsyncSession,
    ) -> StartConceptsResponse:
        """Return up to 3 entry-point concepts with highest learning ROI.

        Entry-point concepts: those with no outgoing PREREQUISITE_OF edges
        (no prerequisites themselves) that ARE referenced as prerequisites by others.

        Sort order: fewest unskipped dependencies first, then fewest existing flashcards
        (highest ROI for new learners).
        """
        graph_svc = get_graph_service()
        candidates = graph_svc.get_entry_point_concepts(document_id, limit=10)

        if not candidates:
            return StartConceptsResponse(document_id=document_id, concepts=[])

        items: list[StartConceptItem] = []
        for concept in candidates:
            # Count flashcards for this concept (approximate via text search)
            fc_count = await self._count_flashcards_for_concept(document_id, concept, db_session)

            # Prereq chain length = 0 for entry points (no prerequisites)
            # Rationale: they ARE the foundations; studying them has highest ROI
            plural = "s" if fc_count != 1 else ""
            rationale = f"0 prerequisites unskipped; {fc_count} flashcard{plural}"

            items.append(
                StartConceptItem(
                    concept=concept,
                    prereq_chain_length=0,
                    flashcard_count=fc_count,
                    rationale=rationale,
                )
            )

        # Sort: fewest flashcards first (highest ROI -- most to learn)
        items.sort(key=lambda x: x.flashcard_count)

        return StartConceptsResponse(
            document_id=document_id,
            concepts=items[:3],
        )

    async def _get_stabilities_for_concept(
        self,
        document_id: str,
        concept: str,
        db_session: AsyncSession,
    ) -> list[float]:
        """Return fsrs_stability values for flashcards related to a concept.

        Approximation: find chunks in this document whose text contains the concept name,
        then return stability of flashcards linked to those chunks.
        """
        try:
            # Find chunk IDs where text matches concept (case-insensitive)
            chunk_result = await db_session.execute(
                select(ChunkModel.id).where(
                    ChunkModel.document_id == document_id,
                    ChunkModel.text.ilike(f"%{concept}%"),
                )
            )
            chunk_ids = [row[0] for row in chunk_result]
            if not chunk_ids:
                return []

            # Get flashcard stabilities for those chunks
            fc_result = await db_session.execute(
                select(FlashcardModel.fsrs_stability).where(
                    FlashcardModel.chunk_id.in_(chunk_ids),
                    FlashcardModel.reps > 0,  # only cards that have been reviewed
                )
            )
            return [row[0] for row in fc_result if row[0] is not None]
        except Exception:
            logger.debug(
                "_get_stabilities_for_concept failed for concept=%r doc=%s",
                concept,
                document_id,
                exc_info=True,
            )
            return []

    async def _count_flashcards_for_concept(
        self,
        document_id: str,
        concept: str,
        db_session: AsyncSession,
    ) -> int:
        """Return count of flashcards related to a concept in a document."""
        try:
            chunk_result = await db_session.execute(
                select(ChunkModel.id).where(
                    ChunkModel.document_id == document_id,
                    ChunkModel.text.ilike(f"%{concept}%"),
                )
            )
            chunk_ids = [row[0] for row in chunk_result]
            if not chunk_ids:
                return 0

            count_result = await db_session.execute(
                select(func.count())
                .select_from(FlashcardModel)
                .where(FlashcardModel.chunk_id.in_(chunk_ids))
            )
            return count_result.scalar_one()
        except Exception:
            logger.debug(
                "_count_flashcards_for_concept failed for concept=%r doc=%s",
                concept,
                document_id,
                exc_info=True,
            )
            return 0
