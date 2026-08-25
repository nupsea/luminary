"""Grounding is spent for latency only where prefill is what the user waits on.

Every other tuning in this repo is free. This one is not: a narrower budget is
fewer of the user's own passages reaching the model, so it is gated on the same
start-up probe as keep-warm and applies nowhere else.

The asymmetry that justifies it: on an M3 Pro prefill is ~0.4s against ~16s of
decode (I-31), so a narrower prompt buys a rounding error and costs real
grounding. On an Intel i7-8850H in a 12GB Docker VM, prefill of 1751 tokens cost
66.1s of one 183s question -- the dominant term.
"""

import pytest

from app.config import Settings
from app.runtime.chat_nodes.synthesize import _qa_context_budget
from app.services import model_keepwarm


@pytest.fixture(autouse=True)
def _forget_probe():
    model_keepwarm.reset_measurement()
    yield
    model_keepwarm.reset_measurement()


class TestTheDefaultIsUntouched:
    """Apple Silicon, Windows, Linux -- anything that answers quickly."""

    def test_a_quick_host_gets_the_shipped_budget(self):
        model_keepwarm.record_startup_probe(3.0)
        assert _qa_context_budget() == Settings().QA_CONTEXT_TOKEN_BUDGET

    def test_an_unmeasured_host_gets_the_shipped_budget(self):
        """Unmeasured is never read as slow; grounding is not spent on a guess."""
        assert model_keepwarm.measured_probe_seconds() is None
        assert _qa_context_budget() == Settings().QA_CONTEXT_TOKEN_BUDGET

    def test_disabling_the_gate_restores_the_default_everywhere(self, monkeypatch):
        """One switch turns the whole host-adaptive behaviour off."""
        model_keepwarm.record_startup_probe(120.0)
        # Both modules bind `get_settings` at import, so the patch target is each
        # call site rather than `app.config` -- the mirror of the lazy-import
        # rule in docs/patterns.md.
        off = lambda: Settings(LLM_KEEP_WARM_ENABLED=False)  # noqa: E731
        monkeypatch.setattr("app.services.model_keepwarm.get_settings", off)
        monkeypatch.setattr("app.runtime.chat_nodes.synthesize.get_settings", off)
        assert _qa_context_budget() == Settings().QA_CONTEXT_TOKEN_BUDGET


class TestASlowHostNarrows:
    def test_a_slow_host_gets_the_constrained_budget(self):
        model_keepwarm.record_startup_probe(130.8)
        assert _qa_context_budget() == Settings().QA_CONTEXT_TOKEN_BUDGET_CONSTRAINED

    def test_the_constrained_budget_is_actually_smaller(self):
        s = Settings()
        assert s.QA_CONTEXT_TOKEN_BUDGET_CONSTRAINED < s.QA_CONTEXT_TOKEN_BUDGET

    def test_it_still_holds_several_passages(self):
        """A budget so small that one chunk fills it stops being retrieval and
        becomes a coin toss. Chunks run to a few hundred tokens."""
        assert Settings().QA_CONTEXT_TOKEN_BUDGET_CONSTRAINED >= 500


class TestTheTwoValuesStaySeparate:
    def test_the_constrained_value_is_its_own_setting(self):
        """Deriving it (a ratio, a "half") would make the trade invisible and
        let a change to one silently move the other."""
        fields = Settings.model_fields
        assert "QA_CONTEXT_TOKEN_BUDGET_CONSTRAINED" in fields
        assert fields["QA_CONTEXT_TOKEN_BUDGET_CONSTRAINED"].default == 750
