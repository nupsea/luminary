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
from app.services.llm import get_llm_service
from app.services.retriever import get_retriever
from app.telemetry import get_tracer, trace_chain, trace_retrieval
from app.types import ScoredChunk

logger = logging.getLogger(__name__)

NOT_FOUND_SENTINEL = "NOT_FOUND_IN_CONTENT"

QA_SYSTEM_PROMPT = (
    "You are a grounded knowledge assistant. "
    "Answer only using the provided context. "
    f"If the answer is not present, respond exactly: {NOT_FOUND_SENTINEL}. "
    "Do not speculate. "
    'After your answer, output JSON: '
    '{"citations":[{"document_title":"...","section_heading":"...","page":0,"excerpt":"..."}],'
    '"confidence":"high|medium|low"}.'
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
    """Extract (answer_text, citations, confidence) from the full LLM response.

    The LLM appends a JSON block like ``{ "citations": [...], "confidence": "..." }``
    after the prose answer, sometimes preceded by a literal "JSON:" label.
    Uses a regex to locate the opening brace of that block regardless of spacing.
    """
    # Match the last occurrence of a JSON object that starts with a "citations" key,
    # tolerating any whitespace between { and "citations".
    pattern = re.compile(r'\{\s*"citations"\s*:', re.DOTALL)
    matches = list(pattern.finditer(full_text))
    if not matches:
        return full_text.strip(), [], "low"

    idx = matches[-1].start()
    # Strip the trailing "JSON:" label the LLM sometimes emits before the block
    answer = re.sub(r"[Jj][Ss][Oo][Nn]\s*:\s*$", "", full_text[:idx]).strip()
    json_text = full_text[idx:]
    try:
        parsed = json.loads(json_text)
        citations: list[dict] = parsed.get("citations", [])
        confidence: str = parsed.get("confidence", "low")
    except json.JSONDecodeError:
        citations = []
        confidence = "low"

    return answer, citations, confidence


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
                with trace_retrieval("hybrid", query=question) as ret_span:
                    effective_doc_ids = document_ids if scope == "single" else None
                    ret_span.set_attribute("retrieval.scope", scope)
                    chunks = await retriever.retrieve(question, effective_doc_ids, k=10)
                    ret_span.set_attribute("retrieval.chunk_count", len(chunks))
                    if chunks:
                        ret_span.set_attribute("retrieval.top_score", round(chunks[0].score, 4))

                # No-context guard
                if not chunks:
                    logger.warning("stream_answer: no chunks retrieved", extra={"question": question})
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
            yield f'data: {json.dumps({"error": "internal", "message": str(exc), "done": True})}\n\n'


_qa_service: QAService | None = None


def get_qa_service() -> QAService:
    global _qa_service
    if _qa_service is None:
        _qa_service = QAService()
    return _qa_service
