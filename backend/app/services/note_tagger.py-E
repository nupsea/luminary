"""Note auto-tagging service -- LLM-suggested tags based on note content."""

import json
import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a tagging assistant. Given a note, suggest up to 5 short, lowercase tags "
    "that best describe its topics. Tags should be 1-3 words, no punctuation. "
    'Output ONLY a JSON array of strings, e.g. ["machine learning", "python"]. '
    "Write no explanation, preamble, or markdown fences."
)

_USER_TMPL = "Note:\n{content}\n\nTags (JSON array, at most 5):"


def _parse_tag_list(raw: str) -> list[str]:
    """Parse LLM output into a list of at most 5 tags. Never raises."""
    if not raw:
        return []
    # Strip markdown fences if present
    cleaned = re.sub(r"```[^\n]*\n?", "", raw).strip()
    # Find first JSON array
    match = re.search(r"\[.*?\]", cleaned, re.DOTALL)
    if not match:
        return []
    try:
        result = json.loads(match.group(0))
        if isinstance(result, list):
            return [str(t).strip().lower() for t in result if str(t).strip()][:5]
    except (json.JSONDecodeError, ValueError):
        pass
    return []


class NoteTaggerService:
    async def suggest_tags(self, content: str) -> list[str]:
        """Return up to 5 suggested tags for the given note content.

        Returns [] for short content (<20 chars) or when Ollama is unreachable.
        """
        if len(content) < 20:
            return []
        from app.services.llm import LLMUnavailableError, get_llm_service  # noqa: PLC0415

        prompt = _USER_TMPL.format(content=content[:2000])
        try:
            raw = await get_llm_service().complete(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            return _parse_tag_list(raw)
        except LLMUnavailableError:
            logger.warning("LLM unavailable during note tagging; returning empty tags")
            return []


@lru_cache
def get_note_tagger() -> NoteTaggerService:
    return NoteTaggerService()
