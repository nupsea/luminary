"""FlashcardAuditService -- Bloom's taxonomy coverage analysis and gap fill (S153).

Analyzes the distribution of bloom_level values across sections for a document
and generates missing-level cards for under-covered sections.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, FlashcardModel, SectionModel
from app.services.flashcard import _parse_llm_response
from app.services.llm import get_llm_service
from app.types import BloomGap, BloomSectionStat, CoverageReport

logger = logging.getLogger(__name__)

# Level-specific prompt additions for gap fill (appended to TECH_FLASHCARD_SYSTEM base)
_BLOOM_LEVEL_INSTRUCTIONS: dict[int, str] = {
    2: (
        "Write an UNDERSTANDING question asking the learner to explain, summarise, "
        "or interpret this concept in their own words."
    ),
    3: ("Write an APPLICATION question asking how to USE this concept in a realistic scenario."),
    4: (
        "Write an ANALYSIS question asking the reader to COMPARE, CONTRAST, or EVALUATE "
        "different aspects of this concept."
    ),
    5: (
        "Write an EVALUATION question asking the reader to justify or critique a design decision "
        "related to this concept."
    ),
    6: (
        "Write a SYNTHESIS question asking the reader to design, construct, or propose "
        "something using this concept."
    ),
}

_AUDIT_FILL_SYSTEM = (
    "You are a learning assistant creating a single flashcard "
    "at a specified Bloom's Taxonomy level. "
    "Output a JSON array starting with [ and ending with ]. "
    'Each element: {"question": "...", "answer": "...", '
    '"source_excerpt": "...", "flashcard_type": "...", "bloom_level": N}. '
    "bloom_level is an integer 1-6 matching the level requested. "
    "flashcard_type must be one of: definition, syntax_recall, "
    "concept_explanation, analogy, code_completion, api_signature, "
    "trace, pattern_recognition, design_decision, complexity, implementation. "
    "Questions must be self-contained -- never use 'in this passage' or 'in this text'. "
    "Write no explanation, preamble, or markdown fences. "
    "Return exactly one card."
)


class FlashcardAuditService:
    """Analyze Bloom's taxonomy coverage and fill gaps for a document's flashcard deck."""

    async def analyze_coverage(self, document_id: str, db: AsyncSession) -> CoverageReport:
        """Return a CoverageReport for all flashcards belonging to document_id.

        Cards with null chunk_id (source='note', 'gap', 'feynman') are excluded
        from section analysis via the JOIN -- this is intentional; they have no
        section context. Cards with null bloom_level are counted in total_cards
        but excluded from by_bloom_level and gap computation.
        """
        # Count all cards for this document (including null bloom_level)
        all_cards_result = await db.execute(
            select(FlashcardModel.id, FlashcardModel.bloom_level).where(
                FlashcardModel.document_id == document_id
            )
        )
        all_rows = all_cards_result.all()
        total_cards = len(all_rows)

        # One JOIN query: flashcard -> chunk -> section (excludes null chunk_id naturally)
        stmt = (
            select(
                FlashcardModel.bloom_level,
                ChunkModel.section_id,
                SectionModel.heading,
            )
            .join(ChunkModel, FlashcardModel.chunk_id == ChunkModel.id)
            .join(SectionModel, ChunkModel.section_id == SectionModel.id)
            .where(FlashcardModel.document_id == document_id)
            .where(FlashcardModel.bloom_level.is_not(None))
        )
        result = await db.execute(stmt)
        rows = result.all()

        # Build per-section stats
        by_section: dict[str, BloomSectionStat] = {}
        global_by_level: dict[int, int] = {}

        for bloom_level, section_id, section_heading in rows:
            level = int(bloom_level)
            global_by_level[level] = global_by_level.get(level, 0) + 1

            if section_id not in by_section:
                by_section[section_id] = BloomSectionStat(
                    section_heading=section_heading,
                    by_bloom_level={},
                    has_level_3_plus=False,
                )
            stat = by_section[section_id]
            stat["by_bloom_level"][level] = stat["by_bloom_level"].get(level, 0) + 1
            if level >= 3:
                stat["has_level_3_plus"] = True

        # coverage_score = fraction of sections with >= 1 L3+ card
        # Guard against division by zero when no section has bloom-level data
        total_sections = len(by_section)
        sections_with_l3_plus = sum(1 for s in by_section.values() if s["has_level_3_plus"])
        coverage_score = 0.0 if total_sections == 0 else sections_with_l3_plus / total_sections

        # Gaps: sections missing any levels 1-6 AND lacking L3+ card
        # (only sections with zero L3+ cards are actionable)
        gaps: list[BloomGap] = []
        for section_id, stat in by_section.items():
            if stat["has_level_3_plus"]:
                continue
            present_levels = set(stat["by_bloom_level"].keys())
            missing = [lv for lv in range(1, 7) if lv not in present_levels]
            if missing:
                gaps.append(
                    BloomGap(
                        section_id=section_id,
                        section_heading=stat["section_heading"],
                        missing_bloom_levels=missing,
                    )
                )

        return CoverageReport(
            total_cards=total_cards,
            by_bloom_level=global_by_level,
            by_section=by_section,
            coverage_score=coverage_score,
            gaps=gaps,
        )

    async def fill_gaps(
        self,
        document_id: str,
        gaps: list[BloomGap],
        db: AsyncSession,
    ) -> int:
        """Generate missing-level flashcards for each gap section.

        For each gap section and each missing bloom level, calls the LLM with a
        level-specific prompt to generate one card at that level. LLM calls run
        concurrently (bounded by a semaphore of 3); DB writes are sequential to
        avoid AsyncSession concurrent-access violations.

        Returns the total number of cards created.
        """
        if not gaps:
            return 0

        # AsyncSession is NOT safe for concurrent access. Strategy: run LLM calls
        # concurrently (bounded by llm_sem), collect results, then write DB rows
        # sequentially. This matches the project pattern from MEMORY.md.
        llm_sem = asyncio.Semaphore(3)
        created_cards: list[FlashcardModel] = []

        # Each tuple: (section_id, level, cards_data)
        LLMResult = tuple[str, int, list[dict]]

        async def _llm_one(section_id: str, section_heading: str, level: int) -> LLMResult:
            instruction = _BLOOM_LEVEL_INSTRUCTIONS.get(level, "")
            prompt = (
                f"Section: {section_heading}\n\n"
                f"Target Bloom's level: {level}\n\n"
                f"Instruction: {instruction}\n\n"
                "Generate exactly 1 flashcard as a JSON array."
            )
            system = _AUDIT_FILL_SYSTEM

            async with llm_sem:
                llm = get_llm_service()
                raw = await llm.generate(prompt, system=system, stream=False)

            cards_data = _parse_llm_response(raw, document_id)
            return (section_id, level, cards_data)

        tasks = []
        for gap in gaps:
            for level in gap["missing_bloom_levels"]:
                # Only generate for levels 2-6 (L1 recall cards usually already exist)
                if level < 2:
                    continue
                tasks.append(_llm_one(gap["section_id"], gap["section_heading"], level))

        if not tasks:
            return 0

        # Run all LLM calls concurrently, then write results to DB sequentially
        llm_results: list[LLMResult] = await asyncio.gather(*tasks)

        now = datetime.now(UTC)
        for section_id, level, cards_data in llm_results:
            # Look up first chunk for this section to assign chunk_id (sequential DB access)
            chunk_result = await db.execute(
                select(ChunkModel.id)
                .where(ChunkModel.document_id == document_id)
                .where(ChunkModel.section_id == section_id)
                .limit(1)
            )
            first_chunk_id = chunk_result.scalar_one_or_none()

            for item in cards_data:
                if not isinstance(item, dict):
                    continue
                question = str(item.get("question", "")).strip()
                answer = str(item.get("answer", "")).strip()
                if not question or not answer:
                    continue
                source_excerpt = str(item.get("source_excerpt", "")).strip()
                flashcard_type = str(item.get("flashcard_type", "concept_explanation")).strip()
                # Honour bloom_level from LLM but coerce to target level if absent/wrong
                raw_bloom = item.get("bloom_level")
                if isinstance(raw_bloom, (int, float)):
                    card_bloom = int(raw_bloom)
                elif isinstance(raw_bloom, str) and raw_bloom.isdigit():
                    card_bloom = int(raw_bloom)
                else:
                    card_bloom = level  # fallback to target level

                card = FlashcardModel(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    chunk_id=first_chunk_id,
                    source="audit",
                    deck="bloom_gap",
                    question=question,
                    answer=answer,
                    source_excerpt=source_excerpt,
                    difficulty="medium",
                    fsrs_state="new",
                    fsrs_stability=0.0,
                    fsrs_difficulty=0.0,
                    due_date=now,
                    reps=0,
                    lapses=0,
                    created_at=now,
                    flashcard_type=flashcard_type,
                    bloom_level=card_bloom,
                )
                db.add(card)
                created_cards.append(card)

        if created_cards:
            await db.commit()
            logger.info(
                "fill_gaps created %d cards for document %s",
                len(created_cards),
                document_id,
            )

        return len(created_cards)


_audit_service: FlashcardAuditService | None = None


def get_flashcard_audit_service() -> FlashcardAuditService:
    global _audit_service  # noqa: PLW0603
    if _audit_service is None:
        _audit_service = FlashcardAuditService()
    return _audit_service
