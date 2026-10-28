"""DeckHealthService -- deck health analysis and one-click remediation

Identifies orphaned cards (source section deleted), mastered cards (stability > 180 days),
stale cards (not reviewed in 90+ days with low stability), uncovered sections (no cards),
and hotspot sections (>= 15 cards). Provides archive_mastered and generate_for_uncovered
remediation methods.
"""

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FlashcardModel
from app.repos.deck_stats_repo import DeckStatsRepo
from app.repos.document_repo import DocumentRepo
from app.types import DeckHealthReport, HealthSection

logger = logging.getLogger(__name__)

_MASTERED_STABILITY_DAYS = 180.0
_STALE_DAYS = 90
_STALE_MAX_STABILITY = 7.0
_HOTSPOT_MIN_CARDS = 15
_HOTSPOT_TOP_N = 5


def _is_mastered(card: FlashcardModel) -> bool:
    return card.fsrs_stability is not None and card.fsrs_stability > _MASTERED_STABILITY_DAYS


def _is_stale(card: FlashcardModel, threshold: datetime) -> bool:
    """Reviewed long ago and almost forgotten since."""
    if card.last_review is None or card.fsrs_stability is None:
        return False
    last = card.last_review if card.last_review.tzinfo else card.last_review.replace(tzinfo=UTC)
    return last < threshold and card.fsrs_stability < _STALE_MAX_STABILITY


class DeckHealthService:
    """Analyze flashcard deck health and perform one-click remediation."""

    async def analyze(self, document_id: str, db: AsyncSession) -> DeckHealthReport:
        """Return a DeckHealthReport for all non-archived flashcards for document_id.

        Orphaned: chunk_id is not null AND the chunk's section_id is not in the
        current SectionModel rows for this document (section was deleted after the card
        was generated).

        Mastered: fsrs_stability > 180 days (card is over-learned; safe to archive).

        Stale: last_review is not null AND (now - last_review) > 90 days AND
        fsrs_stability < 7 days (almost forgotten, never re-studied).

        Uncovered sections: SectionModel rows with no FlashcardModel linked via
        chunk -> section.

        Hotspot sections: top N sections by card count (>= 15 cards).
        """
        now = datetime.now(UTC)

        # 1. Valid section IDs for this document
        sections = await DocumentRepo(db).sections_for_document(document_id)
        valid_section_ids: set[str] = {s.id for s in sections}
        section_heading_map: dict[str, str] = {s.id: s.heading for s in sections}

        # 2. Non-archived cards with their chunk's section; None when there is no chunk
        rows = await DeckStatsRepo(db).with_section_ids(
            document_id=document_id, exclude_archived=True
        )
        stale_threshold = now - timedelta(days=_STALE_DAYS)
        section_card_counts: Counter[str] = Counter()
        orphaned_ids: list[str] = []
        mastered_ids: list[str] = []
        stale_ids: list[str] = []
        for card, section_id in rows:
            if section_id is not None:
                section_card_counts[section_id] += 1
                # Orphaned: its chunk's section is no longer one of the document's
                if section_id not in valid_section_ids:
                    orphaned_ids.append(card.id)
            if _is_mastered(card):
                mastered_ids.append(card.id)
            if _is_stale(card, stale_threshold):
                stale_ids.append(card.id)
        covered_section_ids = set(section_card_counts)

        # 5. Uncovered sections: sections with no cards
        uncovered_section_ids: list[str] = [
            sid for sid in valid_section_ids if sid not in covered_section_ids
        ]

        # 6. Hotspot sections: sections with >= 15 cards, sorted descending by count, top 5
        hotspot_sections: list[HealthSection] = [
            HealthSection(
                section_id=sid,
                section_heading=section_heading_map.get(sid, ""),
                card_count=count,
            )
            for sid, count in section_card_counts.most_common(_HOTSPOT_TOP_N)
            if count >= _HOTSPOT_MIN_CARDS
        ]

        return DeckHealthReport(
            orphaned=len(orphaned_ids),
            orphaned_ids=orphaned_ids,
            mastered=len(mastered_ids),
            mastered_ids=mastered_ids,
            stale=len(stale_ids),
            stale_ids=stale_ids,
            uncovered_sections=len(uncovered_section_ids),
            uncovered_section_ids=uncovered_section_ids,
            hotspot_sections=hotspot_sections,
        )

    async def archive_mastered(self, document_id: str, db: AsyncSession) -> int:
        """Set fsrs_state='archived' for all mastered cards (stability > 180) for document_id.

        Archived cards are excluded from the study queue but are NOT deleted; they
        remain in the DB for historical reference.

        Returns the count of archived cards.
        """
        cards = await DeckStatsRepo(db).live_with_stability_over(
            document_id, _MASTERED_STABILITY_DAYS
        )

        for card in cards:
            card.fsrs_state = "archived"

        if cards:
            await db.commit()
            logger.info(
                "archive_mastered archived %d cards for document %s",
                len(cards),
                document_id,
            )

        return len(cards)

    async def generate_for_uncovered(
        self,
        document_id: str,
        section_ids: list[str],
        db: AsyncSession,
    ) -> int:
        """Generate 3 flashcards for each uncovered section using FlashcardService.generate.

        Processes sections sequentially to avoid AsyncSession concurrent-access violations.
        Returns the total number of cards created.
        """
        from app.services.flashcard import get_flashcard_service  # noqa: PLC0415

        svc = get_flashcard_service()
        total_created = 0

        for section_id in section_ids:
            try:
                cards = await svc.generate(
                    document_id=document_id,
                    scope="section",
                    section_heading=None,
                    section_id=section_id,
                    count=3,
                    session=db,
                )
                total_created += len(cards)
                logger.debug(
                    "generate_for_uncovered created %d cards for section %s",
                    len(cards),
                    section_id,
                )
            except Exception:
                logger.exception(
                    "generate_for_uncovered failed for section %s, skipping",
                    section_id,
                )

        return total_created


_deck_health_service: DeckHealthService | None = None


def get_deck_health_service() -> DeckHealthService:
    global _deck_health_service  # noqa: PLW0603
    if _deck_health_service is None:
        _deck_health_service = DeckHealthService()
    return _deck_health_service
