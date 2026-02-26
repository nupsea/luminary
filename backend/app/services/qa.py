"""Grounded Q&A service — retrieval, citation extraction, Phoenix tracing."""

import json
import logging
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.models import DocumentModel, QAHistoryModel
from app.services.llm import get_llm_service
from app.services.retriever import get_retriever
from app.telemetry import get_tracer
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

    The LLM appends ``{"citations": [...], "confidence": "..."}`` after the prose answer.
    Finds the last occurrence of the citations JSON marker and parses from there.
    """
    marker = '{"citations":'
    idx = full_text.rfind(marker)
    if idx == -1:
        return full_text.strip(), [], "low"

    answer = full_text[:idx].strip()
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
        """
        settings = get_settings()
        effective_model = model or settings.LITELLM_DEFAULT_MODEL
        tracer = get_tracer()
        retriever = get_retriever()
        llm = get_llm_service()

        # Retrieve top-10 chunks with tracing
        with tracer.start_as_current_span("retrieve") as span:
            effective_doc_ids = document_ids if scope == "single" else None
            span.set_attribute("query", question)
            span.set_attribute("scope", scope)
            chunks = await retriever.retrieve(question, effective_doc_ids, k=10)
            span.set_attribute("chunk_count", len(chunks))

        # No-context guard: retrieval returned 0 chunks (stores empty or doc not ingested).
        if not chunks:
            logger.warning("stream_answer: no chunks retrieved", extra={"question": question})
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

        # Generate with tracing — collect full response to parse citations
        with tracer.start_as_current_span("generate") as span:
            span.set_attribute("model_name", effective_model)
            span.set_attribute("query", question)
            span.set_attribute("document_id", document_ids[0] if document_ids else "all")
            span.set_attribute("chunk_count", len(chunks))
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
                yield (
                    'data: {"error": "llm_unavailable", '
                    '"message": "Ollama is not running or unreachable. '
                    'Start it with: ollama serve", "done": true}\n\n'
                )
                return

        full_text = "".join(collected)

        # NOT_FOUND check — return without streaming any tokens
        if NOT_FOUND_SENTINEL in full_text:
            await self._store_qa(question, None, [], "low", None, scope, effective_model)
            yield f'data: {json.dumps({"done": True, "not_found": True})}\n\n'
            return

        # Parse citations JSON from the end of the response
        answer_text, citations, confidence = _split_response(full_text)

        # Stream answer as token events (word granularity)
        for word in answer_text.split():
            yield f'data: {json.dumps({"token": word + " "})}\n\n'

        # Persist Q&A history
        first_doc_id = document_ids[0] if document_ids else None
        qa_id = await self._store_qa(
            question, answer_text, citations, confidence, first_doc_id, scope, effective_model
        )

        # Final SSE event with citations and metadata
        final = {"done": True, "answer": answer_text, "citations": citations,
                 "confidence": confidence, "qa_id": qa_id}
        yield f"data: {json.dumps(final)}\n\n"


_qa_service: QAService | None = None


def get_qa_service() -> QAService:
    global _qa_service
    if _qa_service is None:
        _qa_service = QAService()
    return _qa_service
