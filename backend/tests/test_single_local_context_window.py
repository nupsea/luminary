"""Every local LLM call must ask for the same context window.

Ollama keys a loaded runner on num_ctx, so a call requesting a different window
unloads llama-server and reloads it — tens of seconds, on the critical path.
Three call-site-specific windows (2048 chat default, 4096 QA, 8192 generation)
made one chat turn reload the model twice, and a turn overlapping ingestion
reload it repeatedly: an adopter's question was answered slowly and then cut
off while enrichment ran.
"""

import re
from pathlib import Path

from app.config import Settings, get_settings

_APP = Path(__file__).resolve().parent.parent / "app"

_NUM_CTX_ARG = re.compile(r"num_ctx\s*=\s*([^,)\n]+)")

# Parameter plumbing that passes num_ctx through rather than choosing a value,
# plus _summary_num_ctx() — pinned to OLLAMA_NUM_CTX by
# test_summary_context_budget.test_num_ctx_is_the_one_local_window, and kept
# explicit there because the same value also sizes the input token budget.
_PLUMBING = {"num_ctx", "num_ctx or settings.OLLAMA_NUM_CTX", "None", "_summary_num_ctx("}


def test_settings_expose_one_local_context_window():
    fields = [f for f in Settings.model_fields if f.endswith("NUM_CTX")]
    assert fields == ["OLLAMA_NUM_CTX"], (
        f"a second context-window knob reintroduces runner reloads: {fields}"
    )


def test_no_call_site_requests_a_different_window():
    offenders: list[str] = []
    for path in _APP.rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for value in _NUM_CTX_ARG.findall(line):
                value = value.strip()
                if value in _PLUMBING or "OLLAMA_NUM_CTX" in value:
                    continue
                offenders.append(f"{path.relative_to(_APP.parent)}:{lineno}: num_ctx={value}")
    assert not offenders, "num_ctx must resolve to OLLAMA_NUM_CTX:\n" + "\n".join(offenders)


def test_window_fits_the_largest_prompt():
    """Flashcard/section generation feeds a whole section plus system and output."""
    assert get_settings().OLLAMA_NUM_CTX >= 8192
