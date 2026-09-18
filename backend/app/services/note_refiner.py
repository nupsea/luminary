"""Note refinement -- an LLM rewrite of a note's grammar/structure that keeps
the author's own voice, ideas and image placement untouched (the blog
"Refine" step, run before a note is turned into a post).
"""

import logging
import re
from functools import lru_cache

from app.exceptions import LuminaryError

logger = logging.getLogger(__name__)


class RefineDroppedContentError(LuminaryError):
    """The model returned text that lost an image reference from the original.

    Silently publishing this would strip a picture the author placed on
    purpose, so the caller gets a 502 and the original content back rather
    than an "refined" note quietly missing part of it.
    """

    status_code = 502


DEFAULT_REFINE_PROMPT = (
    "Refine this note into a polished piece, in my own voice -- don't change "
    "what I'm saying or the order I say it in. Fix grammar, tighten sentences, "
    "and smooth transitions where the writing is rough, but keep my tone, my "
    "phrasing, and the analogies as I wrote them. Don't add new sections or a "
    "different ending, don't make it more formal or generic, and don't touch "
    "the images, quotes, or asides -- just carry them through exactly as placed."
)

_SYSTEM = (
    "You are refining a personal note for its author, before they publish it, "
    "in their own voice. Preserve their ideas, their structure and section "
    "order, and every image, link, and blockquote already placed in the text. "
    "Improve only grammar, clarity, and flow -- never add a new claim, section, "
    "or conclusion, and never make the tone more formal or generic than the "
    "original. Keep every `__LUMINARY_IMG__...` placeholder and its alt text "
    "(including any `|small`, `|medium`, or `|large` size hint) character for "
    "character, and keep every `>` blockquote's wording exactly as given. "
    "Output ONLY the refined markdown -- no preamble, no explanation, no "
    "surrounding quotes or code fences."
)

_USER_TMPL = "{instruction}\n\n---\n\n{content}"

# The model's own output length tracks the input's, plus room for the "light
# elaboration where useful" the instruction invites. 3 chars/token is a
# deliberately low (i.e. generous) estimate of English text -- real text runs
# closer to 4 -- so this errs toward more budget rather than truncating a long
# note (see docs/patterns.md: never buy latency by cutting off content).
_CHARS_PER_TOKEN_FLOOR = 3.0
_OUTPUT_BUFFER_TOKENS = 400
_MIN_MAX_TOKENS = 800

# Identity of an image reference for the before/after structural check: the
# placeholder path, not its alt text -- a grammar pass may reasonably reword
# "Pasted Image" but must never drop or rewrite the path itself.
_IMAGE_REF_RE = re.compile(r"__LUMINARY_IMG__/[^\s)\"']+")


def _image_refs(markdown: str) -> set[str]:
    return set(_IMAGE_REF_RE.findall(markdown))


class NoteRefinerService:
    async def refine(
        self, content: str, instruction: str | None = None, model: str | None = None
    ) -> str:
        content_stripped = content.strip()
        if not content_stripped:
            return content

        from app.services.llm import LLMUnavailableError, get_llm_service  # noqa: PLC0415

        prompt = _USER_TMPL.format(
            instruction=(instruction or DEFAULT_REFINE_PROMPT).strip(),
            content=content_stripped,
        )
        max_tokens = max(
            _MIN_MAX_TOKENS,
            int(len(content_stripped) / _CHARS_PER_TOKEN_FLOOR) + _OUTPUT_BUFFER_TOKENS,
        )
        try:
            raw = await get_llm_service().complete(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                model=model,
                temperature=0.5,
                max_tokens=max_tokens,
                # The payload is the user's own note, click-triggered. Hybrid
                # mode would otherwise route this to the cloud provider --
                # note content stays on the machine regardless.
                background=True,
            )
        except LLMUnavailableError:
            logger.warning("LLM unavailable during note refine")
            raise

        refined = raw.strip()
        refined = re.sub(r"^```(?:markdown)?\n|\n```$", "", refined)

        dropped = _image_refs(content_stripped) - _image_refs(refined)
        if dropped:
            raise RefineDroppedContentError(
                f"refine dropped {len(dropped)} image reference(s)", dropped=sorted(dropped)
            )
        return refined


@lru_cache
def get_note_refiner() -> NoteRefinerService:
    return NoteRefinerService()
