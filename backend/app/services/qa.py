"""Grounded Q&A service — retrieval, citation extraction, Phoenix tracing.

V2: stream_answer() invokes the LangGraph chat router (app/runtime/chat_graph.py).
The graph handles: intent classification, query rewriting, retrieval, LLM call,
citation enrichment.  stream_answer() remains the thin SSE streaming layer.
"""

import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator

import litellm
from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.models import DocumentModel, QAHistoryModel
from app.services.graph import get_graph_service
from app.services.llm import get_llm_service
from app.telemetry import trace_chain
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


_SUMMARY_INTENT_KEYWORDS: frozenset[str] = frozenset({
    "summarize", "summary", "summaries", "overview", "key points",
    "what is this about", "main idea", "main ideas", "brief", "briefly",
    "gist", "outline", "recap",
})


def _should_use_summary(question: str) -> bool:
    """Return True if the question has summary-intent keywords."""
    q = question.lower()
    return any(kw in q for kw in _SUMMARY_INTENT_KEYWORDS)


QA_SYSTEM_PROMPT = (
    "You are a grounded knowledge assistant. "
    "Answer only using the provided context. "
    f"If the answer is not present, respond exactly: {NOT_FOUND_SENTINEL}. "
    "Do not speculate. "
    "Write your answer as Markdown prose (use **bold**, bullet lists, and headings where helpful). "
    "Then on a new line write this JSON: "
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
        answer = full_text.strip()
        # Default confidence based on answer length: short/empty answers are low,
        # substantive answers without a JSON block default to medium.
        confidence = "medium" if len(answer) > 80 else "low"
        return answer, [], confidence

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

    citations: list[dict] = [c for c in parsed.get("citations", []) if isinstance(c, dict)]
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
    """Retrieve → ground → cite → stream answer over SSE.

    V2: delegates to the LangGraph chat router.  stream_answer() is the thin
    SSE streaming wrapper; all retrieval, LLM, and citation logic lives inside
    the graph nodes (app/runtime/chat_graph.py).
    """

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

        V2: invokes the LangGraph chat router and streams the answer from the
        graph result.  The SSE format is identical to V1:
          data: {"token": "..."}\\n\\n   — one token event per word
          data: {"done": true, ...}\\n\\n — final event with citations/confidence
          data: {"error": "...", ...}\\n\\n — on error

        All exceptions are caught and yielded as SSE error events so the HTTP
        stream is never silently dropped.
        """
        try:
            settings = get_settings()
            effective_model = model or settings.LITELLM_DEFAULT_MODEL

            with trace_chain("qa.answer", input_value=question) as root_span:
                root_span.set_attribute("qa.scope", scope)
                root_span.set_attribute("qa.model", effective_model)
                if document_ids:
                    root_span.set_attribute("qa.document_ids", ", ".join(document_ids))

                from app.runtime.chat_graph import get_chat_graph  # noqa: PLC0415

                graph = get_chat_graph()

                initial_state: dict = {
                    "question": question,
                    "doc_ids": document_ids or [],
                    "scope": scope,
                    "model": model,
                    "intent": None,
                    "rewritten_question": None,
                    "chunks": [],
                    "section_context": None,
                    "answer": "",
                    "citations": [],
                    "confidence": "low",
                    "not_found": False,
                    "_llm_prompt": None,
                    "_system_prompt": None,
                    "retry_attempted": False,
                    "primary_strategy": None,
                }

                try:
                    result = await graph.ainvoke(initial_state)
                except Exception as exc:
                    root_span.set_attribute("error", True)
                    root_span.set_attribute("error.message", "llm_unavailable")
                    if isinstance(exc, ValueError):
                        msg = "LLM provider not configured. Add your API key in Settings."
                    elif isinstance(exc, litellm.AuthenticationError):
                        msg = "LLM API key is invalid. Check your key in Settings."
                    else:
                        msg = "LLM service unavailable. If using Ollama, run: ollama serve"
                    payload = {"error": "llm_unavailable", "message": msg, "done": True}
                    yield f"data: {json.dumps(payload)}\n\n"
                    return

                root_span.set_attribute("qa.intent", result.get("intent") or "")

                chunks_returned = result.get("chunks") or []

                if result.get("not_found"):
                    if not chunks_returned:
                        # No context retrieved — surface as a distinct error
                        root_span.set_attribute("error", True)
                        root_span.set_attribute("error.message", "no_context")
                        yield (
                            'data: {"error": "no_context", '
                            '"message": "No relevant content found. '
                            'Make sure a document has been ingested.", "done": true}\n\n'
                        )
                    else:
                        # Chunks present but LLM could not find the answer
                        await self._store_qa(
                            question, None, [], "low", None, scope, effective_model
                        )
                        root_span.set_attribute("qa.not_found", True)
                        yield f'data: {json.dumps({"done": True, "not_found": True})}\n\n'
                    return

            # --- Post-graph: stream answer tokens outside the trace span ---
            #
            # Two paths:
            #   (A) Pass-through: a strategy node (e.g. summary_node with cached exec summary)
            #       set state['answer'] directly.  Stream that answer word-by-word.
            #   (B) LLM streaming: synthesize_node prepared _llm_prompt/_system_prompt.
            #       Call the LLM streaming here so the SSE client receives tokens as they
            #       are generated, not after the full response is buffered.
            first_doc_id = document_ids[0] if document_ids else None
            llm_prompt = result.get("_llm_prompt")

            if llm_prompt:
                # Path B — true streaming: call LLM here, yield tokens progressively
                system_prompt = result.get("_system_prompt") or ""
                llm = get_llm_service()
                try:
                    token_gen = await llm.generate(
                        llm_prompt, system=system_prompt, model=effective_model, stream=True
                    )
                except (
                    litellm.ServiceUnavailableError,
                    ValueError,
                    litellm.AuthenticationError,
                ) as exc:
                    if isinstance(exc, ValueError):
                        msg = "LLM provider not configured. Add your API key in Settings."
                    elif isinstance(exc, litellm.AuthenticationError):
                        msg = "LLM API key is invalid. Check your key in Settings."
                    else:
                        msg = "LLM service unavailable. If using Ollama, run: ollama serve"
                    payload = {"error": "llm_unavailable", "message": msg, "done": True}
                    yield f"data: {json.dumps(payload)}\n\n"
                    return

                # Stream tokens as they arrive; stop before the citation JSON block.
                # NOT_FOUND_SENTINEL detection prevents yielding the sentinel text as tokens.
                collected: list[str] = []
                full_text_so_far = ""
                async for token in token_gen:
                    collected.append(token)
                    full_text_so_far += token
                    # Stop streaming tokens once we hit the citation JSON block or sentinel
                    if re.search(r'\{"citations"|\{"answer"', full_text_so_far):
                        break
                    if NOT_FOUND_SENTINEL in full_text_so_far:
                        break
                    yield f"data: {json.dumps({'token': token})}\n\n"

                # Drain any remaining tokens for full_text computation
                async for token in token_gen:
                    collected.append(token)

                full_text = "".join(collected)

                if NOT_FOUND_SENTINEL in full_text:
                    await self._store_qa(question, None, [], "low", None, scope, effective_model)
                    yield f'data: {json.dumps({"done": True, "not_found": True})}\n\n'
                    return

                answer_text, citations, confidence = _split_response(full_text)

                # Enrich citations with document titles
                scored_chunks_for_citation = [
                    ScoredChunk(
                        chunk_id=c.get("chunk_id", ""),
                        document_id=c.get("document_id", ""),
                        text=c.get("text", ""),
                        section_heading=c.get("section_heading", ""),
                        page=c.get("page", 0),
                        score=c.get("score", 0.0),
                        source=c.get("source", "vector"),  # type: ignore[arg-type]
                    )
                    for c in chunks_returned
                ]
                chunk_doc_ids = list(
                    {c["document_id"] for c in chunks_returned if c.get("document_id")}
                )
                doc_titles = await self._fetch_doc_titles(chunk_doc_ids)
                citations = _enrich_citation_titles(
                    citations, scored_chunks_for_citation, doc_titles, scope
                )

            else:
                # Path A — pass-through: strategy node set answer directly
                answer_text = result.get("answer") or ""
                for word in answer_text.split():
                    yield f'data: {json.dumps({"token": word + " "})}\n\n'
                citations = result.get("citations") or []
                confidence = result.get("confidence") or "low"

            # Persist Q&A history and yield final SSE event
            qa_id = await self._store_qa(
                question, answer_text, citations, confidence, first_doc_id, scope, effective_model
            )
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
    global _qa_service  # noqa: PLW0603
    if _qa_service is None:
        _qa_service = QAService()
    return _qa_service
