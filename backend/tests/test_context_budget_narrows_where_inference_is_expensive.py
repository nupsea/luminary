"""The synthesis context budget follows a measurement of the host, not a platform.

Prefill is ~linear in prompt size and is the entire wait on a CPU-only host: an
Intel i7-8850H in a 12GB Docker VM measured ~31 tok/s, so a 1739-token prompt is
~56s before the first token. Narrowing the budget there is worth roughly half of
that; narrowing it on an Apple M3 Pro is pure loss.

The gate is `measured_probe_seconds()` -- what this machine charged for a trivial
answer at start-up -- for the same reason the keep-warm loop uses it: it is right
for a CPU-only laptop, a Docker VM and a GPU box without naming any of them, and
`platform.machine()` would guess at the cause rather than measure the effect.

An unmeasured host keeps the full budget. None means "never measured", never
"fast", so a host whose Ollama was down at start-up is left alone rather than
silently given a narrower prompt.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.runtime.chat_nodes.synthesize import _cap_text_tokens
from app.services import model_keepwarm
from app.services.context_packer import resolve_context_budget


@pytest.fixture(autouse=True)
def _clear_probe():
    model_keepwarm.reset_measurement()
    yield
    model_keepwarm.reset_measurement()


def test_an_unmeasured_host_keeps_the_full_budget():
    """None is 'unmeasured', never 'fast' -- and never 'slow' either."""
    budget, reason = resolve_context_budget()
    assert budget == get_settings().QA_CONTEXT_TOKEN_BUDGET
    assert reason == "default"


def test_a_quick_host_keeps_the_full_budget():
    model_keepwarm.record_startup_probe(get_settings().LLM_KEEP_WARM_ABOVE_SECONDS - 1.0)
    budget, _ = resolve_context_budget()
    assert budget == get_settings().QA_CONTEXT_TOKEN_BUDGET


def test_an_expensive_host_narrows_the_budget():
    """The i7-8850H case: start-up probes there measured 9.59s-155.45s."""
    model_keepwarm.record_startup_probe(get_settings().LLM_KEEP_WARM_ABOVE_SECONDS + 1.0)
    budget, reason = resolve_context_budget()
    assert budget == get_settings().QA_CONTEXT_TOKEN_BUDGET_SLOW_HOST
    assert budget < get_settings().QA_CONTEXT_TOKEN_BUDGET
    assert "slow host" in reason


def test_the_narrow_budget_still_carries_more_than_one_passage():
    """8244526 reverted a narrower budget because 500-1250 all collapsed to ONE
    passage pre-de-duplication. Post-914e8b54 the budget is a dial; a slow-host
    value that drops back to a single retrieved region would re-introduce exactly
    the defect that revert exists to prevent."""
    settings = get_settings()
    assert settings.QA_CONTEXT_TOKEN_BUDGET_SLOW_HOST >= 750


def test_an_optional_injection_is_capped_on_a_word_boundary():
    capped = _cap_text_tokens(" ".join(["word"] * 5000), 100)
    assert capped.endswith(" ...")
    assert len(capped.split()) < 200


def test_capping_leaves_short_text_untouched():
    assert _cap_text_tokens("a short summary", 1000) == "a short summary"
    assert _cap_text_tokens("anything", 0) == "anything"
