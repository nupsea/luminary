"""DeckHealthService -- deck health analysis and one-click remediation (S160).

Identifies orphaned cards (source section deleted), mastered cards (stability > 180 days),
stale cards (not reviewed in 90+ days with low stability), uncovered sections (no cards),
and hotspot sections (>= 15 cards). Provides archive_mastered and generate_for_uncovered
remediation methods.
"""

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, FlashcardModel, SectionModel
from app.types import DeckHealthReport, HealthSection

logger = logging.getLogger(__name__)

_MASTERED_STABILITY_DAYS = 180.0
_STALE_DAYS = 90
_STALE_MAX_STABILITY = 7.0
_HOTSPOT_MIN_CARDS = 15
_HOTSPOT_TOP_N = 5


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
        section_result = await db.execute(
            select(SectionModel.id, SectionModel.heading).where(
                SectionModel.document_id == document_id
            )
        )
        section_rows = section_result.all()
        valid_section_ids: set[str] = {row[0] for row in section_rows}
        section_heading_map: dict[str, str] = {row[0]: row[1] for row in section_rows}

        # 2. All non-archived cards for this document
        cards_result = await db.execute(
            select(
                FlashcardModel.id,
                FlashcardModel.fsrs_stability,
                FlashcardModel.last_review,
                FlashcardModel.chunk_id,
            ).where(
                FlashcardModel.document_id == document_id,
                FlashcardModel.fsrs_state != "archived",
            )
        )
        cards = cards_result.all()

        # 3. JOIN: card -> chunk -> section (excludes null chunk_id naturally)
        join_result = await db.execute(
            select(FlashcardModel.id, ChunkModel.section_id)
            .join(ChunkModel, FlashcardModel.chunk_id == ChunkModel.id)
            .where(FlashcardModel.document_id == document_id)
            .where(FlashcardModel.fsrs_state != "archived")
        )
        join_rows = join_result.all()

        # Build a map: card_id -> section_id (from join; only cards with chunk_id)
        card_to_section: dict[str, str | None] = {}
        section_card_counts: Counter[str] = Counter()
        covered_section_ids: set[str] = set()

        for card_id, section_id in join_rows:
            card_to_section[card_id] = section_id
            if section_id is not None:
                section_card_counts[section_id] += 1
                covered_section_ids.add(section_id)

        # 4. Classify each card
        orphaned_ids: list[str] = []
        mastered_ids: list[str] = []
        stale_ids: list[str] = []

        stale_threshold = now - timedelta(days=_STALE_DAYS)

        for card_id, stability, last_review, chunk_id in cards:
            # Orphaned: has a chunk_id AND that chunk's section_id is not in valid sections
            if card_id in card_to_section:
                s_id = card_to_section[card_id]
                if s_id is not None and s_id not in valid_section_ids:
                    orphaned_ids.append(card_id)

            # Mastered: stability > 180 days
            if stability is not None and stability > _MASTERED_STABILITY_DAYS:
                mastered_ids.append(card_id)

            # Stale: last_review not null AND > 90 days ago AND stability < 7
            # SQLite may return naive datetimes; normalise to UTC-aware for comparison.
            if last_review is not None and stability is not None:
                lr_aware = (
                    last_review.replace(tzinfo=UTC) if last_review.tzinfo is None else last_review
                )
                if lr_aware < stale_threshold and stability < _STALE_MAX_STABILITY:
                    stale_ids.append(card_id)

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
        cards_result = await db.execute(
            select(FlashcardModel).where(
                FlashcardModel.document_id == document_id,
                FlashcardModel.fsrs_stability > _MASTERED_STABILITY_DAYS,
                FlashcardModel.fsrs_state != "archived",
            )
        )
        cards = list(cards_result.scalars().all())

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
            # Fetch section heading
            section_result = await db.execute(
                select(SectionModel.heading).where(SectionModel.id == section_id)
            )
            heading = section_result.scalar_one_or_none()
            if heading is None:
                logger.warning(
                    "generate_for_uncovered: section %s not found, skipping",
                    section_id,
                )
                continue

            try:
                cards = await svc.generate(
                    document_id=document_id,
                    scope="section",
                    section_heading=heading,
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
