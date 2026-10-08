"""Explain service -- context-grounded explanations of selected text."""

import json
import logging
from collections.abc import AsyncGenerator

from app.services.llm import get_llm_service
from app.services.retriever import get_retriever

logger = logging.getLogger(__name__)

EXPLAIN_SYSTEM_BASE = (
    "You are helping a reader understand a document. Ground your answer in the document "
    "excerpts provided. If they do not cover it, say that what follows is general "
    "knowledge rather than from the document."
)

MODE_INSTRUCTIONS: dict[str, str] = {
    "define": (
        "Define the selected term as this document uses it, in two to four sentences. "
        "Then add one sentence on why it matters in this document."
    ),
    "plain": "Rewrite the selected passage in simple, clear English. Keep its meaning.",
    "eli5": "Explain as if to a curious 10-year-old, using a concrete everyday analogy.",
    "analogy": "Create a memorable analogy from everyday life that captures the core idea.",
    "formal": "Give the precise formal definition as stated or implied in the source material.",
}

# A selected term alone gives the model nothing to define it from (one word
# under "use only the provided text"), so passages that mention it ride along.
CONTEXT_PASSAGES = 4
# Bounds the FTS query; a long passage only needs its opening to find its neighbours.
CONTEXT_QUERY_CHARS = 300


async def _document_context(text: str, document_id: str) -> list[str]:
    try:
        chunks = await get_retriever().keyword_search(
            text[:CONTEXT_QUERY_CHARS], [document_id], k=CONTEXT_PASSAGES
        )
    except Exception:
        logger.warning("explain: context lookup failed", exc_info=True)
        return []
    return [c.text for c in chunks if c.text.strip()]


def build_prompt(text: str, mode: str, passages: list[str]) -> str:
    task = "Define the selected term." if mode == "define" else "Explain the selected text."
    if not passages:
        return f"Selected text:\n\n{text}\n\n{task}"
    excerpts = "\n\n---\n\n".join(passages)
    return f"Document excerpts:\n\n{excerpts}\n\nSelected text:\n\n{text}\n\n{task}"


class ExplainService:
    async def stream_explain(
        self,
        text: str,
        document_id: str,
        mode: str,
    ) -> AsyncGenerator[str]:
        """Stream explanation tokens as SSE data events."""
        llm = get_llm_service()

        mode_instruction = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["plain"])
        system = f"{EXPLAIN_SYSTEM_BASE}\n\n{mode_instruction}"
        passages = await _document_context(text, document_id)
        prompt = build_prompt(text, mode, passages)

        token_gen = await llm.generate(prompt, system=system, stream=True)
        async for token in token_gen:
            yield f"data: {json.dumps({'token': token})}\n\n"

        yield f"data: {json.dumps({'done': True})}\n\n"


_explain_service: ExplainService | None = None


def get_explain_service() -> ExplainService:
    global _explain_service  # noqa: PLW0603
    if _explain_service is None:
        _explain_service = ExplainService()
    return _explain_service
