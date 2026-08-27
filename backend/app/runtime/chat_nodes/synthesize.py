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

import asyncio
import logging

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.models import DocumentModel, ImageModel
from app.repos.document_repo import fetch_chunk_locations
from app.runtime.chat_nodes._shared import _get_system_prompt
from app.services import graph as _graph_module  # indirect: get_graph_service is patched
from app.services.context_packer import pack_context_indexed, resolve_context_budget
from app.services.qa import (
    CITATION_MIN_SCORE,
    CITATION_REL_RATIO,
    MAX_CITATIONS,
    _should_use_summary,
)
from app.services.summarizer import get_summarization_service
from app.types import ChatState, TransparencyInfo

logger = logging.getLogger(__name__)


def _cap_text_tokens(text: str, token_cap: int) -> str:
    """Trim *text* to roughly *token_cap* tokens on a word boundary.

    Same ~1.3 tokens-per-word approximation the section-context cap has always
    used. Applied to the OPTIONAL prompt injections only -- never to the packed
    chunk context, because an `[S3]` marker the model is told to cite must still
    have its passage present when the citation is resolved (I-33).
    """
    if token_cap <= 0 or not text:
        return text
    words = text.split()
    cap_words = int(token_cap / 1.3)
    if len(words) <= cap_words:
        return text
    return " ".join(words[:cap_words]) + " ..."


# Citation gating. A cited source should actually contain the text the user is
# sent to — a weakly-related chunk only pollutes the reference list. Cap the list
# and drop low-relevance sources, but always keep the single best source so a
# grounded answer never shows zero citations. RRF fusion scores top out ~0.033;
# a chunk far below the best (or below a small absolute floor) is noise.
# MAX_CITATIONS is shared with the LLM-authored chips so both lists under one
# answer obey the same cap.


# Cap injected visual descriptions so they inform the answer without crowding out
# the retrieved prose. image_ids are already scoped to the answer's documents by
# HybridRetriever.retrieve_with_images.
_MAX_IMAGE_CONTEXT = 4


async def _fetch_image_context(image_ids: list[str], doc_titles: dict[str, str]) -> str:
    """Format vision-analyzed image descriptions as a labeled context block.

    Skips decorative images (no informational content). Returns "" when no
    described, non-decorative images are found so the prompt is unchanged.
    """
    if not image_ids:
        return ""
    async with get_session_factory()() as session:
        rows = await session.execute(
            select(ImageModel).where(
                ImageModel.id.in_(image_ids),
                ImageModel.description.is_not(None),
                ImageModel.image_type != "decorative",
            )
        )
        images = list(rows.scalars().all())

    if not images:
        return ""

    # Preserve retrieval rank: image_ids arrive best-first from the retriever.
    order = {iid: i for i, iid in enumerate(image_ids)}
    images.sort(key=lambda im: order.get(im.id, len(order)))

    lines: list[str] = []
    for img in images[:_MAX_IMAGE_CONTEXT]:
        title = doc_titles.get(img.document_id, "")
        kind = (img.image_type or "image").replace("_", " ")
        where = f" | Document: {title}" if title else ""
        lines.append(f"[Figure ({kind}){where}]\n{img.description}")

    return "The following figures appear in the source material:\n\n" + "\n\n".join(lines)


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
    """Return {chunk_id: (section_id, pdf_page_number, pdf_page_label, heading)}.

    Kept as a name because `chat_graph` re-exports it. The query itself lives in
    the repo layer so the `/qa` citation path resolves location identically --
    the two lists render side by side under one answer and must not disagree
    about which section a chunk is in.
    """
    return await fetch_chunk_locations(chunk_ids)


