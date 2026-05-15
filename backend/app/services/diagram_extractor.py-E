"""DiagramExtractorService: extract typed Kuzu nodes and edges from diagram descriptions.

Phase 2 enrichment job type 'diagram_extract' runs after 'image_analyze' completes.
Reads ImageModel rows where image_type is a qualifying diagram type and description
is not null, calls the default LLM to extract JSON (nodes + edges), then writes
DiagramNode rows and diagram edges to Kuzu.

After extraction, attempts name-match linkage: each extracted node name is compared
case-insensitively against existing LIBRARY/TECHNOLOGY Entity names for the same
document. If a match is found, a DEPICTS edge is written.

Diagram-type routing:
  architecture_diagram -> COMPONENT nodes, CONNECTS_TO / STORES_IN edges
  sequence_diagram     -> ACTOR nodes, SENDS_TO edges (with message property)
  er_diagram           -> ENTITY_DM nodes, HAS_FIELD / REFERENCES_DM edges
  flowchart            -> STEP nodes, LEADS_TO edges (with condition property)

Offline degradation: ServiceUnavailableError propagates so the EnrichmentQueueWorker
marks the job 'failed'. All other per-image errors are caught and logged without
aborting the batch.
"""

import asyncio
import json
import logging

from sqlalchemy import select

from app.database import get_session_factory
from app.models import ImageModel
from app.services import graph as _graph_module  # indirect: get_graph_service is patched
from app.services.llm import LLMUnavailableError, get_llm_service

logger = logging.getLogger(__name__)

_QUALIFYING_TYPES: frozenset[str] = frozenset(
    {
        "architecture_diagram",
        "sequence_diagram",
        "er_diagram",
        "flowchart",
    }
)

# Semaphore: at most 3 concurrent LLM calls across all diagram extraction jobs
_EXTRACT_SEM = asyncio.Semaphore(3)

_PROMPTS: dict[str, str] = {
    "architecture_diagram": (
        "From this architecture diagram description, extract a JSON object with:\n"
        'nodes: list of {"name": string, "node_type": "COMPONENT"}\n'
        'edges: list of {"from": string, "to": string, "edge_type": string, "label": string}\n'
        "where edge_type is one of: CONNECTS_TO, STORES_IN\n"
        "Return only the JSON object, no explanation."
    ),
    "sequence_diagram": (
        "From this sequence diagram description, extract a JSON object with:\n"
        'nodes: list of {"name": string, "node_type": "ACTOR"}\n'
        "edges: list of "
        '{"from": string, "to": string, "edge_type": "SENDS_TO", "message": string}\n'
        "Return only the JSON object, no explanation."
    ),
    "er_diagram": (
        "From this ER diagram description, extract a JSON object with:\n"
        'nodes: list of {"name": string, "node_type": "ENTITY_DM"}\n'
        'edges: list of {"from": string, "to": string, "edge_type": string}\n'
        "where edge_type is one of: HAS_FIELD, REFERENCES_DM\n"
        "Return only the JSON object, no explanation."
    ),
    "flowchart": (
        "From this flowchart description, extract a JSON object with:\n"
        'nodes: list of {"name": string, "node_type": "STEP"}\n'
        "edges: list of "
        '{"from": string, "to": string, "edge_type": "LEADS_TO", "condition": string}\n'
        "Return only the JSON object, no explanation."
    ),
}


def _build_prompt(image_type: str, description: str) -> str:
    """Return a diagram-type-specific extraction prompt with the description appended.

    Pure function, no I/O.
    Raises KeyError if image_type is not in _PROMPTS (caller should pre-filter).
    """
    template = _PROMPTS[image_type]
    return f"{template}\n\nDiagram description:\n{description}"


def _parse_llm_response(raw: str) -> dict:
    """Parse JSON from an LLM response string.

    Strips optional markdown fences before JSON parsing.
    Returns {"nodes": [...], "edges": [...]} on success.
    Raises ValueError if the response is not valid JSON or not a dict.
    Pure function, no I/O.
    """
    text = raw.strip()
    # Strip leading ```json or ``` fence
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :].strip()
        # Strip trailing ```
        if text.endswith("```"):
            text = text[: text.rfind("```")].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")

    # Normalize to always have nodes and edges keys
    parsed.setdefault("nodes", [])
    parsed.setdefault("edges", [])
    return parsed


