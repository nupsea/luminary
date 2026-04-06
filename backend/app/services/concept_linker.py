"""ConceptLinkerService: cross-document SAME_CONCEPT edge creation with contradiction detection.

Registered as enrichment job_type='concept_link'.
Compares CONCEPT and ALGORITHM entities in the newly ingested document against all existing
CONCEPT and ALGORITHM entities across all other documents.

Matching rules (same as EntityDisambiguator):
  A. Exact stripped match (confidence=1.0)
  B. Substring containment -- longer wins (confidence=0.8)
  C. Token overlap >= 2 (confidence=0.6)

For each matched pair, runs a second LLM call to detect contradictions between the two
section summaries that most prominently mention each concept.

Contradiction prompt output JSON:
  {"has_contradiction": bool, "note": str, "prefer_source": "a" | "b"}

If has_contradiction=True, sets contradiction=True, contradiction_note, prefer_source on the edge.
"""

import json
import logging
import re

import litellm
from sqlalchemy import select, update

from app.database import get_session_factory
from app.models import ChunkModel, DocumentModel, SectionSummaryModel
from app.services.entity_disambiguator import _strip_honorifics
from app.services.graph import get_graph_service

logger = logging.getLogger(__name__)

# Entity types to compare across documents for cross-book concept linking
_LINKABLE_TYPES = frozenset({"CONCEPT", "ALGORITHM"})

# Maximum LLM contradiction calls per link_for_document run (cost guard)
_MAX_CONTRADICTION_CALLS = 10

_CONTRADICTION_SYSTEM = (
    "Do these two passages make contradictory claims about the same concept?"
    " If yes, describe the contradiction in one sentence and which is likely more current."
    " Output JSON only:"
    ' {"has_contradiction": bool, "note": str, "prefer_source": "a" or "b"}'
)


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def _parse_year(text: str) -> int | None:
    """Extract approximate publication year from document front matter.

    Searches for patterns: Copyright YYYY, Published YYYY, (c) YYYY, (C) YYYY,
    published in YYYY. Falls back to any 4-digit year 1900-2099 in the first
    500 characters.

    Pure function -- no I/O.
    Returns the first matched year as int, or None.
    """
    # Primary pattern: explicit publication markers
    primary = re.search(
        r"(?:Copyright|Published|published\s+in|\(c\)|\(C\))\s+(\d{4})",
        text,
    )
    if primary:
        year = int(primary.group(1))
        if 1900 <= year <= 2099:
            return year

    # Fallback: first 4-digit year in the opening 500 characters
    fallback = re.search(r"\b((?:19|20)\d{2})\b", text[:500])
    if fallback:
        return int(fallback.group(1))

    return None


