"""Objective coverage tracking service

Marks LearningObjectiveModel rows covered based on average FSRS stability
of non-definition flashcards in the same section_id.

Coverage threshold: avg(fsrs_stability) >= 4.0 days. Lowered from the
original 10-day threshold (audit C, 2026-05) -- 10 days demanded
weeks of review cadence before the panel ticked, which made the
feature feel inert. 4 days is roughly "the learner has seen this
twice with success" and gives feedback within a normal study run.

Update is also now monotonic: only flips False -> True. The
auto-tracker never silently un-marks a covered objective, so it
respects manual toggles (PATCH /documents/{id}/objectives/{id})
and avoids "I marked it yesterday but today it's gone" thrash if
a learner has a bad-review day that drops the section average.
Untoggling is the user's job, via the manual checkbox.
"""

import logging
from collections import defaultdict

from app.database import get_session_factory
from app.repos.deck_stats_repo import DeckStatsRepo
from app.repos.document_repo import DocumentRepo

logger = logging.getLogger(__name__)

_COVERAGE_THRESHOLD = 4.0  # days


class ObjectiveTrackerService:
    """Compute and persist learning objective coverage for a document."""

    async def update_coverage(self, document_id: str) -> None:
        """Mark objectives covered when section avg stability >= 4 days.

        Opens its own session -- safe to call as a fire-and-forget background
        task after the request session has been committed.

        Cards with NULL flashcard_type are treated as non-definition (included).
        Cards without a valid chunk or section_id are excluded from the average.
        If a section has zero qualifying cards, its objectives stay uncovered.

        Monotonic: an already-covered objective is never reset to False
        here. Manual toggles via PATCH stay in force; only the learner
        can un-mark a goal.
        """
        async with get_session_factory()() as session:
            stability = await DeckStatsRepo(session).avg_stability_by_section(document_id)
            covered_section_ids = {
                sid for sid, avg in stability.items() if avg >= _COVERAGE_THRESHOLD
            }
            objs = await DocumentRepo(session).learning_objectives(document_id)

            if not objs:
                return

            changed = 0
            for obj in objs:
                # Monotonic: only promote False -> True. Never auto-revert.
                if not obj.covered and obj.section_id in covered_section_ids:
                    obj.covered = True
                    changed += 1

            if changed:
                await session.commit()
                logger.info(
                    "Updated objective coverage for document %s: %d changed",
                    document_id,
                    changed,
                )

    async def get_progress(self, document_id: str) -> dict:
        """Return a DocumentProgressResponse dict for a document.

        Returns zeros (not 404) when the document has no learning objectives.
        by_chapter is sorted by SectionModel.section_order.
        """
        async with get_session_factory()() as session:
            docs = DocumentRepo(session)
            objs = await docs.learning_objectives(document_id)

            if not objs:
                return {
                    "document_id": document_id,
                    "total_objectives": 0,
                    "covered_objectives": 0,
                    "progress_pct": 0.0,
                    "by_chapter": [],
                }

            section_ids = list({obj.section_id for obj in objs})

            sections = (await docs.sections_by_id(section_ids)).values()

            heading_by_id = {s.id: s.heading for s in sections}
            order_by_id = {s.id: s.section_order for s in sections}

            by_section: dict = defaultdict(list)
            for obj in objs:
                by_section[obj.section_id].append(obj)

            by_chapter = []
            for sec_id in sorted(section_ids, key=lambda sid: order_by_id.get(sid, 0)):
                sec_objs = by_section[sec_id]
                total = len(sec_objs)
                covered = sum(1 for o in sec_objs if o.covered)
                pct = (covered / total * 100.0) if total > 0 else 0.0
                by_chapter.append(
                    {
                        "section_id": sec_id,
                        "heading": heading_by_id.get(sec_id, ""),
                        "total_objectives": total,
                        "covered_objectives": covered,
                        "progress_pct": round(pct, 1),
                    }
                )

            total_all = len(objs)
            covered_all = sum(1 for o in objs if o.covered)
            progress_pct = (covered_all / total_all * 100.0) if total_all > 0 else 0.0

            return {
                "document_id": document_id,
                "total_objectives": total_all,
                "covered_objectives": covered_all,
                "progress_pct": round(progress_pct, 1),
                "by_chapter": by_chapter,
            }


_service: ObjectiveTrackerService | None = None


def get_objective_tracker_service() -> ObjectiveTrackerService:
    global _service
    if _service is None:
        _service = ObjectiveTrackerService()
    return _service
