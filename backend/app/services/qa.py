"""Grounded Q&A service — retrieval, citation extraction, Phoenix tracing."""

import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.models import DocumentModel, QAHistoryModel
from app.services.graph import get_graph_service
from app.services.llm import get_llm_service
from app.services.retriever import get_retriever
from app.telemetry import trace_chain, trace_retrieval
from app.types import ScoredChunk

logger = logging.getLogger(__name__)

NOT_FOUND_SENTINEL = "NOT_FOUND_IN_CONTENT"

# ---------------------------------------------------------------------------
# Query rewriting — resolve vague pronouns via Kuzu entity lookup
# ---------------------------------------------------------------------------

VAGUE_REF_RE = re.compile(
    r"\b(they|he|she|it|them|the author|the speaker|the protagonist|"
    r"the character|the narrator|the writer|both|the two|someone|anyone)\b",
    re.IGNORECASE,
)

_REWRITE_SYSTEM = (
    "Rewrite the question replacing vague references with specific names from the list. "
    "Return only the rewritten question, no explanation."
)


async def _maybe_rewrite_query(
    question: str, document_ids: list[str] | None
) -> str:
    """Return a (possibly rewritten) query with vague references resolved.

    Contract:
    - No vague refs detected → returns question unchanged (0 LLM calls, 0 Kuzu queries).
    - document_ids is None (all-docs scope) → returns question unchanged.
    - Kuzu returns 0 entities → returns question unchanged.
    - LLM fails → logs warning and returns question unchanged (non-fatal).
    """
    if VAGUE_REF_RE.search(question) is None:
        return question
    if document_ids is None:
        return question
    try:
        entity_names = get_graph_service().get_entities_for_documents(document_ids)
    except Exception:
        logger.warning("_maybe_rewrite_query: Kuzu lookup failed", exc_info=True)
        return question
    if not entity_names:
        return question
    try:
        llm = get_llm_service()
        prompt = (
            f"Question: {question}\n"
            f"Available names: {', '.join(entity_names)}"
        )
        result = await llm.generate(prompt, system=_REWRITE_SYSTEM, stream=False)
        rewritten = str(result).strip()
        if rewritten:
            return rewritten
    except Exception:
        logger.warning("_maybe_rewrite_query: LLM rewrite failed", exc_info=True)
    return question


def _enrich_citation_titles(
    citations: list[dict],
    chunks: list[ScoredChunk],
    doc_titles: dict[str, str],
    scope: str,
) -> list[dict]:
    """Populate (or clear) document_title in each citation.

    scope='single' — set document_title=None on all citations (redundant when
    the user is already reading a specific document).

    scope='all' — match each citation to a retrieved chunk by
    (section_heading, page) and fill in the authoritative title from doc_titles.
    If no chunk matches, keep whatever the LLM put in (graceful degradation).
    """
    if scope == "single":
        for c in citations:
            c["document_title"] = None
        return citations

    # Build lookup: (section_heading, page) -> document_id  (first match wins)
    chunk_index: dict[tuple[str, int], str] = {}
    for chunk in chunks:
        key = (chunk.section_heading, chunk.page)
        if key not in chunk_index:
            chunk_index[key] = chunk.document_id

    for c in citations:
        heading = (c.get("section_heading") or "").strip()
        page = int(c.get("page") or 0)
        doc_id = chunk_index.get((heading, page))
        if doc_id and doc_id in doc_titles:
            c["document_title"] = doc_titles[doc_id]

    return citations


QA_SYSTEM_PROMPT = (
    "You are a grounded knowledge assistant. "
    "Answer only using the provided context. "
    f"If the answer is not present, respond exactly: {NOT_FOUND_SENTINEL}. "
    "Do not speculate. "
    "Write your answer as prose. Then on a new line write this JSON: "
    '{"citations":[{"document_title":"...","section_heading":"...","page":0,"excerpt":"..."}],'
    '"confidence":"high|medium|low"}'
)


def _build_context(chunks: list[ScoredChunk], doc_titles: dict[str, str]) -> str:
    """Format retrieved chunks as a numbered context block."""
    parts: list[str] = []
    for chunk in chunks:
        title = doc_titles.get(chunk.document_id, chunk.document_id)
        heading = chunk.section_heading or "—"
        parts.append(
            f"[Document: {title} | Section: {heading} | Page: {chunk.page}]\n{chunk.text}"
        )
    return "\n\n---\n\n".join(parts)


