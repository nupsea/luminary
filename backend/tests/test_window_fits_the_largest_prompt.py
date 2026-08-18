"""A context window is only allowed to shrink to something the prompts still fit.

I-27's value half now exists: `context_window_for` reads `usable_context` off the
model's registry entry, so a small model on a small machine can stop paying for a
KV cache sized for everything. That makes lowering a window newly attractive and
newly dangerous -- Ollama does not error on an oversized prompt, it truncates,
and the flashcard path feeds a whole section.

Computed 2026-08-18 at the summarizer's own 4 chars/token: the largest single
prompt is flashcard generation at ~3,177 tokens (a 10,000-char passage plus
~2,700 chars of system and template), and ~10 cards of output needs ~1,200 more.
So ~4,377 tokens. 8192 leaves ~3,800 spare; 6144 leaves ~1,700; **4096 does not
fit it at all**, and the failure mode is a silently shortened passage rather than
an error.

Approximate by construction, which is why the floor here carries headroom rather
than sitting at the computed number.
"""

import pytest

from app.config import get_settings
from app.model_registry import REGISTRY
from app.services.flashcard import _CHUNK_CHAR_LIMIT
from app.services.flashcard_prompts import _build_genre_system_prompt, flashcard_user_tmpl
from app.services.summarizer import _CHARS_PER_TOKEN, _SUMMARY_RESERVE_TOKENS

# Room for roughly ten cards. Generation is capped by requested count, not by the
# window, so this is what the window has to leave free after the prompt.
_GENERATION_OUTPUT_TOKENS = 1_200


def largest_prompt_tokens() -> int:
    """The biggest prompt any path can build, in tokens."""
    scaffold = len(_build_genre_system_prompt("technical")) + len(flashcard_user_tmpl())
    return (_CHUNK_CHAR_LIMIT + scaffold) // _CHARS_PER_TOKEN


def test_the_deployed_window_fits_the_largest_prompt_and_its_output():
    needed = largest_prompt_tokens() + _GENERATION_OUTPUT_TOKENS
    assert get_settings().OLLAMA_NUM_CTX >= needed, (
        f"the window must hold a {largest_prompt_tokens():,}-token prompt plus room "
        f"to answer; below {needed:,} the passage is silently truncated"
    )


@pytest.mark.parametrize("model_id", sorted(REGISTRY))
def test_every_registered_window_fits_it_too(model_id: str):
    """Per-model windows are the point of `context_window_for`; each still has to
    hold the prompts this app sends, or that model quietly answers from less."""
    needed = largest_prompt_tokens() + _GENERATION_OUTPUT_TOKENS
    assert REGISTRY[model_id].usable_context >= needed, (
        f"{model_id} declares {REGISTRY[model_id].usable_context:,}, which cannot "
        f"hold the {needed:,} tokens the flashcard path needs"
    )


def test_4096_is_recorded_as_too_small():
    """The obvious saving, and the one that would cost content.

    Halving the window is the first thing anyone reaches for on an 8GB machine.
    It does not fit, and nothing would report that it did not.
    """
    assert largest_prompt_tokens() + _GENERATION_OUTPUT_TOKENS > 4096


def test_the_summary_input_budget_stays_larger_than_its_own_reserve():
    """`_input_token_budget` floors at the reserve, so a small enough window makes
    the budget equal to the reserve and the document is cut to nothing useful."""
    window = get_settings().OLLAMA_NUM_CTX
    assert window - _SUMMARY_RESERVE_TOKENS > _SUMMARY_RESERVE_TOKENS, (
        f"a {window:,}-token window leaves the summary "
        f"{window - _SUMMARY_RESERVE_TOKENS:,} tokens of input, at or below the "
        f"{_SUMMARY_RESERVE_TOKENS:,} it reserves for output"
    )
