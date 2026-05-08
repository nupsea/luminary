import asyncio
import logging
import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.database import get_session_factory
from app.telemetry import trace_chain, trace_ingestion_node
from app.workflows.ingestion_nodes._shared import (
    CHUNK_CONFIGS,  # noqa: F401  re-exported for back-compat
    ENTITY_TAIL_MAX,  # noqa: F401  re-exported for back-compat
    STAGE_PROGRESS,  # noqa: F401  re-exported for routers/documents.py
    ContentType,  # noqa: F401  re-exported for back-compat
    IngestionState,
    _background_tasks,
    _classify,  # noqa: F401  re-exported for back-compat (tests import from ingestion)
    _parser,  # noqa: F401  re-exported for back-compat
    _update_stage,
    build_entity_tail,  # noqa: F401  re-exported for back-compat
)
from app.workflows.ingestion_nodes.chunk import (
    _chunk_book,  # noqa: F401  re-exported for tests
    _chunk_code_file,  # noqa: F401  re-exported for tests
    _chunk_conversation,  # noqa: F401  re-exported for tests
    _chunk_tech_book,  # noqa: F401  re-exported for tests
    _run_objective_extraction,  # noqa: F401  re-exported for back-compat
    chunk_node,
)
from app.workflows.ingestion_nodes.parse import classify_node, parse_node
from app.workflows.ingestion_nodes.transcribe import (
    _chunk_audio,  # noqa: F401  re-exported for back-compat (tests/test_audio_ingestion.py)
    transcribe_node,
)

logger = logging.getLogger(__name__)


async def embed_node(state: IngestionState) -> IngestionState:
    import asyncio

    logger.debug("node_start", extra={"node": "embed", "doc_id": state["document_id"]})
    with trace_ingestion_node("embed", state):
        try:
            doc_id = state["document_id"]
            chunks = state.get("chunks") or []
            if not chunks:
                logger.warning("embed_node: no chunks to embed", extra={"doc_id": doc_id})
                await _update_stage(doc_id, "embedding")
                return {**state, "status": "indexing"}

            from app.services.embedder import get_embedding_service
            from app.services.vector_store import get_lancedb_service

            content_type = state.get("content_type") or "notes"
            # S224: concatenate per-chunk entity tail (if any) into embedding input
            # so vector search can match canonical entity names that the surface form
            # may have spelled differently. Display text remains in chunk["text"].
            texts = [
                c["text"] + ("\n" + c["entities_text"] if c.get("entities_text") else "")
                for c in chunks
            ]
            embedder = get_embedding_service()

            # Update stage BEFORE encoding so UI reflects current work immediately
            await _update_stage(doc_id, "embedding")
            logger.info(
                "Embedding started",
                extra={"doc_id": doc_id, "num_chunks": len(chunks)},
            )

            # Run CPU-bound encoding in a thread pool so the event loop stays free
            # for status poll requests during the (potentially long) embedding pass.
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(None, embedder.encode, texts)

            lancedb_rows = [
                {
                    "chunk_id": c["id"],
                    "document_id": doc_id,
                    "content_type": content_type,
                    "section_heading": "",
                    "page": 0,
                    "chunk_index": c.get("index", 0),
                    "speaker": "",
                    "text": c["text"],
                    "vector": embeddings[i],
                }
                for i, c in enumerate(chunks)
            ]

            # Upsert in batches to avoid memory/spill issues in LanceDB/DataFusion
            # with very large documents (like the Bible with 9400+ chunks).
            batch_size = 1000
            lancedb_svc = get_lancedb_service()
            for start_idx in range(0, len(lancedb_rows), batch_size):
                end_idx = start_idx + batch_size
                batch = lancedb_rows[start_idx:end_idx]
                lancedb_svc.upsert_chunks(batch)
                logger.info(
                    "Upserted batch %d-%d to LanceDB",
                    start_idx,
                    min(end_idx, len(lancedb_rows)),
                )

            logger.info("Embedded %d chunks", len(chunks), extra={"doc_id": doc_id})
            return {**state, "status": "indexing"}
        except Exception as exc:
            logger.error("embed_node failed", exc_info=exc)
            return {**state, "status": "error", "error": str(exc)}


