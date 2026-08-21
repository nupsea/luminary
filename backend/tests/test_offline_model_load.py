"""Cache-only model loading must not depend on the network being reachable.

Reported from a real offline run: with wifi off, startup logged
"Warmup: entity model failed ... Failed to resolve 'huggingface.co'" and lost
entity extraction, while every byte the model needed was already on disk.
`local_files_only=True` did not prevent it -- GLiNER forwards the flag to its
own checkpoint and then loads the tokenizer through a bare
`AutoTokenizer.from_pretrained`, which calls `model_info` regardless.
"""

import importlib
import os

from app.services.model_loading import _OFFLINE_FLAGS, offline_model_load


def test_offline_flags_are_set_inside_the_block_and_restored_after():
    """Setting the variables is not enough; both libraries copy them into
    module constants at import time, long before any model loads."""
    before = {}
    for module_path, attr in _OFFLINE_FLAGS:
        module = importlib.import_module(module_path)
        before[(module_path, attr)] = getattr(module, attr)

    with offline_model_load():
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
        for module_path, attr in _OFFLINE_FLAGS:
            module = importlib.import_module(module_path)
            assert getattr(module, attr) is True, f"{module_path}.{attr} not forced offline"

    for (module_path, attr), original in before.items():
        module = importlib.import_module(module_path)
        assert getattr(module, attr) == original, f"{module_path}.{attr} not restored"


def test_transformers_offline_short_circuits_the_tokenizer_hub_call():
    """`is_offline_mode()` is what stops the tokenizer's `model_info` call.

    In `_patch_mistral_regex`, a true return sets `_is_local` and short-circuits
    `is_base_mistral(...)` -- the hub request that is not gated by
    `local_files_only` and whose exception is not caught upstream.
    """
    from transformers.utils.hub import is_offline_mode

    with offline_model_load():
        assert is_offline_mode() is True
    assert is_offline_mode() is False


def test_environment_is_restored_when_the_block_raises():
    had = os.environ.get("HF_HUB_OFFLINE")
    try:
        with offline_model_load():
            raise RuntimeError("model load blew up")
    except RuntimeError:
        pass
    assert os.environ.get("HF_HUB_OFFLINE") == had
    for module_path, attr in _OFFLINE_FLAGS:
        module = importlib.import_module(module_path)
        assert getattr(module, attr) is False