def _split_response(full_text: str) -> tuple[str, list[dict], str]:
    """Extract (answer_text, citations, confidence) from the LLM response.

    The LLM is instructed to write prose then append a JSON citations block.
    Two output styles are handled:
      Style A: [prose]\\n{"citations": [...], "confidence": "..."}
      Style B: {"answer": "...", "citations": [...], "confidence": "..."}
               (some models embed the answer inside the JSON)
    """
    # Find the last JSON block containing our citations payload.
    json_start = -1
    for pattern in (r'\{\s*"citations"\s*:', r'\{\s*"answer"\s*:'):
        matches = list(re.finditer(pattern, full_text, re.DOTALL))
        if matches:
            json_start = matches[-1].start()
            break

    if json_start == -1:
        return full_text.strip(), [], "low"

    # Parse the JSON block, tolerating truncation.
    parsed: dict = {}
    json_text = full_text[json_start:]
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        end = json_text.rfind("}")
        if end != -1:
            try:
                parsed = json.loads(json_text[: end + 1])
            except json.JSONDecodeError:
                pass

    citations: list[dict] = parsed.get("citations", [])
    confidence: str = parsed.get("confidence", "low")

    # Style B: answer is embedded in the JSON.
    if "answer" in parsed and isinstance(parsed["answer"], str):
        return parsed["answer"].strip(), citations, confidence

    # Style A: prose precedes the JSON block.
    prose = full_text[:json_start].strip()
    # Strip any trailing lines that are format labels, not answer content.
    # LLMs sometimes echo instruction fragments (e.g. "JSON:", "Here is the JSON:",
    # "ONLY JSON (no prose ...):") — these always contain the word "json".
    lines = prose.split("\n")
    while lines and re.search(r"\bjson\b", lines[-1], re.IGNORECASE):
        lines.pop()
    return "\n".join(lines).strip(), citations, confidence


