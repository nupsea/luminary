"""The warm-up must outlast a cold model load, or it destroys one.

Reported on an Intel i7-8850H in Docker with 12GB allocated. The startup
warm-up hardcoded a 60s timeout; loading qwen3.5:4b took just over that, since
it is multimodal and pulls in a 3.3GB vision tower plus 58 compat tensor
transforms. When the client gave up, Ollama logged:

    client connection closed before llama-server finished loading, aborting load
    Load failed ... error="timed out waiting for llama-server to start: context canceled"

So the warm-up did not merely fail to warm anything. It cancelled the load, and
every later request began from nothing. The one call whose stated purpose is
"so the first real question does not pay the load" was the reason the model
never finished loading.

Ollama's own OLLAMA_LOAD_TIMEOUT defaults to 5 minutes. A client that is
stricter than the server about a load can only ever cancel work the server was
willing to finish.
"""

import inspect

from app.config import Settings
from app.services import warmup

OLLAMA_LOAD_TIMEOUT_DEFAULT_SECONDS = 300.0


def test_the_warmup_timeout_is_not_stricter_than_ollama_s_own_load_budget():
    assert (
        Settings().LLM_WARMUP_TIMEOUT_SECONDS >= OLLAMA_LOAD_TIMEOUT_DEFAULT_SECONDS
    ), "a client stricter than the server cancels loads the server would finish"


def test_the_warmup_does_not_hardcode_its_timeout():
    """It was 60.0 in the source, so no configuration could rescue a host where
    the load takes longer."""
    source = inspect.getsource(warmup)
    assert "timeout=60.0" not in source
    assert "LLM_WARMUP_TIMEOUT_SECONDS" in source