async def keyword_index_node(state: IngestionState) -> IngestionState:
    from sqlalchemy import text

    doc_id = state["document_id"]
    logger.debug("node_start", extra={"node": "keyword_index", "doc_id": doc_id})
    with trace_ingestion_node("keyword_index", state):
        try:
            async with get_session_factory()() as session:
                # S224: concatenate text || entities_text (when present) so FTS5 BM25
                # matches canonical entity names even if the surface form differs.
                await session.execute(
                    text(
                        "INSERT INTO chunks_fts(rowid, text, chunk_id, document_id) "
                        "SELECT rowid, "
                        "       text || CASE "
                        "         WHEN entities_text IS NOT NULL AND entities_text != '' "
                        "         THEN ' ' || entities_text "
                        "         ELSE '' END, "
                        "       id, document_id FROM chunks "
                        "WHERE document_id = :doc_id"
                    ),
                    {"doc_id": doc_id},
                )
                await session.commit()
            logger.info("FTS5 index populated", extra={"doc_id": doc_id})
        except Exception as exc:
            logger.error("keyword_index_node failed", exc_info=exc)
        await _update_stage(doc_id, "indexing")
    return {**state, "status": "extracting"}


def _build_call_graph(chunks: list[dict], graph, doc_id: str) -> None:
    """Build call graph for code document: create function Entity nodes and CALLS edges."""
    from app.services.code_parser import CodeParser  # noqa: PLC0415

    # Collect function chunks (have function_name metadata)
    fn_chunks = [c for c in chunks if c.get("function_name")]
    if not fn_chunks:
        return

    # Upsert each function as an Entity node with type=FUNCTION
    fn_id_map: dict[str, str] = {}  # function_name → entity id
    for c in fn_chunks:
        name = c["function_name"]
        entity_id = f"fn_{doc_id}_{name}"
        graph.upsert_entity(entity_id, name, "FUNCTION")
        graph.add_mention(entity_id, doc_id)
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
            graph.add_call_edge(caller_id, callee_id, doc_id)

    logger.info(
        "Call graph built",
        extra={"doc_id": doc_id, "functions": len(fn_chunks), "edges": len(call_pairs)},
    )


