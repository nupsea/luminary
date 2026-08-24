"""Section summaries must not hold a readable document hostage to local CPU.

Measured end to end in Docker: alice_in_wonderland.txt produced 12 qualifying
sections and spent 330 of its 390-second ingest generating them inline, because
the gate was `count > 40` and 12 is under 40. The document was readable the
whole time -- the deferred path already exists and runs the same work behind
`stage=complete`.

A count was the wrong unit. One summary is one LLM call, and on a local model at
5-7 tok/s that is minutes; against a hosted model it is a second or two, where
having them immediately is genuinely nicer on a small document.
"""

from app.services.section_summarizer import DEFER_ABOVE_SECTIONS, defer_section_summaries

LOCAL = "ollama/qwen3.5:4b"
CLOUD = "openai/gpt-4o"


def test_a_local_model_always_defers():
    """12 sections cost 330s inline. There is no count at which that is a good
    trade when every section is a CPU generation."""
    assert defer_section_summaries(1, LOCAL)
    assert defer_section_summaries(12, LOCAL)
    assert defer_section_summaries(DEFER_ABOVE_SECTIONS + 1, LOCAL)


def test_a_cloud_model_keeps_the_count_threshold():
    """A hosted call is fast, so a small document still gets its summaries
    before it opens."""
    assert not defer_section_summaries(12, CLOUD)
    assert not defer_section_summaries(DEFER_ABOVE_SECTIONS, CLOUD)
    assert defer_section_summaries(DEFER_ABOVE_SECTIONS + 1, CLOUD)
