"""Note auto-tagging service -- LLM-suggested tags based on note content."""

import json
import logging
import re
from functools import lru_cache

from app.services.prompt_spec import render_for, tag_spec

logger = logging.getLogger(__name__)

NOTE_TAG_SPEC = tag_spec("note")

def _system() -> str:
    return render_for(NOTE_TAG_SPEC, "background")

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

        Returns [] for short content (<20 chars), when Ollama is unreachable,
        or on any other LLM / parse failure -- the caller should never have
        to wrap this in its own try/except.
        """
        if len(content) < 20:
            return []
        from app.services.llm import get_llm_service  # noqa: PLC0415

        prompt = _USER_TMPL.format(content=content[:2000])
        try:
            raw = await get_llm_service().complete(
                messages=[
                    {"role": "system", "content": _system()},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                background=True,
            )
            return _parse_tag_list(raw)
        except Exception as exc:
            # 2D.1.b: broaden from LLMUnavailableError to Exception so parse
            # drift, network blips, or any other downstream failure degrades
            # gracefully to an empty suggestion list.
            logger.warning("note tagger failed (non-fatal): %s", exc)
            return []


@lru_cache
def get_note_tagger() -> NoteTaggerService:
    return NoteTaggerService()
