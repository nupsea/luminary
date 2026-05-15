"""PrereqExtractorService: LLM-based prerequisite pair extraction from section summaries.

Registered as enrichment job_type='prerequisites'.
Reads SectionSummaryModel rows for a document, calls LLM per section,
writes PREREQUISITE_OF edges to Kuzu via add_prerequisite_with_section().
Sets SectionModel.difficulty_estimate = prerequisite chain depth.
"""

import json
import logging
import re

from sqlalchemy import select, update

from app.database import get_session_factory
from app.models import SectionModel, SectionSummaryModel
from app.services.graph import get_graph_service
from app.services.llm import LLMUnavailableError, get_llm_service

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a technical curriculum analyst."
    " For the provided section summary, list concepts this section requires"
    " the reader to already understand."
    " Be specific. Use the exact concept names from the text."
    " Output a JSON array only, no prose:"
    ' [{"requires": "concept name", "required_by": "concept name", "confidence": 0.0}].'
    " Only include prerequisites with confidence >= 0.7."
    " Return [] if no prerequisites apply."
)

_CONFIDENCE_THRESHOLD = 0.7


def _strip_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences from an LLM response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    return cleaned


def _parse_prereqs(raw_text: str) -> list[dict]:
    """Parse a JSON array of prerequisite pairs from LLM output.

    Pure function -- no I/O.
    Returns list of valid dicts with requires, required_by, confidence.
    Filters out entries below _CONFIDENCE_THRESHOLD.
    Returns [] on any parse failure.
    """
    cleaned = _strip_fences(raw_text)
    # Find first [...] block in case there is extra prose
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        parsed = json.loads(cleaned)
        if not isinstance(parsed, list):
            return []
        result = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            requires = item.get("requires")
            required_by = item.get("required_by")
            confidence = item.get("confidence", 0.0)
            if requires and required_by and float(confidence) >= _CONFIDENCE_THRESHOLD:
                result.append(
                    {
                        "requires": str(requires),
                        "required_by": str(required_by),
                        "confidence": float(confidence),
                    }
                )
        return result
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.debug("_parse_prereqs: JSON parse failed for raw=%s", raw_text[:200])
        return []


