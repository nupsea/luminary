"""In hybrid mode, only the question and its packed passages may leave the machine.

This is the claim the Settings routing table and the answer receipt both make, and
the half of rung 0.10.0's exit gate that does not need a provider key.

**What this can and cannot prove.** It checks the egress boundary: that
`LLMService` sends the caller's system prompt and prompt and adds nothing of its
own — no library listing, no titles, no notes, no history. What goes *into* that
prompt is the packer's job and is covered by `tests/test_context_packer.py`; a
test that mocked the prompt and then asserted things about it would be checking
its own fixture, which verifies nothing (see
`.claude/rules/common/product-integrity.md`).

Both directions are asserted. A test that only checked "the secret is absent"
would pass against a client that sent nothing at all.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services import settings_service as ss
from app.services.llm import LLMService

# A string that exists nowhere in the caller's prompt. If it ever appears in an
# outbound payload, something is reading the library behind the caller's back.
NEVER_SENT = "PRIVATE-LIBRARY-CONTENT-THAT-WAS-NOT-RETRIEVED"

SYSTEM_PROMPT = "Answer from the passages. Cite with markers."
USER_PROMPT = "[S1] Raft elects a leader per term.\n\nQuestion: How does leader election work?"


@pytest.fixture
def hybrid_with_key():
    original = dict(ss._cache)
    ss._cache.update(
        {
            "llm_mode": "hybrid",
            "cloud_provider": "openai",
            "cloud_model": "gpt-5-mini",
            "openai_api_key": "sk-test-not-a-real-key",
        }
    )
    yield
    ss._cache.clear()
    ss._cache.update(original)


async def _capture_outbound(**generate_kwargs) -> dict:
    """Run one generation and return the kwargs litellm was actually called with."""
    captured: dict = {}

    async def _fake_acompletion(**kwargs):
        captured.update(kwargs)

        class _Choice:
            message = type("M", (), {"content": "An answer."})()

        return type("R", (), {"choices": [_Choice()]})()

    with patch("litellm.acompletion", new=AsyncMock(side_effect=_fake_acompletion)):
        await LLMService().generate(
            USER_PROMPT, system=SYSTEM_PROMPT, stream=False, **generate_kwargs
        )
    return captured


def _all_content(captured: dict) -> str:
    return "\n".join(m.get("content", "") for m in captured.get("messages", []))


@pytest.mark.asyncio
async def test_only_the_prompt_and_system_leave(hybrid_with_key):
    captured = await _capture_outbound()
    sent = _all_content(captured)

    # Positive direction first: if these are missing the payload is empty and the
    # absence check below would pass for the wrong reason.
    assert "Question: How does leader election work?" in sent
    assert "Raft elects a leader per term." in sent

    # Nothing beyond what the caller handed over.
    assert NEVER_SENT not in sent
    leftover = sent.replace(SYSTEM_PROMPT, "").replace(USER_PROMPT, "").strip()
    assert leftover == "", (
        f"the client added content of its own to the outbound payload: {leftover[:200]!r}"
    )


@pytest.mark.asyncio
async def test_the_check_notices_content_the_caller_never_supplied(hybrid_with_key):
    """The check firing: smuggle a string in and the assertions above catch it.

    Without this, `test_only_the_prompt_and_system_leave` would pass against a
    payload assembled any way at all, so long as it happened not to contain one
    made-up constant.
    """
    captured = await _capture_outbound()
    captured["messages"].append({"role": "user", "content": NEVER_SENT})
    sent = _all_content(captured)

    assert NEVER_SENT in sent
    leftover = sent.replace(SYSTEM_PROMPT, "").replace(USER_PROMPT, "").strip()
    assert leftover != "", "the leftover check cannot see smuggled content"


@pytest.mark.asyncio
async def test_hybrid_sends_the_question_to_the_provider_it_names(hybrid_with_key):
    """The receipt says "cloud" only if the call really went to the provider."""
    captured = await _capture_outbound()

    assert captured["model"].startswith("openai/"), (
        f"hybrid mode routed to {captured['model']!r}; the receipt would report "
        "cloud for a call that never left"
    )
    assert captured.get("api_key") == "sk-test-not-a-real-key"


@pytest.mark.asyncio
async def test_private_mode_sends_nothing_to_a_provider():
    """The other half: with no cloud route, no provider key is ever attached."""
    original = dict(ss._cache)
    ss._cache.update({"llm_mode": "private"})
    try:
        captured = await _capture_outbound()
    finally:
        ss._cache.clear()
        ss._cache.update(original)

    assert captured["model"].startswith("ollama/")
    assert not captured.get("api_key")


def test_egress_assertions_run_on_the_real_client():
    """`LLMService.generate` is what the QA stream calls, not a stand-in."""
    assert asyncio.iscoroutinefunction(LLMService.generate)