async def entity_extract_node(state: IngestionState) -> IngestionState:
    doc_id = state["document_id"]
    chunks = state.get("chunks") or []
    logger.debug("node_start", extra={"node": "entity_extract", "doc_id": doc_id})
    await _update_stage(doc_id, "entity_extract")
    with trace_ingestion_node("entity_extract", state):
        entity_count = 0
        try:
            from app.config import get_settings as _get_settings  # noqa: PLC0415

            if not _get_settings().GLINER_ENABLED:
                logger.info(
                    "entity_extract_node: skipped (GLINER_ENABLED=false)",
                    extra={"doc_id": doc_id},
                )
                await _update_stage(doc_id, "complete")
                return {**state, "status": "complete"}

            from itertools import combinations  # noqa: PLC0415

            from sqlalchemy import select  # noqa: PLC0415

            from app.models import DocumentModel  # noqa: PLC0415
            from app.services.graph import get_graph_service  # noqa: PLC0415
            from app.services.ner import get_entity_extractor  # noqa: PLC0415

            extractor = get_entity_extractor()
            # Cap NER at 500 chunks — sufficient for graph coverage, avoids multi-hour
            # runs on large documents (e.g. 2000+ chunk books).
            # Sample evenly across the document to get representative entities.
            import asyncio as _asyncio

            NER_CHUNK_LIMIT = 5000
            if len(chunks) > NER_CHUNK_LIMIT:
                step = len(chunks) // NER_CHUNK_LIMIT
                ner_chunks = chunks[::step][:NER_CHUNK_LIMIT]
                logger.info(
                    "NER sampling %d of %d chunks",
                    len(ner_chunks),
                    len(chunks),
                    extra={"doc_id": doc_id},
                )
            else:
                ner_chunks = chunks
            # CPU-bound — run in thread pool to keep event loop free for status polls
            loop = _asyncio.get_event_loop()
            content_type = state.get("content_type") or "unknown"
            entities = await loop.run_in_executor(None, extractor.extract, ner_chunks, content_type)
            entity_count = len(entities)

            graph = get_graph_service()

            # Upsert the document node in Kuzu
            async with get_session_factory()() as session:
                result = await session.execute(
                    select(DocumentModel.title, DocumentModel.content_type).where(
                        DocumentModel.id == doc_id
                    )
                )
                row = result.first()
                if row:
                    graph.upsert_document(doc_id, row.title or "", row.content_type or "notes")

            # Disambiguate: collapse surface-form variants to canonical names
            # before writing to Kuzu (e.g. "Mr. Holmes" -> "sherlock holmes").
            from app.services.entity_disambiguator import canonicalize_batch  # noqa: PLC0415

            entity_tuples = [(ent["name"], ent["type"]) for ent in entities]
            existing_by_type = graph.get_entities_by_type_for_document(doc_id)
            canonical_triples = canonicalize_batch(entity_tuples, existing_by_type)

            alias_map: dict[str, list[str]] = {}
            canonical_entities = []
            chunk_to_entities: dict[str, set[str]] = {}
            for (canonical, etype, original), ent in zip(canonical_triples, entities):
                canonical_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:{canonical}"))
                if original != canonical:
                    alias_map.setdefault(canonical_id, []).append(original)
                canonical_entities.append({**ent, "id": canonical_id, "name": canonical})
                chunk_to_entities.setdefault(ent["chunk_id"], set()).add(canonical)

            # S224: Entity injection (option b) -- store canonical entities in a
            # sibling entities_text column. Display text is preserved; downstream
            # embed_node and keyword_index_node concatenate entities_text into the
            # FTS5 indexed text and the embedding input. Idempotent: every reindex
            # overwrites entities_text rather than appending.
            if chunk_to_entities:
                from sqlalchemy import update as _update  # noqa: PLC0415

                from app.models import ChunkModel  # noqa: PLC0415

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

            # Upsert entities and add mentions; re-raise on Kuzu failure when
            # entities were successfully extracted (data loss must not be silent).
            try:
                for ent in canonical_entities:
                    aliases = alias_map.get(ent["id"])
                    graph.upsert_entity(ent["id"], ent["name"], ent["type"], aliases=aliases)
                    graph.add_mention(ent["id"], doc_id)

                # Co-occurrence: entities sharing the same chunk
                chunk_entities: dict[str, list[str]] = {}
                for ent in canonical_entities:
                    chunk_entities.setdefault(ent["chunk_id"], []).append(ent["id"])

                for chunk_ent_ids in chunk_entities.values():
                    for eid_a, eid_b in combinations(chunk_ent_ids, 2):
                        graph.add_co_occurrence(eid_a, eid_b, doc_id)
            except Exception:
                if entity_count > 0:
                    # Entities were extracted but Kuzu write failed — re-raise so the
                    # outer except captures it and the root cause is visible in logs.
                    raise

            # Prerequisite detection: scan chunk texts for marker phrases.
            # Only creates edges between entities already confirmed by GLiNER.
            try:
                from app.services.prerequisite_detector import detect_prerequisites  # noqa: PLC0415

                canonical_name_to_id: dict[str, str] = {
                    ent["name"]: ent["id"] for ent in canonical_entities
                }
                known_names: set[str] = set(canonical_name_to_id.keys())
                prereq_pairs = detect_prerequisites(ner_chunks, known_names)
                prereq_count = 0
                for dep_name, prereq_name, confidence in prereq_pairs:
                    dep_id = canonical_name_to_id.get(dep_name)
                    prereq_id = canonical_name_to_id.get(prereq_name)
                    if dep_id and prereq_id and dep_id != prereq_id:
                        graph.add_prerequisite(dep_id, prereq_id, doc_id, confidence)
                        prereq_count += 1
                logger.info(
                    "prerequisite edges created: %d",
                    prereq_count,
                    extra={"doc_id": doc_id},
                )
            except Exception as prereq_exc:
                logger.warning(
                    "prerequisite detection failed (non-fatal)",
                    extra={"doc_id": doc_id},
                    exc_info=prereq_exc,
                )

            # Tech relationship extraction: IMPLEMENTS, EXTENDS, USES, REPLACES, DEPENDS_ON
            # Only run for tech-relevant content types to avoid false edges in prose.
            content_type_for_tech = state.get("content_type") or ""
            if content_type_for_tech in ("code", "tech_book", "tech_article"):
                try:
                    from app.services.tech_relation_extractor import (
                        extract_tech_relations,  # noqa: PLC0415
                    )

                    canonical_name_to_id_tech: dict[str, str] = {
                        ent["name"]: ent["id"] for ent in canonical_entities
                    }
                    known_names_tech: set[str] = set(canonical_name_to_id_tech.keys())
                    tech_rel_pairs = extract_tech_relations(ner_chunks, known_names_tech)
                    tech_rel_count = 0
                    for name_a, name_b, rel_label in tech_rel_pairs:
                        id_a = canonical_name_to_id_tech.get(name_a)
                        id_b = canonical_name_to_id_tech.get(name_b)
                        if id_a and id_b and id_a != id_b:
                            try:
                                graph.add_tech_relation(id_a, id_b, rel_label, doc_id)
                                tech_rel_count += 1
                            except ValueError:
                                logger.debug("Skipped unknown tech relation label: %r", rel_label)
                    logger.info(
                        "tech relation edges created: %d",
                        tech_rel_count,
                        extra={"doc_id": doc_id},
                    )

                    # Version-of edges: for LIBRARY entities with version qualifiers,
                    # link the versioned entity to its major-version base entity.
                    from app.services.entity_disambiguator import (
                        _extract_version_qualifier,  # noqa: PLC0415
                    )

                    version_base_count = 0
                    for ent in canonical_entities:
                        if ent["type"] != "LIBRARY":
                            continue
                        name = ent["name"]
                        base_name, version_str = _extract_version_qualifier(name)
                        if version_str is None or base_name == name:
                            continue
                        # Create or find the base entity node
                        import uuid as _uuid  # noqa: PLC0415

                        base_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"{doc_id}:{base_name}"))
                        # Upsert base entity if it doesn't exist yet
                        graph.upsert_entity(base_id, base_name, "LIBRARY")
                        graph.add_mention(base_id, doc_id)
                        graph.add_version_of(ent["id"], base_id, doc_id)
                        version_base_count += 1
                    if version_base_count:
                        logger.info(
                            "version_of edges created: %d",
                            version_base_count,
                            extra={"doc_id": doc_id},
                        )
                except Exception as tech_exc:
                    logger.warning(
                        "tech relation extraction failed (non-fatal)",
                        extra={"doc_id": doc_id},
                        exc_info=tech_exc,
                    )

            # Build call graph for code documents
            content_type = state.get("content_type") or ""
            if content_type == "code":
                _build_call_graph(chunks, graph, doc_id)
        except MemoryError as exc:
            logger.error(
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


async def _run_pregenerate(doc_id: str) -> None:
    """Background task: pre-generate summaries and invalidate library cache."""
    from app.services.summarizer import get_summarization_service  # noqa: PLC0415

    svc = get_summarization_service()
    try:
        await svc.generate_all_summaries(doc_id)
        logger.info("background summarize: done", extra={"doc_id": doc_id})
    except Exception as exc:
        logger.warning(
            "background summarize: failed (non-fatal)",
            extra={"doc_id": doc_id},
            exc_info=exc,
        )
    finally:
        # Always invalidate library cache — a new document was ingested regardless
        # of whether its individual summaries could be generated (e.g. Ollama offline).
        await svc.invalidate_library_cache()


async def section_summarize_node(state: IngestionState) -> IngestionState:
    """Generate section-level summaries (bounded to 100 units) before document summarization.

    Non-fatal: if Ollama is offline or summarization fails, ingestion continues.
    """
    doc_id = state["document_id"]
    logger.debug("node_start", extra={"node": "section_summarize", "doc_id": doc_id})
    try:
        from app.services.section_summarizer import get_section_summarizer_service  # noqa: PLC0415

        svc = get_section_summarizer_service()
        count = await svc.generate(doc_id)
        logger.info("section_summarize_node: %d units stored", count, extra={"doc_id": doc_id})
        return {**state, "section_summary_count": count}
    except Exception as exc:
        logger.warning(
            "section_summarize_node failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )
        return {**state, "section_summary_count": 0}


async def summarize_node(state: IngestionState) -> IngestionState:
    """Fire off summary pre-generation as a background task and return immediately.

    The document is already marked complete by entity_extract_node.  Summaries
    generate asynchronously so ingestion does not block on LLM calls.
    """
    doc_id = state["document_id"]
    task = asyncio.create_task(_run_pregenerate(doc_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    logger.info("summarize_node: background task scheduled", extra={"doc_id": doc_id})
    return state


async def error_finalize_node(state: IngestionState) -> IngestionState:
    """Terminal node reached when any upstream node sets status='error'.

    Persists the human-readable error detail to DocumentModel.error_message so
    GET /documents/{id}/status can surface it to the UI (e.g. 'ffmpeg not found').
    """
    from sqlalchemy import update as _update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    doc_id = state["document_id"]
    error_detail = state.get("error")
    async with get_session_factory()() as session:
        await session.execute(
            _update(DocumentModel)
            .where(DocumentModel.id == doc_id)
            .values(stage="error", error_message=error_detail)
        )
        await session.commit()
    logger.error(
        "Ingestion failed at node",
        extra={"document_id": doc_id, "error": error_detail},
    )
    return state


async def enrichment_enqueue_node(state: IngestionState) -> IngestionState:
    """Create enrichment jobs: image_extract (PDF/EPUB only) and concept_link (always).

    Non-fatal: enrichment failure does not prevent document from being usable.
    """
    import uuid as _uuid  # noqa: PLC0415

    from sqlalchemy import update as _update  # noqa: PLC0415

    from app.models import DocumentModel, EnrichmentJobModel  # noqa: PLC0415
    from app.services.enrichment_worker import get_enrichment_worker  # noqa: PLC0415

    doc_id = state["document_id"]
    fmt = state.get("format", "").lower()
    _IMAGE_FORMATS = {"pdf", "epub", "md", "markdown"}

    # Image extraction: PDF, EPUB, and MD (web articles)
    if fmt in _IMAGE_FORMATS:
        try:
            job_id = str(_uuid.uuid4())
            async with get_session_factory()() as session:
                session.add(
                    EnrichmentJobModel(
                        id=job_id,
                        document_id=doc_id,
                        job_type="image_extract",
                        status="pending",
                    )
                )
                await session.execute(
                    _update(DocumentModel)
                    .where(DocumentModel.id == doc_id)
                    .values(stage="enriching")
                )
                await session.commit()

            worker = get_enrichment_worker()
            task = asyncio.create_task(worker._dispatch_pending())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

            logger.info(
                "enrichment_enqueue_node: enqueued image_extract job=%s doc=%s",
                job_id,
                doc_id,
            )
        except Exception as exc:
            logger.warning(
                "enrichment_enqueue_node: image_extract enqueue failed (non-fatal): %s",
                exc,
                extra={"doc_id": doc_id},
            )
    else:
        logger.info(
            "enrichment_enqueue_node: skipping image_extract (format=%s has no images)",
            fmt,
            extra={"doc_id": doc_id},
        )

    # Concept linking: always enqueue for cross-document concept comparison (S141)
    try:
        cl_job_id = str(_uuid.uuid4())
        async with get_session_factory()() as session:
            session.add(
                EnrichmentJobModel(
                    id=cl_job_id,
                    document_id=doc_id,
                    job_type="concept_link",
                    status="pending",
                )
            )
            await session.commit()

        worker = get_enrichment_worker()
        task = asyncio.create_task(worker._dispatch_pending())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        logger.info(
            "enrichment_enqueue_node: enqueued concept_link job=%s doc=%s",
            cl_job_id,
            doc_id,
        )
    except Exception as exc:
        logger.warning(
            "enrichment_enqueue_node: concept_link enqueue failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )

    await _update_stage(doc_id, "complete")
    return {**state, "status": "complete"}


def _route_on_status(next_node: str):
    """Return a router that goes to error_finalize if status=='error', else next_node."""

    def _router(state: IngestionState) -> str:
        return "error_finalize" if state.get("status") == "error" else next_node

    return _router


def _build_graph():
    builder: StateGraph = StateGraph(IngestionState)
    builder.add_node("parse", parse_node)
    builder.add_node("classify", classify_node)
    builder.add_node("transcribe", transcribe_node)
    builder.add_node("chunk", chunk_node)
    builder.add_node("embed", embed_node)
    builder.add_node("keyword_index", keyword_index_node)
    builder.add_node("entity_extract", entity_extract_node)
    builder.add_node("section_summarize", section_summarize_node)
    builder.add_node("summarize", summarize_node)
    builder.add_node("enrichment_enqueue", enrichment_enqueue_node)
    builder.add_node("error_finalize", error_finalize_node)
    builder.add_edge(START, "parse")
    builder.add_conditional_edges("parse", _route_on_status("classify"))
    builder.add_conditional_edges("classify", _route_on_status("transcribe"))
    builder.add_conditional_edges("transcribe", _route_on_status("chunk"))
    builder.add_conditional_edges("chunk", _route_on_status("entity_extract"))
    builder.add_edge("entity_extract", "embed")
    builder.add_edge("embed", "keyword_index")
    builder.add_edge("keyword_index", "section_summarize")
    builder.add_edge("section_summarize", "summarize")
    builder.add_edge("summarize", "enrichment_enqueue")
    builder.add_edge("enrichment_enqueue", END)
    builder.add_edge("error_finalize", END)
    return builder.compile()


ingestion_graph = _build_graph()


async def run_ingestion(
    document_id: str,
    file_path: str,
    format: str,
    content_type: str | None = None,
    parsed_document: dict[str, Any] | None = None,
) -> None:
    initial_state: IngestionState = {
        "document_id": document_id,
        "file_path": file_path,
        "format": format,
        "parsed_document": parsed_document,
        "content_type": content_type,
        "chunks": None,
        "status": "parsing" if parsed_document is None else "classifying",
        "error": None,
        "section_summary_count": None,
        "audio_duration_seconds": None,
        "_audio_chunks": None,
    }
    logger.info(
        "Ingestion task started",
        extra={"document_id": document_id, "format": format, "content_type": content_type},
    )
    if parsed_document is None:
        await _update_stage(document_id, "parsing")
    else:
        await _update_stage(document_id, "classifying")
    with trace_chain(
        "ingestion.workflow",
        input_value=f"doc={document_id} format={format}",
    ) as root_span:
        root_span.set_attribute("ingestion.document_id", document_id)
        root_span.set_attribute("ingestion.format", format)
        try:
            await ingestion_graph.ainvoke(initial_state)
            root_span.set_attribute("output.value", "complete")
            logger.info("Ingestion task complete", extra={"document_id": document_id})
        except Exception as exc:
            root_span.set_attribute("error", True)
            root_span.set_attribute("error.message", str(exc))
            logger.error(
                "Ingestion task failed",
                extra={"document_id": document_id},
                exc_info=exc,
            )
            await _update_stage(document_id, "error")
