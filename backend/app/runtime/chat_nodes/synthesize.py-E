"""synthesize_node and its citation/contradiction helpers.

synthesize_node prepares the LLM prompt + system prompt and stores
them in state as `_llm_prompt` and `_system_prompt` *without* calling
the LLM. `stream_answer()` runs the LLM streaming so the first SSE
token event reaches the client as soon as the LLM emits it (not after
the whole response is buffered).

Pass-through behaviour: if a strategy node already set a non-empty
`answer` (e.g. summary_node with a cached executive summary), this
node returns {} so stream_answer() emits the existing answer.
"""

import logging

from sqlalchemy import select

from app.database import get_session_factory
from app.models import ChunkModel, DocumentModel
from app.runtime.chat_nodes._shared import _get_system_prompt
from app.services import graph as _graph_module  # indirect: get_graph_service is patched
from app.services.context_packer import pack_context
from app.services.qa import _should_use_summary
from app.services.summarizer import get_summarization_service
from app.types import ChatState, TransparencyInfo

logger = logging.getLogger(__name__)


async def _fetch_doc_titles_for_chunks(chunks_dicts: list[dict]) -> dict[str, str]:
    doc_ids = list({c["document_id"] for c in chunks_dicts if c.get("document_id")})
    if not doc_ids:
        return {}
    async with get_session_factory()() as session:
        rows = await session.execute(
            select(DocumentModel.id, DocumentModel.title).where(DocumentModel.id.in_(doc_ids))
        )
        return {row.id: row.title for row in rows}


async def _fetch_section_ids_and_pages_for_chunks(
    chunk_ids: list[str],
) -> dict[str, tuple[str | None, int | None]]:
    """Return {chunk_id: (section_id, pdf_page_number)} for the given chunk_ids.

    Used by synthesize_node to build SourceCitation entries from retrieved chunks.
    Returns {} on any DB error (non-fatal).
    """
    if not chunk_ids:
        return {}
    try:
        async with get_session_factory()() as session:
            rows = await session.execute(
                select(ChunkModel.id, ChunkModel.section_id, ChunkModel.pdf_page_number).where(
                    ChunkModel.id.in_(chunk_ids)
                )
            )
            return {row.id: (row.section_id, row.pdf_page_number) for row in rows}
    except Exception:
        logger.warning("_fetch_section_ids_and_pages_for_chunks: DB lookup failed", exc_info=True)
        return {}


async def _fetch_contradiction_context(doc_ids: list[str]) -> str:
    """Return a formatted context block of SAME_CONCEPT contradictions for the given documents.

    Fetches SAME_CONCEPT edges with contradiction=True that involve any of the given doc_ids.
    Looks up publication_year to include '[YYYY source preferred]' when available.
    Returns empty string if no contradictions exist or on any error.
    Caps output at 3 contradictions to avoid prompt bloat.
    """

    try:
        svc = _graph_module.get_graph_service()
        all_edges = svc.get_same_concept_edges()
        relevant = [
            e
            for e in all_edges
            if e["contradiction"]
            and (e["source_doc_id"] in doc_ids or e["target_doc_id"] in doc_ids)
        ]
        if not relevant:
            return ""

        # Look up publication years for the documents involved
        all_doc_ids: set[str] = set()
        for e in relevant:
            all_doc_ids.add(e["source_doc_id"])
            all_doc_ids.add(e["target_doc_id"])

        doc_years: dict[str, int | None] = {}
        try:
            async with get_session_factory()() as session:
                rows = await session.execute(
                    select(DocumentModel.id, DocumentModel.publication_year).where(
                        DocumentModel.id.in_(list(all_doc_ids))
                    )
                )
                for row in rows:
                    doc_years[row.id] = row.publication_year
        except Exception:
            logger.debug("_fetch_contradiction_context: year lookup failed", exc_info=True)

        lines: list[str] = ["[Cross-source contradictions detected:]"]
        for e in relevant[:3]:
            prefer = ""
            if e["prefer_source"] == "b":
                year = doc_years.get(e["target_doc_id"])
                prefer = f" [{year} source preferred]" if year else " (newer source preferred)"
            elif e["prefer_source"] == "a":
                year = doc_years.get(e["source_doc_id"])
                prefer = f" [{year} source preferred]" if year else " (first source preferred)"
            lines.append(f'- Concept "{e["name_a"]}": {e["contradiction_note"]}{prefer}')
        return "\n".join(lines)
    except Exception:
        logger.debug("_fetch_contradiction_context failed", exc_info=True)
        return ""