def _compute_match_confidence(name_a: str, name_b: str) -> float | None:
    """Return match confidence between two concept names, or None if no match.

    Applies the same three-rule ordering as EntityDisambiguator:
      A. Exact stripped match    -> 1.0
      B. Substring containment   -> 0.8
      C. Token overlap >= 2      -> 0.6

    Pure function -- no I/O.
    """
    sa = _strip_honorifics(name_a)
    sb = _strip_honorifics(name_b)

    if not sa or not sb:
        return None

    # Rule A: exact match after stripping
    if sa == sb:
        return 1.0

    # Rule B: substring containment (longer wins)
    if sa in sb or sb in sa:
        return 0.8

    # Rule C: token overlap >= 2
    tokens_a = set(sa.split())
    tokens_b = set(sb.split())
    if len(tokens_a & tokens_b) >= 2:
        return 0.6

    return None


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ConceptLinkerService:
    """Cross-document concept linking with contradiction detection.

    Main public method: link_for_document(document_id, session) -> int
    Returns the number of SAME_CONCEPT edges created or updated.
    """

    async def _find_summary_for_concept(
        self, concept_name: str, document_id: str, session
    ) -> str | None:
        """Return the section summary content that most prominently mentions concept_name.

        Queries SectionSummaryModel rows for the given document and returns the content
        of whichever row contains the most case-insensitive occurrences of concept_name.
        Returns None if no section summaries exist.
        """
        result = await session.execute(
            select(SectionSummaryModel.content)
            .where(SectionSummaryModel.document_id == document_id)
        )
        rows = result.scalars().all()
        if not rows:
            return None

        name_lower = concept_name.lower()
        best_content = ""
        best_count = -1
        for content in rows:
            count = content.lower().count(name_lower)
            if count > best_count:
                best_count = count
                best_content = content

        return best_content if best_count >= 0 else None

    async def _detect_contradiction(
        self, concept_name: str, summary_a: str, summary_b: str
    ) -> dict:
        """Call the LLM to detect if two passages make contradictory claims.

        Returns a dict with keys: has_contradiction (bool), note (str), prefer_source (str).
        Returns safe defaults if LLM is unreachable or JSON parse fails.
        Raises litellm.ServiceUnavailableError (propagates to worker caller).
        """
        from app.services.settings_service import get_litellm_kwargs  # noqa: PLC0415

        user_prompt = (
            f'Concept: "{concept_name}"\n\n'
            f"Passage A:\n{summary_a[:600]}\n\n"
            f"Passage B:\n{summary_b[:600]}"
        )
        response = await litellm.acompletion(
            **get_litellm_kwargs(background=True),
            messages=[
                {"role": "system", "content": _CONTRADICTION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
        raw = response.choices[0].message.content or ""
        cleaned = _strip_json_fences(raw)
        # Find first JSON object in response
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)
        try:
            parsed = json.loads(cleaned)
            return {
                "has_contradiction": bool(parsed.get("has_contradiction", False)),
                "note": str(parsed.get("note", ""))[:500],
                "prefer_source": str(parsed.get("prefer_source", ""))[:1],
            }
        except (json.JSONDecodeError, ValueError):
            logger.debug(
                "_detect_contradiction: JSON parse failed for concept=%r raw=%r",
                concept_name, raw[:200],
            )
            return {"has_contradiction": False, "note": "", "prefer_source": ""}

    async def link_for_document(self, document_id: str, session) -> int:
        """Compare concept/algorithm entities in document_id against all other documents.

        Creates SAME_CONCEPT edges in Kuzu for matched concept pairs.
        Runs contradiction detection (capped at _MAX_CONTRADICTION_CALLS LLM calls).
        Also parses and stores DocumentModel.publication_year if not yet set.

        Returns the number of edges created.
        """
        graph_svc = get_graph_service()

        # 1. Get CONCEPT/ALGORITHM entities for this document
        source_by_type = graph_svc.get_entities_by_type_for_document(document_id)
        source_entities: list[dict] = []
        for etype in _LINKABLE_TYPES:
            for name in source_by_type.get(etype, []):
                source_entities.append({"name": name, "type": etype, "doc_id": document_id})

        if not source_entities:
            logger.info(
                "concept_linker: no CONCEPT/ALGORITHM entities for doc=%s, skipping",
                document_id,
            )
            return 0

        logger.info(
            "concept_linker: found %d linkable entities for doc=%s",
            len(source_entities),
            document_id,
        )

        # 2. Get all other documents
        result = await session.execute(
            select(DocumentModel.id).where(DocumentModel.id != document_id)
        )
        other_doc_ids = [row[0] for row in result.all()]

        if not other_doc_ids:
            logger.info("concept_linker: no other documents to compare, skipping")
            return 0

        # 3. Build pool of existing entities from other documents
        # {etype: [(name, doc_id)]}
        other_entities: list[dict] = []
        for other_doc_id in other_doc_ids:
            other_by_type = graph_svc.get_entities_by_type_for_document(other_doc_id)
            for etype in _LINKABLE_TYPES:
                for name in other_by_type.get(etype, []):
                    other_entities.append({"name": name, "type": etype, "doc_id": other_doc_id})

        if len(other_entities) > 500:
            logger.warning(
                "concept_linker: large entity pool (%d entities across %d other docs)."
                " Performance may be slow.",
                len(other_entities),
                len(other_doc_ids),
            )

        # 4. For each entity in source doc, find matches in other docs
        edges_created = 0
        contradiction_calls = 0

        # Need entity IDs to call add_same_concept_edge; query them from Kuzu
        source_entity_ids = self._get_entity_ids_for_doc(graph_svc, document_id)
        other_entity_ids: dict[str, dict[str, str]] = {}  # doc_id -> {name -> id}
        for other_doc_id in other_doc_ids:
            other_entity_ids[other_doc_id] = self._get_entity_ids_for_doc(
                graph_svc, other_doc_id
            )

        for src_ent in source_entities:
            src_name = src_ent["name"]
            src_type = src_ent["type"]
            src_id = source_entity_ids.get(src_name)
            if not src_id:
                continue

            for tgt_ent in other_entities:
                if tgt_ent["type"] != src_type:
                    continue
                tgt_name = tgt_ent["name"]
                tgt_doc_id = tgt_ent["doc_id"]
                tgt_id = other_entity_ids.get(tgt_doc_id, {}).get(tgt_name)
                if not tgt_id:
                    continue

                confidence = _compute_match_confidence(src_name, tgt_name)
                if confidence is None:
                    continue

                # Detect contradiction if summaries are available
                contradiction_data: dict = {
                    "has_contradiction": False,
                    "note": "",
                    "prefer_source": "",
                }
                if contradiction_calls < _MAX_CONTRADICTION_CALLS:
                    try:
                        summary_a = await self._find_summary_for_concept(
                            src_name, document_id, session
                        )
                        summary_b = await self._find_summary_for_concept(
                            tgt_name, tgt_doc_id, session
                        )
                        if summary_a and summary_b:
                            contradiction_calls += 1
                            contradiction_data = await self._detect_contradiction(
                                src_name, summary_a, summary_b
                            )
                    except litellm.ServiceUnavailableError:
                        logger.warning(
                            "concept_linker: LLM unavailable for contradiction detection"
                            " (concept=%r) -- skipping",
                            src_name,
                        )
                    except Exception:
                        logger.debug(
                            "concept_linker: contradiction detection failed for"
                            " concept=%r, continuing",
                            src_name,
                            exc_info=True,
                        )

                graph_svc.add_same_concept_edge(
                    entity_id_a=src_id,
                    entity_id_b=tgt_id,
                    source_doc_id=document_id,
                    target_doc_id=tgt_doc_id,
                    confidence=confidence,
                    contradiction=contradiction_data["has_contradiction"],
                    contradiction_note=contradiction_data["note"],
                    prefer_source=contradiction_data["prefer_source"],
                )
                edges_created += 1

        # 5. Parse and store publication_year for this document if not yet set
        try:
            doc_result = await session.execute(
                select(DocumentModel.publication_year, DocumentModel.id)
                .where(DocumentModel.id == document_id)
            )
            doc_row = doc_result.first()
            if doc_row and doc_row[0] is None:
                # Scan first chunk text for year patterns
                chunk_result = await session.execute(
                    select(ChunkModel.text)
                    .where(ChunkModel.document_id == document_id)
                    .order_by(ChunkModel.chunk_index)
                    .limit(3)
                )
                chunk_texts = chunk_result.scalars().all()
                combined = " ".join(chunk_texts)[:2000]
                year = _parse_year(combined)
                if year is not None:
                    await session.execute(
                        update(DocumentModel)
                        .where(DocumentModel.id == document_id)
                        .values(publication_year=year)
                    )
                    await session.commit()
                    logger.info(
                        "concept_linker: set publication_year=%d for doc=%s",
                        year,
                        document_id,
                    )
        except Exception:
            logger.debug("concept_linker: publication_year extraction failed", exc_info=True)

        logger.info(
            "concept_linker: link_for_document done doc=%s edges=%d contradiction_calls=%d",
            document_id,
            edges_created,
            contradiction_calls,
        )
        return edges_created

    def _get_entity_ids_for_doc(self, graph_svc, document_id: str) -> dict[str, str]:
        """Return {name -> entity_id} for CONCEPT/ALGORITHM entities in a document."""
        try:
            result = graph_svc._conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {id: $did})"
                " WHERE e.type IN ['CONCEPT', 'ALGORITHM']"
                " RETURN e.name, e.id",
                {"did": document_id},
            )
            mapping: dict[str, str] = {}
            while result.has_next():
                row = result.get_next()
                if row[0] and row[1]:
                    mapping[row[0]] = row[1]
            return mapping
        except Exception:
            logger.debug(
                "_get_entity_ids_for_doc failed for doc=%s", document_id, exc_info=True
            )
            return {}


async def concept_link_handler(document_id: str, job_id: str) -> None:
    """Enrichment handler for job_type='concept_link'.

    Called by EnrichmentQueueWorker for each concept_link job.
    Raises litellm.ServiceUnavailableError (propagates to mark job 'failed').
    """
    logger.info("concept_link_handler: starting doc=%s job=%s", document_id, job_id)
    svc = ConceptLinkerService()
    async with get_session_factory()() as session:
        count = await svc.link_for_document(document_id, session)
    logger.info("concept_link_handler: done doc=%s edges=%d", document_id, count)
