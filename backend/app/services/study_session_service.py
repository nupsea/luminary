"""Pure helpers for the /study router.

Extracted from ``app.routers.study``. Each function is pure -- no I/O,
no DB, no LLM. Inputs are explicit; outputs are Pydantic schemas defined
in ``app.schemas.study``.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from app.models import FlashcardModel
from app.schemas.study import (
    GapResult,
    SectionHeatmapItem,
    SessionPlanItem,
)


def compute_gaps(
    weak_cards: list[FlashcardModel],
    chunk_to_section: dict[str, str | None],
) -> list[GapResult]:
    """Group weak cards by section, compute avg stability, return sorted results."""
    groups: dict[str | None, list[FlashcardModel]] = {}
    for card in weak_cards:
        heading = chunk_to_section.get(card.chunk_id)
        groups.setdefault(heading, []).append(card)

    results: list[GapResult] = []
    for heading, group_cards in groups.items():
        avg_stab = sum(c.fsrs_stability for c in group_cards) / len(group_cards)
        sample = [c.question for c in group_cards[:3]]
        results.append(
            GapResult(
                section_heading=heading,
                weak_card_count=len(group_cards),
                avg_stability=round(avg_stab, 4),
                sample_questions=sample,
            )
        )

    results.sort(key=lambda r: r.avg_stability)
    return results


def compute_section_heatmap(
    cards: list[FlashcardModel],
    chunk_to_section: dict[str, str | None],
    now: datetime,
) -> dict[str, SectionHeatmapItem]:
    """Aggregate FSRS retrievability per section.

    fragility_score = 1 - avg_retrievability where retrievability = exp(-t/S).
    Sections with no cards are absent from the returned dict.
    """
    groups: dict[str, list[FlashcardModel]] = {}
    for card in cards:
        if not card.chunk_id:
            continue
        section_id = chunk_to_section.get(card.chunk_id)
        if section_id is None:
            continue
        groups.setdefault(section_id, []).append(card)

    result: dict[str, SectionHeatmapItem] = {}
    for section_id, group in groups.items():
        retrievabilities: list[float] = []
        for card in group:
            if card.fsrs_stability <= 0 or card.last_review is None:
                retrievabilities.append(0.0)
            else:
                last_review_aware = card.last_review.replace(tzinfo=UTC)
                days_since = (now - last_review_aware).total_seconds() / 86400
                retrievabilities.append(math.exp(-days_since / card.fsrs_stability))

        avg_ret = sum(retrievabilities) / len(retrievabilities)
        fragility = round(max(0.0, min(1.0, 1.0 - avg_ret)), 4)
        due_count = sum(
            1 for card in group if card.due_date and card.due_date.replace(tzinfo=UTC) <= now
        )
        result[section_id] = SectionHeatmapItem(
            section_id=section_id,
            fragility_score=fragility,
            due_card_count=due_count,
            avg_retention_pct=round(avg_ret * 100, 1),
        )
    return result


def build_session_plan(
    due_count: int,
    gap_areas: list[str],
    recent_doc_titles: list[tuple[str, str]],
    budget_minutes: int,
) -> list[SessionPlanItem]:
    """Assemble a prioritized study agenda from available data."""
    items: list[SessionPlanItem] = []

    if due_count > 0:
        items.append(
            SessionPlanItem(
                type="review",
                title=f"{due_count} flashcards due for review",
                minutes=min(10, max(5, due_count // 2)),
                action_label="Start Review",
                action_target="/study",
            )
        )

    for gap_area in gap_areas[:2]:
        items.append(
            SessionPlanItem(
                type="gap",
                title=f"Weak area: {gap_area}",
                minutes=5,
                action_label="Study Gaps",
                action_target="/study",
            )
        )

    if recent_doc_titles:
        doc_id, doc_title = recent_doc_titles[0]
        items.append(
            SessionPlanItem(
                type="read",
                title=f"Continue: {doc_title}",
                minutes=5,
                action_label="Open Document",
                action_target=f"/learning?document_id={doc_id}",
            )
        )

    return items[:5]