class PrereqExtractorService:
    """Extract prerequisite relationships from section summaries and write to Kuzu."""

    async def extract(self, section_content: str, section_id: str, document_id: str) -> list[dict]:
        """Call the LLM to extract prerequisite pairs from a section summary.

        Returns list of {requires, required_by, confidence} dicts with confidence >= 0.7.
        Returns [] on parse failure (non-fatal).
        Raises LLMUnavailableError when the LLM is unreachable (propagates to worker).
        """
        user_prompt = (
            f"Section summary:\n{section_content[:2000]}\n\n"
            "List all concepts this section requires the reader to already understand."
        )
        raw = await get_llm_service().complete(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            background=True,
        )
        return _parse_prereqs(raw)

    async def enrich(self, document_id: str) -> int:
        """Generate PREREQUISITE_OF edges for all SectionSummaryModel rows of a document.

        Returns count of edges written.
        Raises LLMUnavailableError (propagates to worker to mark job failed).
        """
        async with get_session_factory()() as session:
            summaries_result = await session.execute(
                select(SectionSummaryModel).where(SectionSummaryModel.document_id == document_id)
            )
            summaries = list(summaries_result.scalars().all())

        if not summaries:
            logger.info("prereq_extractor: no section summaries for doc=%s, skipping", document_id)
            return 0

        graph_svc = get_graph_service()
        total_edges = 0

        # Track (dependent_id, prereq_id) -> section_id for difficulty computation
        section_entity_map: dict[str, list[tuple[str, str]]] = {}

        for summary in summaries:
            try:
                pairs = await self.extract(summary.content, summary.section_id or "", document_id)
            except LLMUnavailableError:
                raise
            except Exception as exc:
                logger.warning(
                    "prereq_extractor: extraction failed for section_id=%s: %s",
                    summary.section_id,
                    exc,
                )
                continue

            for pair in pairs:
                requires_name = pair["requires"]
                required_by_name = pair["required_by"]
                confidence = pair["confidence"]

                # Resolve concept names to Entity IDs
                requires_id = graph_svc.match_entity_by_name(requires_name, document_id)
                required_by_id = graph_svc.match_entity_by_name(required_by_name, document_id)

                if requires_id is None or required_by_id is None:
                    logger.debug(
                        "prereq_extractor: could not resolve entity for pair"
                        " requires=%r required_by=%r in doc=%s",
                        requires_name,
                        required_by_name,
                        document_id,
                    )
                    continue

                graph_svc.add_prerequisite_with_section(
                    dependent_id=required_by_id,
                    prerequisite_id=requires_id,
                    document_id=document_id,
                    confidence=confidence,
                    source_section_id=summary.section_id or "",
                )
                total_edges += 1

                # Track for difficulty computation: section -> dependent entity
                if summary.section_id:
                    section_entity_map.setdefault(summary.section_id, []).append(
                        (required_by_id, requires_id)
                    )

        if total_edges > 0 and section_entity_map:
            await self._compute_and_store_difficulty(document_id, section_entity_map)

        logger.info("prereq_extractor: wrote %d edges for doc=%s", total_edges, document_id)
        return total_edges

    async def _compute_and_store_difficulty(
        self,
        document_id: str,
        section_entity_map: dict[str, list[tuple[str, str]]],
    ) -> None:
        """Compute prereq chain depth per section; store in SectionModel.difficulty_estimate.

        Chain depth (per entity) = number of hops from that entity back to a root concept.
        Root = a concept that is only a prerequisite for others but has no prerequisites itself.
        For each section, difficulty_estimate = max chain depth across all entities
        appearing in that section's extracted prerequisite pairs.
        """
        graph_svc = get_graph_service()
        edges = graph_svc.get_prerequisite_edges_for_document(document_id)
        if not edges:
            return

        # Build adjacency: dependent -> list of prerequisites
        adj: dict[str, list[str]] = {}
        all_nodes: set[str] = set()
        for e in edges:
            from_id = e["from_id"]
            to_id = e["to_id"]
            adj.setdefault(from_id, []).append(to_id)
            all_nodes.add(from_id)
            all_nodes.add(to_id)

        # Chain depth per entity: BFS from roots (no outgoing prereq edges) in reverse
        has_prereqs = set(adj.keys())
        roots = all_nodes - has_prereqs
        depth_map: dict[str, int] = {n: 0 for n in roots}

        reverse_adj: dict[str, list[str]] = {}
        for from_id, neighbors in adj.items():
            for to_id in neighbors:
                reverse_adj.setdefault(to_id, []).append(from_id)

        from collections import deque  # noqa: PLC0415

        queue: deque[str] = deque(roots)
        while queue:
            current = queue.popleft()
            current_depth = depth_map[current]
            for dependent in reverse_adj.get(current, []):
                new_depth = current_depth + 1
                if new_depth > depth_map.get(dependent, 0):
                    depth_map[dependent] = new_depth
                    queue.append(dependent)

        # section_id -> max chain depth of any dependent entity in that section
        section_depths: dict[str, int] = {}
        for section_id, entity_pairs in section_entity_map.items():
            max_depth = 0
            for dep_id, _req_id in entity_pairs:
                d = depth_map.get(dep_id, 0)
                max_depth = max(max_depth, d)
            if max_depth > 0:
                section_depths[section_id] = max_depth

        if not section_depths:
            return

        # Clamp to 1-5 range and store
        for sid, depth in section_depths.items():
            clamped = max(1, min(5, depth + 1))
            async with get_session_factory()() as db_session:
                await db_session.execute(
                    update(SectionModel)
                    .where(SectionModel.id == sid)
                    .values(difficulty_estimate=clamped)
                )
                await db_session.commit()

        logger.debug(
            "prereq_extractor: updated difficulty_estimate for %d sections in doc=%s",
            len(section_depths),
            document_id,
        )


async def prereq_extract_handler(document_id: str, job_id: str) -> None:
    """Enrichment handler for job_type='prerequisites'.

    Called by EnrichmentQueueWorker for each prerequisites job.
    Delegates to PrereqExtractorService.enrich().
    LLMUnavailableError propagates to mark job 'failed'.
    """
    logger.info("prereq_extract_handler: starting doc=%s job=%s", document_id, job_id)
    svc = PrereqExtractorService()
    count = await svc.enrich(document_id)
    logger.info("prereq_extract_handler: done doc=%s edges=%d", document_id, count)