async def _fetch_contradiction_context(doc_ids: list[str]) -> str:
    """Return a formatted context block of SAME_CONCEPT contradictions for the given documents.

    Fetches SAME_CONCEPT edges with contradiction=True that involve any of the given doc_ids.
    Looks up publication_year to include '[YYYY source preferred]' when available.
    Returns empty string if no contradictions exist or on any error.
    Caps output at 3 contradictions to avoid prompt bloat.
    """

    try:
        svc = _graph_module.get_graph_service()
        # Kuzu is synchronous: keep it off the event loop (I-2). The contradiction
        # + doc-scope filter is done in Cypher, so only the edges we'll actually
        # use cross into Python (was: scan every SAME_CONCEPT edge in the library
        # and filter here).
        relevant = await asyncio.to_thread(
            svc.get_contradiction_edges_for_docs, doc_ids
        )
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

    # Resolved before the first log line, not after it: this used to print the
    # configured QA_CONTEXT_TOKEN_BUDGET while the pack below ran at the
    # slow-host one, so the two `synthesize_node:` lines disagreed about the
    # budget on exactly the hosts the profile exists for -- and both are what
    # scripts/diagnose-slow-host.sh pastes.
    token_budget, budget_reason = resolve_context_budget()

    logger.info(
        "synthesize_node: intent=%s chunks=%d section_context=%s budget=%d (%s)",
        intent,
        len(chunks_dicts),
        "yes" if section_context else "no",
        token_budget,
        budget_reason,
    )

    # Assemble chunk context using the pure context packer (dedup + section grouping).
    # Indexed: each chunk carries an [S<n>] marker so a citation can name the chunk
    # it came from and have its excerpt filled in from that chunk (I-33).
    chunks_context, cited_chunks = (
        pack_context_indexed(chunks_dicts, token_budget=token_budget)
        if chunks_dicts
        else ("", [])
    )
    logger.info(
        "synthesize_node: packed %d/%d passages into %d chars at budget %d (%s)",
        len(cited_chunks),
        len(chunks_dicts),
        len(chunks_context),
        token_budget,
        budget_reason,
    )

    # section_context (graph results, executive summary): the same cap as every
    # other optional injection, through the same helper. It was an open-coded
    # copy of _cap_text_tokens against a literal 1000, which is the number
    # QA_SUMMARY_INJECTION_TOKEN_CAP was chosen to match -- two places to change
    # for one decision.
    context_parts: list[str] = []
    if section_context:
        section_context = _cap_text_tokens(
            section_context, get_settings().QA_SUMMARY_INJECTION_TOKEN_CAP
        )
        context_parts.append(section_context)

    if chunks_context:
        context_parts.append(chunks_context)

    context = "\n\n---\n\n".join(context_parts) if context_parts else ""

    # Inject vision-analyzed figure descriptions so diagrams/charts/code
    # screenshots inform the answer, not just retrieval. Must happen before the
    # prompt is assembled below.
    image_ids = state.get("image_ids") or []
    if image_ids:
        try:
            image_doc_titles = await _fetch_doc_titles_for_chunks(chunks_dicts)
            image_context = await _fetch_image_context(image_ids, image_doc_titles)
            if image_context:
                image_context = _cap_text_tokens(
                    image_context, get_settings().QA_SUMMARY_INJECTION_TOKEN_CAP
                )
                context = f"{context}\n\n---\n\n{image_context}" if context else image_context
                logger.info(
                    "synthesize_node: injected image context (%d chars)", len(image_context)
                )
        except Exception:
            logger.debug("synthesize_node: image context fetch failed", exc_info=True)

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
                # Uncapped until 2026-08-27: `_should_use_summary` is a keyword
                # match, so this fires on exactly the questions asked of long
                # documents and prepended a whole cached summary past the context
                # budget. The budget bounded chunks_context only.
                summary_text = _cap_text_tokens(
                    exec_summary.content, get_settings().QA_SUMMARY_INJECTION_TOKEN_CAP
                )
                context = f"[Document Summary]\n{summary_text}\n\n---\n\n{context}"
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

    # Inject SAME_CONCEPT contradiction context for scope=all. Must happen before
    # the prompt is assembled below, or it never reaches the LLM.
    if scope == "all" and state.get("doc_ids"):
        try:
            contradiction_ctx = await _fetch_contradiction_context(state["doc_ids"])
            if contradiction_ctx:
                contradiction_ctx = _cap_text_tokens(
                    contradiction_ctx, get_settings().QA_SUMMARY_INJECTION_TOKEN_CAP
                )
                context = contradiction_ctx + "\n\n---\n\n" + context
                logger.info(
                    "synthesize_node: injected contradiction context (%d chars)",
                    len(contradiction_ctx),
                )
        except Exception:
            logger.debug("synthesize_node: contradiction context fetch failed", exc_info=True)

    if history_block:
        prompt = f"{history_block}\n\nContext:\n\n{context}\n\nQuestion: {question}"
    else:
        prompt = f"Context:\n\n{context}\n\nQuestion: {question}"
    system_prompt = _get_system_prompt(intent)

    # Prefill is ~linear in prompt size and is the whole wait on a CPU-only host,
    # yet nothing reported what the prompt actually weighed -- only what the chunk
    # packer contributed, which is one of five additive sources. Approximate
    # (~1.3 tokens/word) on purpose: an exact count costs a tokenizer pass on every
    # answer to inform a log line.
    _approx_prompt_tokens = int(len((prompt + system_prompt).split()) * 1.3)
    _ceiling = get_settings().QA_PROMPT_TOKEN_CEILING
    if _ceiling and _approx_prompt_tokens > _ceiling:
        logger.warning(
            "synthesize_node: prompt ~%d tokens exceeds ceiling %d (context %d chars, "
            "budget %d) -- an injection is outgrowing the context budget",
            _approx_prompt_tokens,
            _ceiling,
            len(context),
            token_budget,
        )
    else:
        logger.info("synthesize_node: prompt ~%d tokens", _approx_prompt_tokens)

    # For library-wide factual/exploratory queries, instruct the LLM to attribute sources
    if scope == "all" and intent in ("factual", "exploratory"):
        system_prompt = (
            system_prompt + "\n\nThe user is asking about their entire library. "
            "Answer using only the provided passages. "
            "If the passages come from multiple documents, synthesise across them. "
            "Be explicit about which document each point comes from."
        )

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
    chunk_meta: dict = {}  # chunk_id -> (section_id, pdf_page, pdf_page_label, heading)
    source_citations_out: list[dict] = []
    if chunks_dicts:
        # Rank by retrieval score so the best sources lead and the cap keeps the
        # strongest. Gate out weakly-related chunks (relative to the best, with a
        # small absolute floor) but always keep the single best source.
        ranked = sorted(chunks_dicts, key=lambda c: c.get("score", 0.0), reverse=True)
        top_score = ranked[0].get("score", 0.0)
        floor = max(CITATION_MIN_SCORE, top_score * CITATION_REL_RATIO)

        chunk_ids = [c["chunk_id"] for c in ranked if c.get("chunk_id")]
        chunk_meta = await _fetch_section_ids_and_pages_for_chunks(chunk_ids)
        doc_titles_map = await _fetch_doc_titles_for_chunks(ranked)

        seen_dedup_keys: set[str] = set()
        for c in ranked:
            if len(source_citations_out) >= MAX_CITATIONS:
                break
            # Always keep the best source; gate the rest on relevance.
            if source_citations_out and c.get("score", 0.0) < floor:
                continue
            cid = c.get("chunk_id", "")
            meta = chunk_meta.get(cid, (None, None, None, None))
            section_id, pdf_page, pdf_page_label, db_heading = meta
            doc_id = c.get("document_id", "")
            doc_title = doc_titles_map.get(doc_id, "")
            # The retrieved chunk's heading is always empty: embed_node writes
            # `"section_heading": ""` into every vector row, so the field exists
            # in the index and never carries anything. Measured on a real
            # answer, that left four citations on one page indistinguishable --
            # same title, same number, nothing to tell them apart. The section
            # row is the only place the heading actually lives.
            section_heading = (db_heading or c.get("section_heading", "") or "").strip()

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
                    # What the sheet is printed as, when the book numbers its
                    # front matter separately. The chip shows this; it still
                    # navigates by pdf_page_number, which is what the viewer
                    # scrolls to.
                    "pdf_page_label": pdf_page_label,
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
        "cited_chunks": cited_chunks,
        "transparency": transparency_info,
    }
