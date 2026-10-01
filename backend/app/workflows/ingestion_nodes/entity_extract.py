"""entity_extract_node + _build_call_graph.

entity_extract_node is the largest single node in the ingestion
pipeline. For each chunk it:
  1. Runs GLiNER NER (filtered by content type) to surface entities.
  2. Disambiguates surface forms against the canonical entity index.
  3. Writes the document's entities and their CO_OCCURS, prerequisite, tech and
     VERSION_OF edges in one transaction.
  4. Concatenates the canonical entity tail back into ChunkModel
     so embed/keyword index can match on it

For code documents, also builds a function-level call graph via
_build_call_graph.

GLiNER is the dominant memory hog; if GLINER_ENABLED is false the
node degrades gracefully and the document still ingests.
"""

import asyncio as _asyncio
import logging
import uuid
from itertools import combinations

from sqlalchemy import update as _update

from app.config import get_settings as _get_settings
from app.database import get_session_factory
from app.exceptions import ModelNotDownloaded
from app.models import ChunkModel
from app.repos.document_repo import DocumentRepo
from app.services import graph as _graph_module  # indirect: get_graph_service is patched
from app.services import ner as _ner_module  # indirect: get_entity_extractor is patched
from app.services.code_parser import CodeParser
from app.services.entity_disambiguator import (
    _extract_version_qualifier,
    canonicalize_batch,
)
from app.services.graph import DocumentGraph
from app.services.prerequisite_detector import detect_prerequisites
from app.services.tech_relation_extractor import extract_tech_relations
from app.telemetry import trace_ingestion_node
from app.types import is_technical_content
from app.workflows.ingestion_nodes._shared import (
    IngestionState,
    _update_stage,
    build_entity_tail,
)

logger = logging.getLogger(__name__)

# A cap on GLiNER time for long documents. Ingest and reindex both read
# select_ner_chunks, so either builds the same graph (#63).
NER_CHUNK_LIMIT = 500


def select_ner_chunks(chunks: list[dict]) -> list[dict]:
    """The chunks entity extraction reads: all of them, or NER_CHUNK_LIMIT spread evenly."""
    if len(chunks) <= NER_CHUNK_LIMIT:
        return chunks
    step = len(chunks) // NER_CHUNK_LIMIT
    return chunks[::step][:NER_CHUNK_LIMIT]


async def record_entity_coverage(doc_id: str, chunks_scanned: int) -> None:
    async with get_session_factory()() as session:
        await DocumentRepo(session).set_entity_chunks_scanned(doc_id, chunks_scanned)
        await session.commit()


def _build_call_graph(chunks: list[dict], graph: DocumentGraph, doc_id: str) -> None:
    """Add a code document's functions and the CALLS edges between them."""

    # Collect function chunks (have function_name metadata)
    fn_chunks = [c for c in chunks if c.get("function_name")]
    if not fn_chunks:
        return

    # Upsert each function as an Entity node with type=FUNCTION
    fn_id_map: dict[str, str] = {}  # function_name → entity id
    for c in fn_chunks:
        name = c["function_name"]
        entity_id = f"fn_{doc_id}_{name}"
        graph.add_entity(entity_id, name, "FUNCTION")
        fn_id_map[name] = entity_id

    # Detect call edges via body_text substring matching
    defs = [
        {
            "name": c["function_name"],
            "kind": "function",
            "body_text": c.get("body_text", ""),
        }
        for c in fn_chunks
        if c.get("function_name")
    ]
    call_pairs = CodeParser.build_call_edges(defs)  # type: ignore[arg-type]
    for caller_name, callee_name in call_pairs:
        caller_id = fn_id_map.get(caller_name)
        callee_id = fn_id_map.get(callee_name)
        if caller_id and callee_id:
            graph.add_edge("CALLS", caller_id, callee_id)

    logger.info(
        "Call graph built",
        extra={"doc_id": doc_id, "functions": len(fn_chunks), "edges": len(call_pairs)},
    )


