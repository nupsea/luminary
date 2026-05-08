"""socratic_node and teach_back_node.

Both return __card__ sentinel strings so stream_answer() emits a
structured SSE card. They route directly to END (bypass synthesize +
confidence) because card answers are fully formed by these nodes.

socratic_node (intent='socratic'): retrieves k=5 chunks, asks the LLM
for one targeted recall question, parses the two-line Q/CONTEXT
response. Returns a fallback question on any parse/LLM failure.

teach_back_node (intent='teach_back'): evaluates the learner's
explanation against retrieved passages, returns a structured
correct/misconceptions/gaps/encouragement card.
"""

import json
import logging

from app.services.llm import LLMUnavailableError, get_llm_service
from app.services.retriever import get_retriever
from app.types import ChatState, ScoredChunk

logger = logging.getLogger(__name__)


async def socratic_node(state: ChatState) -> dict:
    """Generate one targeted recall question from document chunks.

    (1) Retrieves k=5 chunks (filtered to doc_ids[0] when available).
    (2) Calls LiteLLM (non-streaming) with a Socratic tutor prompt.
    (3) Parses exactly two lines: 'Q: ...' and 'CONTEXT: ...'.
    (4) On parse failure: returns fallback question (no exception raised).
    (5) On Ollama offline: returns card with 'error' field (no exception raised).

    Returns state['answer'] = '__card__' + JSON so the existing SSE protocol
    in stream_answer() handles delivery without any changes (S96 contract).
    Routes directly to END — card answers bypass synthesize/confidence nodes.
    """
    doc_ids = state.get("doc_ids") or []
    document_id = doc_ids[0] if doc_ids else None

    logger.info("socratic_node: document_id=%s", document_id)

    # Retrieve k=5 chunks
    chunks_retrieved: list[ScoredChunk] = []
    try:
        retriever = get_retriever()
        filter_ids = [document_id] if document_id else None
        chunks_retrieved = await retriever.retrieve("key concept important idea", filter_ids, k=5)
    except Exception:
        logger.warning("socratic_node: retrieval failed", exc_info=True)

    if not chunks_retrieved:
        card = {
            "type": "quiz_question",
            "question": "What are the main ideas in this material?",
            "context_hint": "See the document content.",
            "document_id": document_id or "",
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}

    passages = "\n---\n".join(c.text for c in chunks_retrieved[:5])

    system_msg = (
        "You are a Socratic tutor. Given passages from a learning document, "
        "generate ONE targeted recall question testing a specific fact, name, or concept. "
        "Format your response as exactly two lines:\n"
        "Q: {the question}\n"
        "CONTEXT: {1-2 sentence answer from the passages}\n"
        "Output nothing else."
    )

    try:
        text = (
            await get_llm_service().complete(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": f"Passages:\n{passages}"},
                ],
                temperature=0.7,
            )
        ).strip()

        q_text = "What are the main ideas in this material?"
        context_text = "See the document content."
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("Q:"):
                q_text = stripped[2:].strip()
            elif stripped.startswith("CONTEXT:"):
                context_text = stripped[8:].strip()

        card = {
            "type": "quiz_question",
            "question": q_text,
            "context_hint": context_text,
            "document_id": document_id or "",
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}

    except LLMUnavailableError:
        logger.warning("socratic_node: LLM unavailable")
        card = {
            "type": "quiz_question",
            "question": "Quiz unavailable",
            "context_hint": "",
            "document_id": document_id or "",
            "error": "LLM unavailable. Check Settings.",
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}

    except Exception:
        logger.warning("socratic_node: LLM call failed", exc_info=True)
        card = {
            "type": "quiz_question",
            "question": "What are the main ideas in this material?",
            "context_hint": "See the document content.",
            "document_id": document_id or "",
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}


_TEACH_BACK_SYSTEM = (
    "You are a learning coach. The learner explained a concept in their own words. "
    "Identify: (a) what they got right, (b) specific misconceptions (things stated that are "
    "factually wrong), (c) important gaps (key aspects not mentioned). "
    "Be specific -- name exact concepts. Do not re-explain the whole topic. "
    "Structure response as JSON: "
    '{"correct": ["..."], "misconceptions": ["..."], "gaps": ["..."], '
    '"encouragement": "one sentence of genuine encouragement"}'
)


async def teach_back_node(state: ChatState) -> dict:
    """Evaluate the user's explanation against authoritative passages.

    (1) Retrieves k=5 chunks relevant to the explanation.
    (2) Calls LiteLLM (non-streaming) with a learning coach prompt.
    (3) Parses JSON response; on parse failure returns fallback card.
    (4) On Ollama offline: returns card with 'error' field.

    Routes directly to END -- card answers bypass synthesize/confidence nodes.
    """
    doc_ids = state.get("doc_ids") or []
    document_id = doc_ids[0] if doc_ids else None
    question = state["question"]

    logger.info("teach_back_node: document_id=%s", document_id)

    # Use first 150 chars of the explanation as retrieval query
    retrieval_query = question[:150]

    chunks_retrieved: list[ScoredChunk] = []
    try:
        retriever = get_retriever()
        filter_ids = [document_id] if document_id else None
        chunks_retrieved = await retriever.retrieve(retrieval_query, filter_ids, k=5)
    except Exception:
        logger.warning("teach_back_node: retrieval failed", exc_info=True)

    passages = "\n---\n".join(c.text for c in chunks_retrieved[:5])[:3000]
    user_msg = f"LEARNER EXPLANATION:\n{question}\n\nAUTHORITATIVE PASSAGES:\n{passages}"

    fallback_card = {
        "type": "teach_back_result",
        "correct": [],
        "misconceptions": [],
        "gaps": [],
        "encouragement": "I had trouble analyzing your explanation. Try rephrasing.",
        "error_detail": "Could not parse evaluation",
        "document_id": document_id or "",
    }

    try:
        text = (
            await get_llm_service().complete(
                messages=[
                    {"role": "system", "content": _TEACH_BACK_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.3,
            )
        ).strip()

        if text.startswith("```"):
            text = text.split("\n", 1)[-1].strip()
            if text.endswith("```"):
                text = text[: text.rfind("```")].strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("teach_back_node: JSON parse failed, using fallback")
            return {"answer": "__card__" + json.dumps(fallback_card), "chunks": []}

        card = {
            "type": "teach_back_result",
            "correct": parsed.get("correct") or [],
            "misconceptions": parsed.get("misconceptions") or [],
            "gaps": parsed.get("gaps") or [],
            "encouragement": parsed.get("encouragement") or "Good effort!",
            "document_id": document_id or "",
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}

    except LLMUnavailableError:
        logger.warning("teach_back_node: LLM unavailable")
        card = {
            "type": "teach_back_result",
            "correct": [],
            "misconceptions": [],
            "gaps": [],
            "encouragement": "",
            "document_id": document_id or "",
            "error": "LLM unavailable. Check Settings.",
        }
        return {"answer": "__card__" + json.dumps(card), "chunks": []}

    except Exception:
        logger.warning("teach_back_node: LLM call failed", exc_info=True)
        return {"answer": "__card__" + json.dumps(fallback_card), "chunks": []}
