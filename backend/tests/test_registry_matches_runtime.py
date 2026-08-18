"""The registry's capability claims must match what the runtime actually reports.

`qwen3.5:4b` and `gemma3:4b` both read images and were both recorded
`multimodal=False`. Nothing caught it, because a capability written by hand has
nothing to disagree with. The cost was not cosmetic: with no small multimodal
entry, the vision role resolved to a 6.81GB model needing 16GB, and the low
profile had zero feasible assignments across its four roles.

Marked `e2e` **and** guarded by a reachability check, deliberately. A skip guard
is not a marker: a previous real-model test was green on CI (no Ollama) and
hung the suite on every dev machine that had the model. This one only calls
`/api/show`, which returns metadata and runs no inference, so it cannot hang on
generation -- the marker is belt and braces.

Run it when adding or changing a registry entry::

    cd backend && uv run pytest tests/test_registry_matches_runtime.py -m e2e
"""

import os

import pytest

from app.model_registry import REGISTRY

pytestmark = pytest.mark.e2e

_TIMEOUT = 10.0

# NOT `get_settings().OLLAMA_URL`: conftest points that at a dead port on purpose,
# so the suite can never reach a live model. Reading it here would make this file
# skip every case forever, which is a dead test wearing a marker. This one is
# opted into explicitly and asks the machine's own runtime.
_OLLAMA = os.environ.get("LUMINARY_E2E_OLLAMA_URL", "http://127.0.0.1:11434")


def _capabilities(model: str) -> set[str] | None:
    """What Ollama says this model can do, or None when it is not installed."""
    import httpx

    base = _OLLAMA.rstrip("/")
    try:
        resp = httpx.post(f"{base}/api/show", json={"model": model}, timeout=_TIMEOUT)
    except httpx.HTTPError:
        pytest.skip("Ollama is not reachable")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return set(resp.json().get("capabilities") or [])


@pytest.mark.parametrize("model_id", sorted(REGISTRY))
def test_the_multimodal_flag_matches_the_runtime(model_id: str):
    if not model_id.startswith("ollama/"):
        pytest.skip("not a local model")
    name = model_id.removeprefix("ollama/")
    caps = _capabilities(name)
    if caps is None:
        pytest.skip(f"{name} is not installed on this machine")

    declared = REGISTRY[model_id].multimodal
    actual = "vision" in caps
    assert declared == actual, (
        f"{model_id}: registry says multimodal={declared}, Ollama reports "
        f"vision={actual}. A wrong flag here removed every feasible assignment "
        f"from the low profile once already."
    )


@pytest.mark.parametrize("model_id", sorted(REGISTRY))
def test_the_thinking_default_matches_the_runtime(model_id: str):
    """`think=False` is set on every call (I-27) precisely because this differs
    by model, so the entry has to know which models it is protecting against."""
    if not model_id.startswith("ollama/"):
        pytest.skip("not a local model")
    name = model_id.removeprefix("ollama/")
    caps = _capabilities(name)
    if caps is None:
        pytest.skip(f"{name} is not installed on this machine")

    declared = REGISTRY[model_id].thinking_default
    actual = "thinking" in caps
    assert declared == actual, (
        f"{model_id}: registry says thinking_default={declared}, Ollama reports "
        f"thinking={actual}"
    )