def _add_prerequisites(
    graph: DocumentGraph, canonical_entities: list[dict], ner_chunks: list[dict], doc_id: str
) -> None:
    """PREREQUISITE_OF edges from marker phrases, only between entities GLiNER confirmed."""
    try:
        name_to_id = {ent["name"]: ent["id"] for ent in canonical_entities}
        count = 0
        for dep_name, prereq_name, confidence in detect_prerequisites(ner_chunks, set(name_to_id)):
            dep_id, prereq_id = name_to_id.get(dep_name), name_to_id.get(prereq_name)
            if dep_id and prereq_id and dep_id != prereq_id:
                graph.add_edge("PREREQUISITE_OF", dep_id, prereq_id, confidence=confidence)
                count += 1
        logger.info("prerequisite edges created: %d", count, extra={"doc_id": doc_id})
    except Exception as exc:
        logger.warning(
            "prerequisite detection failed (non-fatal)", extra={"doc_id": doc_id}, exc_info=exc
        )


def _add_tech_relations(
    graph: DocumentGraph, canonical_entities: list[dict], ner_chunks: list[dict], doc_id: str
) -> None:
    """IMPLEMENTS/EXTENDS/USES/REPLACES/DEPENDS_ON edges, and VERSION_OF from a versioned
    LIBRARY entity to its base. Only for technical content, to avoid false edges in prose."""
    try:
        name_to_id = {ent["name"]: ent["id"] for ent in canonical_entities}
        count = 0
        for name_a, name_b, label in extract_tech_relations(ner_chunks, set(name_to_id)):
            id_a, id_b = name_to_id.get(name_a), name_to_id.get(name_b)
            if id_a and id_b and id_a != id_b:
                try:
                    graph.add_tech_relation(id_a, id_b, label)
                    count += 1
                except ValueError:
                    logger.debug("Skipped unknown tech relation label: %r", label)
        logger.info("tech relation edges created: %d", count, extra={"doc_id": doc_id})

        versions = 0
        for ent in canonical_entities:
            if ent["type"] != "LIBRARY":
                continue
            base_name, version_str = _extract_version_qualifier(ent["name"])
            if version_str is None or base_name == ent["name"]:
                continue
            base_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:{base_name}"))
            graph.add_entity(base_id, base_name, "LIBRARY")
            graph.add_edge("VERSION_OF", ent["id"], base_id)
            versions += 1
        if versions:
            logger.info("version_of edges created: %d", versions, extra={"doc_id": doc_id})
    except Exception as exc:
        logger.warning(
            "tech relation extraction failed (non-fatal)", extra={"doc_id": doc_id}, exc_info=exc
        )


def build_document_graph(
    doc_id: str,
    canonical_entities: list[dict],
    alias_map: dict[str, list[str]],
    ner_chunks: list[dict],
    chunks: list[dict],
    content_type: str,
    is_technical: bool | None = None,
) -> DocumentGraph:
    """A document's entities, CO_OCCURS, prerequisite/tech/version edges and call graph.

    Shared by entity_extract_node (ingestion) and reindex_entities
    --rebuild-graph so both produce an identical graph for the same input.
    """
    graph = DocumentGraph()
    for ent in canonical_entities:
        graph.add_entity(ent["id"], ent["name"], ent["type"], aliases=alias_map.get(ent["id"]))

    chunk_entities: dict[str, list[str]] = {}
    for ent in canonical_entities:
        chunk_entities.setdefault(ent["chunk_id"], []).append(ent["id"])
    # One id per entity, not per mention: a chunk naming Ulysses twice must not pair him
    # with himself. Sorting fixes the direction, so a pair is one edge, not two (I-49).
    for chunk_ent_ids in chunk_entities.values():
        for eid_a, eid_b in combinations(sorted(set(chunk_ent_ids)), 2):
            graph.add_co_occurrence(eid_a, eid_b)

    _add_prerequisites(graph, canonical_entities, ner_chunks, doc_id)
    if is_technical_content(content_type, is_technical):
        _add_tech_relations(graph, canonical_entities, ner_chunks, doc_id)
    if content_type == "code":
        _build_call_graph(chunks, graph, doc_id)
    return graph


