"""Explain service -- context-grounded explanations of selected text."""

import json
import logging
from collections.abc import AsyncGenerator

from app.services.llm import get_llm_service

logger = logging.getLogger(__name__)

EXPLAIN_SYSTEM_BASE = (
    "You are explaining a concept using only the context from the source document. "
    "Use only information present in the provided text."
)

MODE_INSTRUCTIONS: dict[str, str] = {
    "plain": "Explain in simple, clear English.",
    "eli5": "Explain as if to a curious 10-year-old, using a concrete everyday analogy.",
    "analogy": "Create a memorable analogy from everyday life that captures the core idea.",
    "formal": "Give the precise formal definition as stated or implied in the source material.",
}


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
        prompt = f"Selected text:\n\n{text}\n\nExplain the selected text."

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