async def synthesize_node(state: ChatState) -> dict:
    """Prepare LLM prompt for stream_answer() to call streaming.

    Pass-through: if a strategy node already set a non-empty answer (e.g. summary_node
    with a cached executive summary), returns {} so stream_answer() uses that answer.
    No-context: if both chunks and section_context are absent, returns {"not_found": True}.

    True streaming design: synthesize_node prepares the prompt and system_prompt, stores
    them in state as _llm_prompt and _system_prompt, and returns WITHOUT calling the LLM.
    stream_answer() calls the LLM streaming and yields tokens progressively to the SSE
    client as they are generated, rather than buffering the full response first.
    """
    existing_answer = state.get("answer", "")
    if existing_answer:
        logger.info("synthesize_node: answer already set — pass-through, skipping LLM call")
        return {}

    chunks_dicts = state.get("chunks") or []
    section_context = state.get("section_context")
    question = state["question"]
    scope = state.get("scope", "all")
    intent = state.get("intent")

    if not chunks_dicts and not section_context:
        logger.info("synthesize_node: no context available — returning not_found")
        return {"not_found": True}

    logger.info(
        "synthesize_node: intent=%s chunks=%d section_context=%s",
        intent,
        len(chunks_dicts),
        "yes" if section_context else "no",
    )


    # Assemble chunk context using the pure context packer (dedup + section grouping)
    chunks_context = pack_context(chunks_dicts, token_budget=3000) if chunks_dicts else ""

    # section_context (graph results, executive summary) capped at 1000 tokens
    context_parts: list[str] = []
    if section_context:
        words = section_context.split()
        cap_words = int(1000 / 1.3)  # approx word count for 1000 tokens
        if len(words) > cap_words:
            section_context = " ".join(words[:cap_words]) + " ..."
        context_parts.append(section_context)

    if chunks_context:
        context_parts.append(chunks_context)

    context = "\n\n---\n\n".join(context_parts) if context_parts else ""

    # For summary intent with scope=single: also prepend executive summary if chunks present
    if (
        intent != "summary"
        and scope == "single"
        and state.get("doc_ids")
        and _should_use_summary(question)
    ):
        try:

            exec_summary = await get_summarization_service()._fetch_cached(
                state["doc_ids"][0], "executive"
            )
            if exec_summary:
                context = f"[Document Summary]\n{exec_summary.content}\n\n---\n\n{context}"
        except Exception:
            logger.warning("synthesize_node: failed to fetch executive summary", exc_info=True)

    # Inject conversation history before retrieval context.
    # Cap at ~385 words (~500 tokens) to protect the retrieval context budget.
    # Most-recent messages are kept when trimming is needed.
    conversation_history = state.get("conversation_history") or []
    history_block = ""
    if conversation_history:
        all_lines: list[str] = []
        for msg in conversation_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            label = "User" if role == "user" else "Assistant"
            all_lines.append(f"{label}: {content}")
        # Keep as many lines as fit within the word cap, prioritising recent turns.
        lines_to_include: list[str] = []
        word_count = 0
        for line in reversed(all_lines):
            words = len(line.split())
            if word_count + words > 385:
                break
            lines_to_include.insert(0, line)
            word_count += words
        if lines_to_include:
            history_block = "Prior conversation (most recent last):\n" + "\n".join(lines_to_include)

    if history_block:
        prompt = f"{history_block}\n\nContext:\n\n{context}\n\nQuestion: {question}"
    else:
        prompt = f"Context:\n\n{context}\n\nQuestion: {question}"
    system_prompt = _get_system_prompt(intent)

    # For library-wide factual/exploratory queries, instruct the LLM to attribute sources
    if scope == "all" and intent in ("factual", "exploratory"):
        system_prompt = (
            system_prompt + "\n\nThe user is asking about their entire library. "
            "Answer using only the provided passages. "
            "If the passages come from multiple documents, synthesise across them. "
            "Be explicit about which document each point comes from."
        )

    # Inject SAME_CONCEPT contradiction context for scope=all
    if scope == "all" and state.get("doc_ids"):
        try:
            contradiction_ctx = await _fetch_contradiction_context(state["doc_ids"])
            if contradiction_ctx:
                context = contradiction_ctx + "\n\n---\n\n" + context
                logger.info(
                    "synthesize_node: injected contradiction context (%d chars)",
                    len(contradiction_ctx),
                )
        except Exception:
            logger.debug("synthesize_node: contradiction context fetch failed", exc_info=True)

    # Inject version-mismatch detection instruction when web snippets are present
    web_snippets = state.get("web_snippets") or []
    if web_snippets:
        web_versions = [s.get("version_info", "") for s in web_snippets if s.get("version_info")]
        if web_versions:
            system_prompt = (
                system_prompt + "\n\nSome context comes from web sources labeled [Web: ...]. "
                "If the web source mentions a newer version than the local content "
                "(e.g. 'Python 3.12' vs 'Python 3.9'), explicitly note the discrepancy: "
                "'Your book covers X [Local]. The current recommendation is Y [Web: domain].' "
                "In the citations JSON, add version_mismatch=true to any citation where "
                "a version discrepancy is detected between local and web content."
            )

    # collect SourceCitations from context chunks for post-stream emission.
    # Deduplicate by section_id (first occurrence wins); when section_id is None,
    # fall back to chunk_id so each unlinked chunk gets its own citation entry.
    chunk_meta: dict = {}  # chunk_id -> (section_id, pdf_page); populated below if chunks present
    source_citations_out: list[dict] = []
    if chunks_dicts:
        chunk_ids = [c["chunk_id"] for c in chunks_dicts if c.get("chunk_id")]
        chunk_meta = await _fetch_section_ids_and_pages_for_chunks(chunk_ids)
        doc_titles_map = await _fetch_doc_titles_for_chunks(chunks_dicts)

        seen_dedup_keys: set[str] = set()
        for c in chunks_dicts:
            cid = c.get("chunk_id", "")
            meta = chunk_meta.get(cid, (None, None))
            section_id, pdf_page = meta
            doc_id = c.get("document_id", "")
            doc_title = doc_titles_map.get(doc_id, "")
            section_heading = c.get("section_heading", "")

            # Dedup key: (section_id, page) for PDFs so different pages in the same
            # section produce separate citations; section_id alone for non-PDFs.
            if pdf_page is not None and section_id:
                dedup_key = f"{section_id}:{pdf_page}"
            elif section_id:
                dedup_key = section_id
            else:
                dedup_key = cid
            if dedup_key in seen_dedup_keys:
                continue
            seen_dedup_keys.add(dedup_key)

            chunk_text = c.get("text", "") or ""
            source_citations_out.append(
                {
                    "chunk_id": cid,
                    "document_id": doc_id,
                    "document_title": doc_title,
                    "section_id": section_id,
                    "section_heading": section_heading,
                    "pdf_page_number": pdf_page,
                    "section_preview_snippet": chunk_text[:150],  # hover tooltip preview
                }
            )

    # build TransparencyInfo for the retrieval transparency panel.
    # strategy_used is inferred from primary_strategy and retry state.
    # confidence_level is not known here (determined by _split_response after streaming);
    # stream_answer() fills it in before emitting the 'transparency' SSE event.
    primary_strategy = state.get("primary_strategy") or ""
    transparency_augmented = state.get("transparency_augmented", False)
    if transparency_augmented:
        strategy_used = "augmented_hybrid"
    elif primary_strategy == "graph_node":
        strategy_used = "graph_traversal"
    elif primary_strategy == "comparative_node":
        strategy_used = "comparative"
    else:
        strategy_used = "hybrid_retrieval"

    # Count unique sections across context chunks (using already-fetched chunk_meta).
    section_count = 0
    if chunks_dicts:
        section_count = len({meta[0] for meta in chunk_meta.values() if meta[0] is not None})

    transparency_info: TransparencyInfo = {
        "strategy_used": strategy_used,
        "chunk_count": len(chunks_dicts),
        "section_count": section_count,
        "augmented": transparency_augmented,
    }

    # Estimate retrieval confidence from chunk scores so confidence_gate_node
    # can make an informed routing decision.  Before this fix the gate always
    # saw the initial "low" default (synthesize_node prepares the prompt but
    # does not call the LLM, so LLM-derived confidence is not available yet).
    retrieval_confidence = "low"
    if chunks_dicts:
        scores = sorted(
            (c.get("score", 0) for c in chunks_dicts),
            reverse=True,
        )
        top3_avg = sum(scores[:3]) / min(len(scores), 3)
        # RRF with k=60: max score ~0.033 (rank 1 in both sources).
        # 0.025+ = strong matches in both sources; 0.015+ = decent single-source.
        if top3_avg >= 0.025:
            retrieval_confidence = "high"
        elif top3_avg >= 0.015:
            retrieval_confidence = "medium"

    # Return prompt fields for stream_answer() to call the LLM streaming directly.
    # This enables true token-by-token streaming: the first SSE token event is sent
    # as the LLM generates it, not after all tokens are buffered.
    return {
        "_llm_prompt": prompt,
        "_system_prompt": system_prompt,
        "confidence": retrieval_confidence,
        "source_citations": source_citations_out,
        "transparency": transparency_info,
    }
