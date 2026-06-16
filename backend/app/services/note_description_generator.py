"""Note description generation -- a short LLM summary used as card context."""

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You write a single concise summary sentence (12-25 words) that captures what "
    "a user's note is about, to show as context on a card. "
    "Output ONLY the sentence -- no quotes, no markdown, no preamble."
)

_USER_TMPL = "Note content:\n{content}\n\nSummary:"


def _fallback(content: str) -> str:
    # First non-empty line, trimmed to a card-sized snippet.
    snippet = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
    snippet = re.sub(r"^#+\s*", "", snippet)
    return snippet[:160]


class NoteDescriptionGeneratorService:
    async def suggest_description(self, content: str) -> str:
        """Return a one-sentence summary; falls back to a content snippet when
        the note is too short or the LLM is unreachable."""
        content_stripped = content.strip()
        if len(content_stripped) < 40:
            return _fallback(content_stripped)

        from app.services.llm import LLMUnavailableError, get_llm_service  # noqa: PLC0415

        try:
            raw = await get_llm_service().complete(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _USER_TMPL.format(content=content_stripped[:2000])},
                ],
                temperature=0.3,
                max_tokens=60,
            )
            desc = re.sub(r'^["\']|["\']$', "", raw.strip()).strip()
            return desc or _fallback(content_stripped)
        except LLMUnavailableError:
            logger.warning("LLM unavailable during note description generation; using fallback")
            return _fallback(content_stripped)


@lru_cache
def get_description_generator() -> NoteDescriptionGeneratorService:
    return NoteDescriptionGeneratorService()
