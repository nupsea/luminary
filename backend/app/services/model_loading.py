"""Process-wide lock serializing HuggingFace/torch model construction.

`transformers.from_pretrained` mutates process-global state while it builds a
model (`no_init_weights` swaps out `torch.nn.init.*`, weights are materialized
from a meta-device init). Two concurrent loads in different threads therefore
corrupt each other: one model keeps meta parameters that are never filled, and
its final `.to(device)` raises "Cannot copy out of meta tensor". Every torch
model load in this process -- embedder, GLiNER, cross-encoder -- must be built
while holding this lock.
"""

import contextlib
import importlib
import logging
import os
import threading

logger = logging.getLogger(__name__)

MODEL_LOAD_LOCK = threading.RLock()

# Every HuggingFace entry point takes `local_files_only`, and passing it is not
# enough: a loader that composes others does not necessarily forward it.
# GLiNER's `from_pretrained` honours the flag for its own checkpoint and then
# calls `AutoTokenizer.from_pretrained(config.model_name, cache_dir=...)`
# without it, so the tokenizer reaches for huggingface.co even though the
# weights came off disk. With a network that is merely *down* rather than
# absent, that raises instead of falling back, and a cold start with no
# connection loses entity extraction while every byte it needs is already
# cached. These variables bind the whole stack, including loaders we do not
# call ourselves.
# Setting the variables is necessary and not sufficient: both libraries copy
# them into module constants at import time, and the app has long since
# imported both by the time a model loads. Each flag below was found by
# following an actual offline failure, so do not drop one as redundant:
#
#   huggingface_hub.constants.HF_HUB_OFFLINE
#       Read per request in `utils/_http.send`. With it set, a hub call raises
#       OfflineModeIsEnabled instead of hanging on DNS.
#   transformers.utils.hub._is_offline_mode
#       A copy of the above, taken at import. It is what `is_offline_mode()`
#       returns, and in `_patch_mistral_regex` that return value short-circuits
#       a `model_info` call the tokenizer would otherwise make -- the call that
#       breaks a cold start with no network, since it is not gated by
#       `local_files_only` and its exception is not caught upstream.
_OFFLINE_VARS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
_OFFLINE_FLAGS = (
    ("huggingface_hub.constants", "HF_HUB_OFFLINE"),
    ("transformers.utils.hub", "_is_offline_mode"),
)


@contextlib.contextmanager
def offline_model_load():
    """Force cache-only loading for the duration of the block.

    Safe to nest inside `MODEL_LOAD_LOCK`, which is what serializes the
    process-global mutation this performs; do not use it outside that lock.
    """
    previous = {k: os.environ.get(k) for k in _OFFLINE_VARS}
    os.environ.update(dict.fromkeys(_OFFLINE_VARS, "1"))

    restore: list[tuple[object, str, object]] = []
    for module_path, attr in _OFFLINE_FLAGS:
        try:
            module = importlib.import_module(module_path)
        except Exception:  # not installed, or restructured upstream
            logger.debug("offline_model_load: %s unavailable", module_path, exc_info=True)
            continue
        if hasattr(module, attr):
            restore.append((module, attr, getattr(module, attr)))
            setattr(module, attr, True)

    try:
        yield
    finally:
        for module, attr, value in restore:
            setattr(module, attr, value)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
