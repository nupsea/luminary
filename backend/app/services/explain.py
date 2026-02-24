"""Explain service — context-grounded explanations and glossary extraction."""

import json
import logging
from collections.abc import AsyncGenerator

from app.services.llm import get_llm_service
from app.services.retriever import get_retriever

logger = logging.getLogger(__name__)

EXPLAIN_SYSTEM_BASE = (
    "You are explaining a concept using only the context from the source document. "
    "Do not introduce information from outside this text."
)

MODE_INSTRUCTIONS: dict[str, str] = {
    "plain": "Explain in simple, clear English.",
    "eli5": "Explain as if to a curious 10-year-old. Use a concrete everyday analogy.",
    "analogy": "Create a memorable analogy from everyday life that captures the core idea.",
    "formal": "Give the precise formal definition as stated or implied in the source material.",
}

GLOSSARY_SYSTEM = (
    "You are a precise technical terminology extractor. "
    "Output only valid JSON, no preamble, no markdown code fences."
)

GLOSSARY_USER_TMPL = (
    "Extract all domain-specific technical terms from this text. "
    "For each term, provide a definition based only on how it is used in the text. "
    'Output a JSON array: [{{"term": str, "definition": str, "first_mention_page": int}}]. '
    "Output only JSON.\n\nText:\n{text}"
)

# Approximate token limit for glossary context (8000 tokens ≈ 32000 chars)
_GLOSSARY_CHAR_LIMIT = 32_000


class ExplainService:
    async def stream_explain(
        self,
        text: str,
        document_id: str,
        mode: str,
    ) -> AsyncGenerator[str]:
        """Stream explanation tokens as SSE data events.

        Retrieves the 3 most relevant surrounding chunks and asks the LLM to
        explain the selected text using only that document context.
        """
        retriever = get_retriever()
        llm = get_llm_service()

        chunks = await retriever.retrieve(text, document_ids=[document_id], k=3)
        context = "\n\n---\n\n".join(c.text for c in chunks) if chunks else text

        mode_instruction = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["plain"])
        system = f"{EXPLAIN_SYSTEM_BASE}\n\n{mode_instruction}"
        prompt = f"Context:\n\n{context}\n\nSelected text: {text}\n\nExplain the selected text."

        token_gen = await llm.generate(prompt, system=system, stream=True)
        async for token in token_gen:
            yield f'data: {json.dumps({"token": token})}\n\n'

        yield f'data: {json.dumps({"done": True})}\n\n'

    async def extract_glossary(self, document_id: str) -> list[dict]:
        """Extract technical terms from a document and return a structured list.

        Samples document chunks up to _GLOSSARY_CHAR_LIMIT characters to fit the
        LLM context window.
        """
        retriever = get_retriever()
        llm = get_llm_service()

        # Retrieve a broad sample of chunks (high k, filter by document)
        chunks = await retriever.retrieve(
            "definition concept term", document_ids=[document_id], k=50
        )

        # Build text sample, truncate to char limit
        parts: list[str] = []
        total = 0
        for chunk in chunks:
            if total + len(chunk.text) > _GLOSSARY_CHAR_LIMIT:
                remaining = _GLOSSARY_CHAR_LIMIT - total
                if remaining > 200:  # noqa: PLR2004
                    parts.append(chunk.text[:remaining])
                break
            parts.append(chunk.text)
            total += len(chunk.text)

        combined_text = "\n\n".join(parts) if parts else ""
        if not combined_text:
            return []

        prompt = GLOSSARY_USER_TMPL.format(text=combined_text)
        raw = await llm.generate(prompt, system=GLOSSARY_SYSTEM, stream=False)

        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]

        try:
            terms = json.loads(raw)
            if isinstance(terms, list):
                return terms
        except (json.JSONDecodeError, ValueError):
            logger.warning("Glossary parse failed for doc %s: %r", document_id, raw[:200])

        return []


_explain_service: ExplainService | None = None


def get_explain_service() -> ExplainService:
    global _explain_service  # noqa: PLW0603
    if _explain_service is None:
        _explain_service = ExplainService()
    return _explain_service
