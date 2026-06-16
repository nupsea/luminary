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


class NoteDescriptionGeneratorService:
    async def suggest_description(self, content: str) -> str | None:
        """Return a one-sentence summary, or None when the note is too short or
        the LLM is unavailable. Callers leave the description null in that case
        and the card falls back to a content snippet, so nothing useless is
        stored and the summary is retried on the next save/backfill."""
        content_stripped = content.strip()
        if len(content_stripped) < 40:
            return None

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
            return re.sub(r'^["\']|["\']$', "", raw.strip()).strip() or None
        except LLMUnavailableError:
            logger.warning("LLM unavailable during note description generation; skipping")
            return None


@lru_cache
def get_description_generator() -> NoteDescriptionGeneratorService:
    return NoteDescriptionGeneratorService()
