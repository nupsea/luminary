"""The /qa SSE stream: run the chat graph, stream the LLM answer, ground its citations.

The graph (app/runtime/chat_graph.py) classifies, retrieves and builds the prompt; this
module calls the LLM streaming so the first token reaches the client as it is generated.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from app.exceptions import DependencyUnavailable
from app.repos import qa_repo
from app.runtime import chat_graph
from app.services.llm import (
    LLMAPIConnectionError,
    LLMAuthenticationError,
    LLMNotFoundError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    get_llm_service,
)
from app.services.llm_routing import is_on_device
from app.services.qa import (
    NOT_FOUND_SENTINEL,
    QA_CREATIVE_SYSTEM_PROMPT,
    QA_CREATIVE_TEMPERATURE,
    QA_DIRECT_SYSTEM_PROMPT,
    _drop_ungrounded_citations,
    _enrich_citation_titles,
    _fill_citation_locations,
    _gate_and_rank_citations,
    _marker_prefix_holdback,
    _resolve_marker_citations,
    _split_response,
)
from app.telemetry import trace_chain
from app.types import ScoredChunk

logger = logging.getLogger(__name__)

# A graph node that renders a UI card sets state["answer"] = CARD_PREFIX + json;
# the stream then emits exactly {"card": ...} and {"done": true}, no tokens.
CARD_PREFIX = "__card__"
_STOP_MARKERS = ('{"citations"', '{"answer"', NOT_FOUND_SENTINEL)
_SOCRATIC_PREFIX = (
    "Before answering, start with one probing question (1-2 sentences) "
    "that activates the user's prior knowledge about this topic. "
    "Format: [Your probing question?]\n\n"
)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _llm_error_message(exc: Exception) -> str:
    if isinstance(exc, DependencyUnavailable):
        return exc.detail
    if isinstance(exc, ValueError):
        return "LLM provider not configured. Add your API key in Settings."
    if isinstance(exc, LLMAuthenticationError):
        return "LLM API key is invalid. Check your key in Settings."
    if isinstance(exc, LLMRateLimitError):
        return "Rate limit reached. Free tier quota exhausted — wait and retry, or switch provider."
    if isinstance(exc, LLMNotFoundError):
        return f"Model not found ({type(exc).__name__}). Check the model name in Settings."
    if isinstance(exc, (LLMServiceUnavailableError, LLMAPIConnectionError)):
        return (
            "LLM unreachable. Check your network or Settings — if using Ollama, run: ollama serve"
        )
    return f"LLM error ({type(exc).__name__}). Check backend logs and Settings."


def _llm_error_event(exc: Exception) -> str:
    return _sse(
        {
            "type": "error",
            "error": "llm_unavailable",
            "message": _llm_error_message(exc),
            "done": True,
        }
    )


def _store_model_for(model: str | None) -> str:
    # model_used is NOT NULL. `model` itself must stay None for cloud routing so
    # LLMService picks up the DB-cached API key rather than settings (empty in Docker).
    try:
        from app.services.settings_service import get_effective_routing  # noqa: PLC0415

        return model or get_effective_routing()[0]
    except Exception:
        return model or "unknown"


async def _offline_notice(model: str | None, store_model: str) -> str | None:
    """A notice when a routed cloud answer will run locally because the provider is down."""
    if model is not None or not store_model or store_model.startswith("ollama/"):
        return None
    from app.services.connectivity import is_cloud_model, provider_reachable  # noqa: PLC0415

    if is_cloud_model(store_model) and not await asyncio.to_thread(provider_reachable, store_model):
        return _sse(
            {
                "type": "notice",
                "level": "offline",
                "message": (
                    "No internet connection — answering with the local model "
                    "instead of the cloud provider."
                ),
            }
        )
    return None


def _initial_state(
    question: str,
    document_ids: list[str] | None,
    scope: str,
    model: str | None,
    direct: bool,
    conversation_history: list[dict] | None,
    web_enabled: bool,
) -> dict:
    return {
        "question": question,
        "doc_ids": document_ids or [],
        "scope": scope,
        "model": model,
        "direct": direct,
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
        "conversation_history": conversation_history or [],
        "image_ids": [],
        "web_enabled": web_enabled,
        "web_calls_used": 0,
        "web_snippets": [],
        "source_citations": [],
        "transparency": None,
        "transparency_augmented": False,
    }


def _card_events(raw_answer: str) -> list[str]:
    try:
        card_payload = json.loads(raw_answer[len(CARD_PREFIX) :])
    except json.JSONDecodeError:
        card_payload = {"type": "error", "error": "Malformed card payload"}
    return [_sse({"card": card_payload}), _sse({"done": True})]


def _system_prompt_for(
    result: dict, direct: bool, creative: bool, socratic: bool
) -> tuple[str, float | None]:
    system_prompt = result.get("_system_prompt") or ""
    temperature: float | None = None
    if direct:
        system_prompt = QA_DIRECT_SYSTEM_PROMPT
        if creative:
            temperature = QA_CREATIVE_TEMPERATURE
        if socratic:
            system_prompt = _SOCRATIC_PREFIX + "[Full answer below]\n\n" + system_prompt
        return system_prompt, temperature
    if creative and system_prompt:
        system_prompt = QA_CREATIVE_SYSTEM_PROMPT
        temperature = QA_CREATIVE_TEMPERATURE
    if socratic and system_prompt:
        system_prompt = _SOCRATIC_PREFIX + "[Full answer with citations below]\n\n" + system_prompt
    return system_prompt, temperature


@dataclass
class _Generation:
    """What the LLM streamed: every token, and when the first arrived."""

    collected: list[str]
    ttft_seconds: float | None = None


def _first_marker(text: str) -> int | None:
    positions = [p for p in (text.find(m) for m in _STOP_MARKERS) if p != -1]
    return min(positions) if positions else None


def _record_token(gen: _Generation, token: str, t_llm: float) -> None:
    if gen.ttft_seconds is None:
        gen.ttft_seconds = time.perf_counter() - t_llm
        logger.info("[perf] LLM time-to-first-token: %.2fs", gen.ttft_seconds)
    gen.collected.append(token)


async def _stream_prose(token_gen, gen: _Generation, t_llm: float) -> AsyncGenerator[str]:
    """Yield prose token events, never the trailing citation JSON or not-found sentinel.

    A marker can be split across tokens, so a tail that could be a marker's prefix is
    held back until it either completes the marker (cut there) or stops matching.
    """
    text = ""
    emitted = 0
    async for token in token_gen:
        _record_token(gen, token, t_llm)
        text += token
        cut = _first_marker(text)
        if cut is not None:
            if cut > emitted:
                yield _sse({"token": text[emitted:cut]})
            async for rest in token_gen:  # drained so the full text can be parsed
                gen.collected.append(rest)
            return
        safe = len(text) - _marker_prefix_holdback(text, _STOP_MARKERS)
        if safe > emitted:
            yield _sse({"token": text[emitted:safe]})
            emitted = safe
    if len(text) > emitted:
        yield _sse({"token": text[emitted:]})


@dataclass
class _Grounded:
    citations: list[dict]
    dropped: int = 0
    proposed: int = 0
    gated: int = 0


async def _ground_citations(
    answer_text: str, citations: list[dict], result: dict, scope: str
) -> _Grounded:
    chunks_returned = result.get("chunks") or []
    scored_chunks = [
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
    chunk_doc_ids = list({c["document_id"] for c in chunks_returned if c.get("document_id")})
    doc_titles = await qa_repo.fetch_titles(chunk_doc_ids)

    # Marker citations resolve against the chunks put in the prompt; a retyped
    # excerpt falls back to verification against the grounding (I-33).
    citations, unresolved = _resolve_marker_citations(
        citations, result.get("cited_chunks") or [], doc_titles, answer_text
    )
    await _fill_citation_locations(citations)
    before_drop = len(citations)
    citations = _drop_ungrounded_citations(citations, _grounding_texts(result))
    dropped = (before_drop - len(citations)) + unresolved
    # The relevance gate is counted apart from grounding failures: it trims a
    # reference list, it does not reject an unsupported claim.
    proposed = len(citations)
    citations = _gate_and_rank_citations(citations)
    gated = proposed - len(citations)
    citations = _enrich_citation_titles(citations, scored_chunks, doc_titles, scope)
    return _Grounded(citations, dropped, proposed, gated)


def _grounding_texts(result: dict) -> list[str]:
    # Summary/graph routes ground on section_context with zero chunks.
    texts = [c.get("text", "") for c in result.get("chunks") or [] if c.get("text")]
    section_context = result.get("section_context")
    if section_context and section_context.strip():
        texts.append(section_context)
    return texts


def _transparency_event(result: dict, confidence: str) -> str | None:
    transparency = result.get("transparency")
    if not transparency:
        return None
    return _sse(
        {
            "type": "transparency",
            "confidence_level": confidence,
            "strategy_used": transparency.get("strategy_used", "hybrid_retrieval"),
            "chunk_count": transparency.get("chunk_count", 0),
            "section_count": transparency.get("section_count", 0),
            "augmented": transparency.get("augmented", False),
        }
    )


def _receipt(
    result: dict,
    served_model: str,
    ttft_seconds: float | None,
    t_start: float,
    direct: bool,
) -> dict:
    # Which engine served the answer and how much of the library went with it make
    # the privacy claim checkable. A pass-through answer has no TTFT: null, not 0.
    # context_budget_reason says when the slow-host path halved the budget (#100).
    return {
        "engine": "local" if is_on_device(served_model) else "cloud",
        "model": served_model,
        "ttft_seconds": round(ttft_seconds, 2) if ttft_seconds is not None else None,
        "total_seconds": round(time.perf_counter() - t_start, 2),
        "passages_sent": 0 if direct else result.get("_passages_sent"),
        "context_chars": 0 if direct else result.get("_context_chars"),
        "context_budget_tokens": 0 if direct else result.get("_context_budget"),
        "context_budget_reason": "direct" if direct else result.get("_budget_reason"),
    }


def _eval_context(result: dict, grounded: _Grounded, direct: bool) -> dict:
    # Eval-only (include_context): faithfulness is scored against the exact grounding
    # the answer was generated from, section_context included.
    if direct:
        return {
            "context_chunks": [],
            "citations_dropped": 0,
            "citations_proposed": 0,
            "citations_gated": 0,
        }
    return {
        "context_chunks": _grounding_texts(result),
        "citations_dropped": grounded.dropped,
        "citations_proposed": grounded.proposed,
        "citations_gated": grounded.gated,
    }


class QAService:
    """Retrieve → ground → cite → stream answer over SSE."""

    async def _no_context_reason(
        self, scope: str, document_ids: list[str] | None, *, retrieval_failed: bool
    ) -> tuple[str, str]:
        """Why nothing was retrieved, and what the user can do about it."""
        if retrieval_failed:
            return (
                "retrieval_failed",
                "Search could not run just now — indexing may be using the machine."
                " Try again in a moment.",
            )
        total, indexing = await qa_repo.library_counts()
        if not total:
            return ("no_documents", "Your library is empty. Ingest a document and ask again.")
        if total == indexing:
            return (
                "still_indexing",
                "Your documents are still being indexed. Ask again in a moment.",
            )
        if scope == "single" and document_ids:
            titles = await self._fetch_doc_titles(document_ids)
            name = next(iter(titles.values()), "")
            if not name:
                # Deleting a document does not clear a chat's selection of it.
                return (
                    "document_missing",
                    "This chat is pointed at a document that is no longer in your"
                    " library. Pick a document, or switch to all documents.",
                )
            return (
                "no_match_in_document",
                f"Nothing in “{name}” answers that."
                " Switch to all documents to search the rest of your library.",
            )
        return ("no_context", "Nothing in your library matches that question.")

    async def _fetch_doc_titles(self, document_ids: list[str]) -> dict[str, str]:
        return await qa_repo.fetch_titles(document_ids)

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
        return await qa_repo.insert_qa_history(
            question, answer, citations, confidence, document_id, scope, model_used
        )

    async def _run_graph(self, initial_state: dict, root_span) -> tuple[dict | None, str | None]:
        """(graph result, None), or (None, the error event to end the stream with)."""
        try:
            t_graph = time.perf_counter()
            result = await chat_graph.get_chat_graph().ainvoke(initial_state)
            logger.info(
                "[perf] graph.ainvoke (intent+retrieval+strategy) took %.2fs",
                time.perf_counter() - t_graph,
            )
            return result, None
        except Exception as exc:
            root_span.set_attribute("error", True)
            root_span.set_attribute("error.message", "llm_unavailable")
            logger.warning("stream_answer: graph error [%s]: %s", type(exc).__name__, exc)
            return None, _llm_error_event(exc)

    async def _not_found_event(self, req: "_Request", result: dict, root_span) -> str:
        if not (result.get("chunks") or []):
            code, msg = await self._no_context_reason(
                req.scope, req.document_ids, retrieval_failed=bool(result.get("retrieval_failed"))
            )
            root_span.set_attribute("error", True)
            root_span.set_attribute("error.message", code)
            return _sse({"error": code, "message": msg, "done": True})
        await self._store_qa(req.question, None, [], "low", None, req.scope, req.store_model)
        root_span.set_attribute("qa.not_found", True)
        return _sse({"done": True, "not_found": True})

    async def stream_answer(
        self,
        question: str,
        document_ids: list[str] | None,
        scope: str,
        model: str | None,
        conversation_history: list[dict] | None = None,
        web_enabled: bool = False,
        socratic: bool = False,
        creative: bool = False,
        direct: bool = False,
        include_context: bool = False,
    ) -> AsyncGenerator[str]:
        """Async generator of SSE events: token*, then done (or error).

        Every exception becomes an SSE error event so the stream is never silently dropped.
        """
        req = _Request(
            question, document_ids, scope, model, socratic, creative, direct, include_context
        )
        try:
            req.store_model = _store_model_for(model)
            notice = await _offline_notice(model, req.store_model)
            if notice:
                yield notice
            state = _initial_state(
                question, document_ids, scope, model, direct, conversation_history, web_enabled
            )
            result = None
            async for event in self._graph_events(req, state):
                if isinstance(event, dict):
                    result = event
                else:
                    yield event
            if result is None:
                return
            async for event in self._answer_events(req, result):
                yield event
            logger.info(
                "[perf] stream_answer total: %.2fs (question=%r)",
                time.perf_counter() - req.t_start,
                question[:60],
            )
        except Exception as exc:
            logger.exception("stream_answer: unhandled error", exc_info=exc)
            yield _sse({"error": "internal", "message": str(exc), "done": True})

    async def _graph_events(self, req: "_Request", state: dict) -> AsyncGenerator[str | dict]:
        """Run the graph inside the qa.answer span.

        Yields the terminal events of a stream the graph ends (error, card, not found),
        or the graph result as a dict when the answer still has to be streamed.
        """
        with trace_chain("qa.answer", input_value=req.question) as root_span:
            root_span.set_attribute("qa.scope", req.scope)
            root_span.set_attribute("qa.model", req.store_model)
            if req.document_ids:
                root_span.set_attribute("qa.document_ids", ", ".join(req.document_ids))
            result, error_event = await self._run_graph(state, root_span)
            if result is None:
                yield error_event
                return
            root_span.set_attribute("qa.intent", result.get("intent") or "")
            raw_answer = result.get("answer") or ""
            if raw_answer.startswith(CARD_PREFIX):
                for event in _card_events(raw_answer):
                    yield event
            elif result.get("not_found"):
                yield await self._not_found_event(req, result, root_span)
            else:
                yield result

    async def _llm_events(
        self, req: "_Request", result: dict, answer: "_Answer"
    ) -> AsyncGenerator[str]:
        """Call the LLM on the prompt synthesize_node left, streaming its prose.

        Leaves answer.finished set when the stream already ended (error or not found).
        """
        # Retrieval is done, so the source chips can show before the first token.
        # `done` still carries source_citations (I-8).
        early_sources = result.get("source_citations") or []
        if early_sources:
            yield _sse({"type": "sources", "source_citations": early_sources})

        system_prompt, temperature = _system_prompt_for(
            result, req.direct, req.creative, req.socratic
        )
        try:
            t_llm = time.perf_counter()
            # The token generator is lazy: acompletion runs on first iteration,
            # so the try must cover the streaming loop too.
            token_gen = await get_llm_service().generate(
                result["_llm_prompt"], system=system_prompt, model=req.model, stream=True,
                temperature=temperature,
            )  # fmt: skip
            async for event in _stream_prose(token_gen, answer.gen, t_llm):
                yield event
            logger.info("[perf] LLM streaming complete: %.2fs", time.perf_counter() - t_llm)
        except Exception as exc:
            logger.warning("stream_answer: LLM call failed [%s]: %s", type(exc).__name__, exc)
            answer.finished = True
            yield _llm_error_event(exc)
            return

        full_text = "".join(answer.gen.collected)
        answer.served_model = getattr(token_gen, "model", None) or req.store_model
        if NOT_FOUND_SENTINEL in full_text:
            prose_before = full_text[: full_text.index(NOT_FOUND_SENTINEL)].strip()
            if not prose_before:
                await self._store_qa(
                    req.question, None, [], "low", None, req.scope, answer.served_model
                )
                answer.finished = True
                yield _sse({"done": True, "not_found": True})
                return
            full_text = prose_before  # sentinel appended after a real answer

        answer.text, citations, answer.confidence = _split_response(full_text)
        if not req.direct:
            answer.grounded = await _ground_citations(answer.text, citations, result, req.scope)

    async def _answer_events(self, req: "_Request", result: dict) -> AsyncGenerator[str]:
        """Stream the answer, persist it, and end with the done event.

        Pass-through: a strategy node set state['answer'] and it streams word by word.
        Otherwise synthesize_node left a prompt and the LLM is called here, streaming.
        """
        answer = _Answer(served_model=req.store_model)
        if result.get("_llm_prompt"):
            async for event in self._llm_events(req, result, answer):
                yield event
            if answer.finished:
                return
        else:
            answer.text = result.get("answer") or ""
            for word in answer.text.split():
                yield _sse({"token": word + " "})
            answer.grounded = _Grounded(result.get("citations") or [])
            answer.confidence = result.get("confidence") or "low"

        transparency = _transparency_event(result, answer.confidence)
        if transparency:
            yield transparency
        yield await self._done_event(req, result, answer)

    async def _done_event(self, req: "_Request", result: dict, answer: "_Answer") -> str:
        first_doc_id = req.document_ids[0] if req.document_ids else None
        qa_id = await self._store_qa(
            req.question,
            answer.text,
            answer.grounded.citations,
            answer.confidence,
            first_doc_id if not req.direct else None,
            "direct" if req.direct else req.scope,
            answer.served_model,
        )
        final = {
            "done": True,
            "answer": answer.text,
            "citations": answer.grounded.citations,
            "confidence": answer.confidence,
            "qa_id": qa_id,
            "image_ids": result.get("image_ids") or [],
            "web_sources": result.get("web_snippets") or [],
            "web_calls_used": result.get("web_calls_used") or 0,
            "source_citations": result.get("source_citations") or [],
            "receipt": _receipt(
                result, answer.served_model, answer.gen.ttft_seconds, req.t_start, req.direct
            ),
        }
        if req.direct:
            final["direct"] = True
        if req.include_context:
            final.update(_eval_context(result, answer.grounded, req.direct))
        return _sse(final)


@dataclass
class _Request:
    question: str
    document_ids: list[str] | None
    scope: str
    model: str | None
    socratic: bool
    creative: bool
    direct: bool
    include_context: bool
    store_model: str = ""
    t_start: float = field(default_factory=time.perf_counter)


@dataclass
class _Answer:
    served_model: str
    text: str = ""
    confidence: str = "low"
    grounded: _Grounded = field(default_factory=lambda: _Grounded([]))
    gen: _Generation = field(default_factory=lambda: _Generation([]))
    finished: bool = False


_qa_service: QAService | None = None


def get_qa_service() -> QAService:
    global _qa_service  # noqa: PLW0603
    if _qa_service is None:
        _qa_service = QAService()
    return _qa_service