class DiagramExtractorService:
    """Extracts diagram nodes and edges from image descriptions and writes them to Kuzu."""

    async def extract(self, document_id: str) -> int:
        """Process all ImageModel rows with qualifying image_type and non-null description.

        Returns count of images for which Kuzu nodes were successfully written.
        Skips images with description=null (image_analyze has not yet run for them).
        Idempotent: DiagramNode id = f"{image_id}:{node_name.lower()}" so re-runs
        do not create duplicate nodes.
        """


        async with get_session_factory()() as session:
            result = await session.execute(
                select(ImageModel).where(
                    ImageModel.document_id == document_id,
                    ImageModel.image_type.in_(list(_QUALIFYING_TYPES)),
                    ImageModel.description.is_not(None),
                )
            )
            images = list(result.scalars().all())

        if not images:
            logger.info("diagram_extractor: no qualifying diagram images for doc=%s", document_id)
            return 0

        logger.info(
            "diagram_extractor: processing %d diagram images for doc=%s",
            len(images),
            document_id,
        )

        processed = 0
        for img in images:
            try:
                prompt = _build_prompt(img.image_type, img.description or "")
            except KeyError:
                logger.debug(
                    "diagram_extractor: image_type=%r not in _PROMPTS, skipping image_id=%s",
                    img.image_type,
                    img.id,
                )
                continue

            async with _EXTRACT_SEM:
                try:
                    raw = (
                        await get_llm_service().complete(
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.0,
                            background=True,
                        )
                    ).strip()
                except LLMUnavailableError:
                    logger.warning(
                        "diagram_extractor: LLM unavailable for image_id=%s "
                        "-- Ollama is unreachable, start with: ollama serve",
                        img.id,
                    )
                    raise
                except Exception as exc:
                    logger.warning(
                        "diagram_extractor: LLM call failed for image_id=%s: %s", img.id, exc
                    )
                    continue

            try:
                parsed = _parse_llm_response(raw)
            except ValueError as exc:
                logger.warning(
                    "diagram_extractor: JSON parse failed for image_id=%s: %s", img.id, exc
                )
                continue

            nodes = parsed.get("nodes", [])
            edges = parsed.get("edges", [])
            if not isinstance(nodes, list):
                nodes = []
            if not isinstance(edges, list):
                edges = []

            try:
                await self._write_to_kuzu(
                    document_id=document_id,
                    image_id=img.id,
                    image_type=img.image_type,
                    nodes=nodes,
                    edges=edges,
                )
                processed += 1
                logger.info(
                    "diagram_extractor: wrote %d nodes / %d edges for image_id=%s",
                    len(nodes),
                    len(edges),
                    img.id,
                )
            except Exception as exc:
                logger.warning(
                    "diagram_extractor: Kuzu write failed for image_id=%s: %s", img.id, exc
                )
                continue

        logger.info(
            "diagram_extractor: done doc=%s processed=%d total=%d",
            document_id,
            processed,
            len(images),
        )
        return processed

    async def _write_to_kuzu(
        self,
        document_id: str,
        image_id: str,
        image_type: str,
        nodes: list[dict],
        edges: list[dict],
    ) -> None:
        """Write extracted diagram nodes and edges to Kuzu.

        Node dict shape: {"name": str, "node_type": str}
        Edge dict shape: {"from": str, "to": str, "edge_type": str, ...properties}

        Runs name-match linkage after writing nodes (DEPICTS edges to Entity).
        Pure Kuzu calls; no SQLite or LanceDB I/O.
        """

        graph = _graph_module.get_graph_service()

        # Build node_id map: name -> kuzu_id (for edge lookup)
        name_to_id: dict[str, str] = {}
        for node in nodes:
            name = node.get("name", "")
            node_type = node.get("node_type", "COMPONENT")
            if not name:
                continue
            # Deterministic ID: image_id + normalized name
            node_id = f"{image_id}:{name.lower()}"
            name_to_id[name] = node_id
            graph.upsert_diagram_node(
                node_id=node_id,
                name=name,
                node_type=node_type,
                source_image_id=image_id,
                document_id=document_id,
            )

        # Write edges; skip any whose from/to nodes are not in name_to_id
        for edge in edges:
            from_name = edge.get("from", "")
            to_name = edge.get("to", "")
            edge_type = edge.get("edge_type", "")
            if not from_name or not to_name or not edge_type:
                continue
            from_id = name_to_id.get(from_name)
            to_id = name_to_id.get(to_name)
            if from_id is None or to_id is None:
                logger.debug(
                    "diagram_extractor: skipping edge %r->%r (node not in extracted set)",
                    from_name,
                    to_name,
                )
                continue
            properties: dict[str, str] = {
                k: str(v)
                for k, v in edge.items()
                if k not in ("from", "to", "edge_type") and v is not None
            }
            try:
                graph.add_diagram_edge(
                    from_id=from_id,
                    to_id=to_id,
                    edge_type=edge_type,
                    document_id=document_id,
                    **properties,
                )
            except Exception as exc:
                logger.debug(
                    "diagram_extractor: edge write failed %r->%r type=%r: %s",
                    from_name,
                    to_name,
                    edge_type,
                    exc,
                )

        # Name-match linkage: attempt to link each diagram node to an existing Entity
        for name, node_id in name_to_id.items():
            entity_id = graph.match_entity_by_name(name, document_id)
            if entity_id is not None:
                try:
                    graph.add_depicts_edge(node_id, entity_id, document_id)
                    logger.debug("diagram_extractor: DEPICTS %r -> entity %r", name, entity_id)
                except Exception as exc:
                    logger.debug("diagram_extractor: DEPICTS edge failed for %r: %s", name, exc)


async def diagram_extract_handler(document_id: str, job_id: str) -> None:
    """Enrichment handler for job_type='diagram_extract'.

    Called by EnrichmentQueueWorker for each diagram_extract job.
    Delegates to DiagramExtractorService.extract().
    ServiceUnavailableError propagates to mark job 'failed'.
    """
    logger.info("diagram_extract_handler: starting doc=%s job=%s", document_id, job_id)
    svc = DiagramExtractorService()
    count = await svc.extract(document_id)
    logger.info(
        "diagram_extract_handler: done doc=%s job=%s processed=%d", document_id, job_id, count
    )
