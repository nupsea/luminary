"""Every local call for a given model must ask for the same context window.

Ollama keys a loaded runner on num_ctx, so a call requesting a different window
unloads llama-server and reloads it — tens of seconds, on the critical path.
Three call-site-specific windows (2048 chat default, 4096 QA, 8192 generation)
made one chat turn reload the model twice, and a turn overlapping ingestion
reload it repeatedly: an adopter's question was answered slowly and then cut
off while enrichment ran.

I-27 has two halves. The *rule* is one window in force per loaded model; the
*value* is a property of the model, read from its registry profile. The value
half was never built — `usable_context` sat unread on every entry while one
global `OLLAMA_NUM_CTX` applied to every model at once — so this file used to
assert that every call site resolved to that global. It now asserts the real
invariant: no call site chooses a window, and exactly one function decides it.
"""

import re
from pathlib import Path

from app.config import Settings, get_settings
from app.model_registry import MEASURED_AT_NUM_CTX, REGISTRY, context_window_for

_APP = Path(__file__).resolve().parent.parent / "app"

_NUM_CTX_ARG = re.compile(r"num_ctx\s*=\s*([^,)\n]+)")

# Forms that pass a window through or resolve it from the model, rather than
# choosing one. `_summary_num_ctx` resolves via `context_window_for` and is kept
# separate because the same value also sizes the summary's input token budget.
_PLUMBING = {
    "num_ctx",
    "None",
    "num_ctx or context_window_for(model)",
    "_summary_num_ctx(model",
    "_summary_num_ctx(",
}


def test_settings_expose_one_local_context_window():
    fields = [f for f in Settings.model_fields if f.endswith("NUM_CTX")]
    assert fields == ["OLLAMA_NUM_CTX"], (
        f"a second context-window knob reintroduces runner reloads: {fields}"
    )


def test_no_call_site_chooses_a_window():
    offenders: list[str] = []
    for path in _APP.rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for value in _NUM_CTX_ARG.findall(line):
                value = value.strip()
                if value in _PLUMBING:
                    continue
                offenders.append(f"{path.relative_to(_APP.parent)}:{lineno}: num_ctx={value}")
    assert not offenders, (
        "num_ctx must be plumbed through or resolved from the model, never chosen "
        "at the call site:\n" + "\n".join(offenders)
    )


def test_only_the_registry_reads_the_global_window():
    """One fallback, in one place.

    A service reading `OLLAMA_NUM_CTX` directly is how the per-call windows came
    back last time: the global is the answer for an *unregistered* model, and
    anything else asking for it is asking the wrong question.
    """
    offenders = [
        f"{path.relative_to(_APP.parent)}:{lineno}"
        for path in _APP.rglob("*.py")
        if path.name not in {"config.py", "model_registry.py"}
        for lineno, line in enumerate(path.read_text().splitlines(), 1)
        if "OLLAMA_NUM_CTX" in line and not line.lstrip().startswith("#")
    ]
    assert not offenders, (
        "only model_registry.context_window_for may read the global window:\n"
        + "\n".join(offenders)
    )


class TestTheWindowIsAPropertyOfTheModel:
    def test_a_registered_model_gets_its_own_profile_value(self):
        for model_id, profile in REGISTRY.items():
            assert context_window_for(model_id) == profile.usable_context

    def test_the_provider_prefix_is_optional(self):
        """Settings stores `ollama/x`; some call sites carry the bare id. Both must
        resolve to the same window, or the same model gets two runners."""
        assert context_window_for("qwen3.5:4b") == context_window_for("ollama/qwen3.5:4b")

    def test_an_unregistered_model_falls_back_rather_than_failing(self):
        """A user may point Settings at any model Ollama holds."""
        assert context_window_for("ollama/not-in-the-registry") == (
            get_settings().OLLAMA_NUM_CTX
        )

    def test_it_is_a_pure_function_of_the_model(self):
        """Two call sites cannot disagree, because there is nothing else to vary."""
        assert context_window_for("ollama/llama3.2") == context_window_for("ollama/llama3.2")

    def test_every_window_fits_the_largest_prompt(self):
        """Flashcard/section generation feeds a whole section plus system and output.

        Below this the prompt is silently truncated, which is the failure the
        window exists to prevent -- so a smaller window is a decision that has to
        be measured, not a default someone lowers to save memory.
        """
        assert get_settings().OLLAMA_NUM_CTX >= 8192
        for model_id, profile in REGISTRY.items():
            assert profile.usable_context >= 8192, model_id

    def test_footprints_were_measured_at_the_window_the_entries_declare(self):
        """`resident_bytes` is weights plus one KV cache, and the cache is sized by
        the window. An entry whose window differs from what its footprint was
        measured at is reporting a memory cost the machine will not see."""
        for model_id, profile in REGISTRY.items():
            assert profile.usable_context == MEASURED_AT_NUM_CTX, (
                f"{model_id}: footprint measured at {MEASURED_AT_NUM_CTX} but the "
                f"entry declares {profile.usable_context}; re-measure with "
                f"scripts/model_footprint.py before changing a window"
            )