class QAService:
    """Retrieve → ground → cite → stream answer over SSE."""

    async def _fetch_doc_titles(self, document_ids: list[str]) -> dict[str, str]:
        if not document_ids:
            return {}
        async with get_session_factory()() as session:
            result = await session.execute(
                select(DocumentModel.id, DocumentModel.title).where(
                    DocumentModel.id.in_(document_ids)
                )
            )
            return {row.id: row.title for row in result}

    async def _store_qa(
        self,
        question: str,
        answer: str | None,
        citations: list[dict],
        confidence: str,
        document_id: str | None,
        scope: str,
        model_used: str,
    ) -> str:
        qa_id = str(uuid.uuid4())
        async with get_session_factory()() as session:
            session.add(
                QAHistoryModel(
                    id=qa_id,
                    document_id=document_id,
                    scope=scope,
                    question=question,
                    answer=answer or "",
                    citations=citations,
                    confidence=confidence,
                    model_used=model_used,
                )
            )
            await session.commit()
        return qa_id

    async def stream_answer(
        self,
        question: str,
        document_ids: list[str] | None,
        scope: str,
        model: str | None,
    ) -> AsyncGenerator[str]:
        """Async generator of SSE event strings.

        Yields ``data: {"token": "..."}\\n\\n`` for each answer word.
        Yields a final ``data: {"done": true, ...}\\n\\n`` event with citations.
        On NOT_FOUND: yields ``data: {"done": true, "not_found": true}\\n\\n``.

        All exceptions are caught and yielded as SSE error events so the HTTP
        stream is never silently dropped (which causes a generic frontend error).
        """
        try:
            settings = get_settings()
            effective_model = model or settings.LITELLM_DEFAULT_MODEL
            retriever = get_retriever()
            llm = get_llm_service()

            # Top-level CHAIN span for the entire Q&A journey
            with trace_chain("qa.answer", input_value=question) as root_span:
                root_span.set_attribute("qa.scope", scope)
                root_span.set_attribute("qa.model", effective_model)
                if document_ids:
                    root_span.set_attribute("qa.document_ids", ", ".join(document_ids))

                # Hybrid retrieval — RETRIEVER span
                # Rewrite vague-reference queries using Kuzu entities (non-fatal).
                # Use the rewritten query for retrieval but the original in the LLM prompt.
                with trace_retrieval("hybrid", query=question) as ret_span:
                    effective_doc_ids = document_ids if scope == "single" else None
                    retrieval_question = await _maybe_rewrite_query(question, effective_doc_ids)
                    if retrieval_question != question:
                        logger.info(
                            "stream_answer: query rewritten for retrieval",
                            extra={"original": question, "rewritten": retrieval_question},
                        )
                    ret_span.set_attribute("retrieval.scope", scope)
                    chunks = await retriever.retrieve(retrieval_question, effective_doc_ids, k=10)
                    ret_span.set_attribute("retrieval.chunk_count", len(chunks))
                    if chunks:
                        ret_span.set_attribute("retrieval.top_score", round(chunks[0].score, 4))

                # No-context guard
                if not chunks:
                    logger.warning(
                        "stream_answer: no chunks retrieved",
                        extra={"question": question},
                    )
                    root_span.set_attribute("error", True)
                    root_span.set_attribute("error.message", "no_context")
                    yield (
                        'data: {"error": "no_context", '
                        '"message": "No relevant content found. '
                        'Make sure a document has been ingested.", "done": true}\n\n'
                    )
                    return

                # Build context string
                all_doc_ids = list({c.document_id for c in chunks})
                doc_titles = await self._fetch_doc_titles(all_doc_ids)
                context = _build_context(chunks, doc_titles)
                prompt = f"Context:\n\n{context}\n\nQuestion: {question}"

                # LLM generation — LiteLLM is auto-instrumented so the LLM child
                # span appears automatically; this block just handles error routing.
                try:
                    token_gen = await llm.generate(
                        prompt, system=QA_SYSTEM_PROMPT, model=model, stream=True
                    )
                    collected: list[str] = []
                    async for token in token_gen:
                        collected.append(token)
                except Exception as exc:
                    logger.warning(
                        "stream_answer: LLM call failed",
                        extra={"model": effective_model},
                        exc_info=exc,
                    )
                    root_span.set_attribute("error", True)
                    root_span.set_attribute("error.message", "llm_unavailable")
                    yield (
                        'data: {"error": "llm_unavailable", '
                        '"message": "Ollama is not running or unreachable. '
                        'Start it with: ollama serve", "done": true}\n\n'
                    )
                    return

                full_text = "".join(collected)

                # NOT_FOUND check
                if NOT_FOUND_SENTINEL in full_text:
                    await self._store_qa(question, None, [], "low", None, scope, effective_model)
                    root_span.set_attribute("qa.not_found", True)
                    yield f'data: {json.dumps({"done": True, "not_found": True})}\n\n'
                    return

                # Parse citations JSON from the end of the response
                answer_text, citations, confidence = _split_response(full_text)
                # Authoritative document_title population from DB titles
                citations = _enrich_citation_titles(citations, chunks, doc_titles, scope)

                # Record the answer on the root span for Phoenix to show Q→A
                root_span.set_attribute("output.value", answer_text[:2000])
                root_span.set_attribute("qa.confidence", confidence)
                root_span.set_attribute("qa.citation_count", len(citations))

            # Stream answer as token events (word granularity)
            # NOTE: streaming happens outside the trace_chain block intentionally —
            # the span is closed once we have the full answer (before streaming starts).
            for word in answer_text.split():
                yield f'data: {json.dumps({"token": word + " "})}\n\n'

            # Persist Q&A history
            first_doc_id = document_ids[0] if document_ids else None
            qa_id = await self._store_qa(
                question, answer_text, citations, confidence, first_doc_id, scope, effective_model
            )

            # Final SSE event with citations and metadata
            final = {
                "done": True,
                "answer": answer_text,
                "citations": citations,
                "confidence": confidence,
                "qa_id": qa_id,
            }
            yield f"data: {json.dumps(final)}\n\n"

        except Exception as exc:
            logger.error("stream_answer: unhandled error", exc_info=exc)
            payload = {"error": "internal", "message": str(exc), "done": True}
            yield f"data: {json.dumps(payload)}\n\n"


_qa_service: QAService | None = None


def get_qa_service() -> QAService:
    global _qa_service
    if _qa_service is None:
        _qa_service = QAService()
    return _qa_service
