"""Note title generation service -- LLM-suggested title based on note content."""

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are an assistant that creates concise, descriptive titles for user notes. "
    "Given a note, generate a short title (at most 5-6 words). "
    "Output ONLY the plain text title. "
    "Do not use markdown, do not include any explanation or preamble."
)

_USER_TMPL = "Note content:\n{content}\n\nTitle:"


class NoteTitleGeneratorService:
    async def suggest_title(self, content: str) -> str:
        """Return a short descriptive title for the given note content.

        Returns first few words as fallback when LLM is unreachable.
        """
        content_stripped = content.strip()
        if not content_stripped:
            return "Empty Note"

        # Use the first line as a fallback title
        lines = content_stripped.split("\n")
        fallback_title = lines[0].strip()[:50]
        if not fallback_title:
            fallback_title = "Untitled Note"

        if len(content_stripped) < 20:
            return fallback_title

        from app.services.llm import LLMUnavailableError, get_llm_service  # noqa: PLC0415

        prompt = _USER_TMPL.format(content=content_stripped[:1000])
        try:
            raw = await get_llm_service().complete(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=30,
            )
            title = raw.strip()
            title = re.sub(r'^["\']|["\']$', "", title)
            title = re.sub(r"^(Title|title):\s*", "", title).strip()

            if not title:
                return fallback_title
            return title
        except LLMUnavailableError:
            logger.warning("LLM unavailable during note title generation; returning fallback")
            return fallback_title


@lru_cache
def get_title_generator() -> NoteTitleGeneratorService:
    return NoteTitleGeneratorService()