async def entity_extract_node(state: IngestionState) -> IngestionState:
    doc_id = state["document_id"]
    chunks = state.get("chunks") or []
    logger.debug("node_start", extra={"node": "entity_extract", "doc_id": doc_id})
    await _update_stage(doc_id, "entity_extract")
    with trace_ingestion_node("entity_extract", state):
        entity_count = 0
        try:
            if not _get_settings().GLINER_ENABLED:
                logger.info(
                    "entity_extract_node: skipped (GLINER_ENABLED=false)",
                    extra={"doc_id": doc_id},
                )
                await _update_stage(doc_id, "complete")
                return {**state, "status": "complete"}

            extractor = _ner_module.get_entity_extractor()
            ner_chunks = select_ner_chunks(chunks)
            if len(ner_chunks) < len(chunks):
                logger.info(
                    "NER sampling %d of %d chunks",
                    len(ner_chunks),
                    len(chunks),
                    extra={"doc_id": doc_id},
                )
            # CPU-bound — run in thread pool to keep event loop free for status polls.
            # Timeout guards against GLiNER hanging on pathological chunk text.
            loop = _asyncio.get_event_loop()
            content_type = state.get("content_type") or "unknown"
            is_technical = state.get("is_technical")
            entities = await _asyncio.wait_for(
                loop.run_in_executor(
                    None, extractor.extract, ner_chunks, content_type, is_technical
                ),
                timeout=300.0,
            )
            entity_count = len(entities)

            graph = _graph_module.get_graph_service()

            # Disambiguate: collapse surface-form variants to canonical names
            # before writing the graph (e.g. "Mr. Holmes" -> "sherlock holmes").
            entity_tuples = [(ent["name"], ent["type"]) for ent in entities]
            existing_by_type = await graph.get_entities_by_type_for_document(doc_id)
            canonical_triples = canonicalize_batch(entity_tuples, existing_by_type)

            alias_map: dict[str, list[str]] = {}
            canonical_entities = []
            chunk_to_entities: dict[str, set[str]] = {}
            for (canonical, canonical_type, original), ent in zip(
                canonical_triples, entities, strict=True
            ):
                canonical_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:{canonical}"))
                if original != canonical:
                    alias_map.setdefault(canonical_id, []).append(original)
                canonical_entities.append(
                    {**ent, "id": canonical_id, "name": canonical, "type": canonical_type}
                )
                chunk_to_entities.setdefault(ent["chunk_id"], set()).add(canonical)

            # Entity injection (option b) -- store canonical entities in a
            # sibling entities_text column. Display text is preserved; downstream
            # embed_node and keyword_index_node concatenate entities_text into the
            # FTS5 indexed text and the embedding input. Idempotent: every reindex
            # overwrites entities_text rather than appending.
            if chunk_to_entities:
                async with get_session_factory()() as update_session:
                    for chunk in chunks:
                        cid = chunk["id"]
                        canonicals = chunk_to_entities.get(cid)
                        tail = build_entity_tail(canonicals) if canonicals else ""
                        chunk["entities_text"] = tail or None
                        await update_session.execute(
                            _update(ChunkModel)
                            .where(ChunkModel.id == cid)
                            .values(entities_text=tail or None)
                        )
                    await update_session.commit()

            document_graph = await _asyncio.to_thread(
                build_document_graph,
                doc_id,
                canonical_entities,
                alias_map,
                ner_chunks,
                chunks,
                state.get("content_type") or "",
                is_technical,
            )
            await graph.write_document_graph(doc_id, document_graph)
            await record_entity_coverage(doc_id, len(ner_chunks))
        except ModelNotDownloaded:
            # Optional, installed from Settings; the document is complete without it.
            logger.info(
                "entity_extract_node: skipped, entity model not installed",
                extra={"doc_id": doc_id},
            )
        except MemoryError as exc:
            logger.exception(
                "entity_extract_node: OOM loading GLiNER model -- "
                "set GLINER_ENABLED=false in .env to skip NER on low-memory machines",
                extra={"doc_id": doc_id},
                exc_info=exc,
            )
        except Exception as exc:
            logger.warning(
                "entity_extract_node failed (non-fatal, proceeding to complete)",
                extra={"doc_id": doc_id, "entity_count": entity_count},
                exc_info=exc,
            )
        finally:
            logger.info(
                "entity_extract_node finished",
                extra={"doc_id": doc_id, "entity_count": entity_count},
            )

        await _update_stage(doc_id, "embedding")
    return {**state, "status": "embedding"}


# _background_tasks now lives in ingestion_nodes/_shared.py so all node
# modules share one strong-ref set. Re-exported below for back-compat
# (tests check the same registry).
# _run_objective_extraction lives in ingestion_nodes/chunk.py (its only
# call site) and is re-exported via that module.
