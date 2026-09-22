"""LiteLLM's own Ollama lookups must reach the configured server, not localhost:11434.

`OllamaConfig.get_model_info` runs around every streamed call and reads only
OLLAMA_API_BASE. On a bundled Windows install (engine on an ephemeral port) it
stalled each answer by ~16s before the first token and ~20s after the last.
"""

from unittest.mock import MagicMock, patch

import litellm


def test_litellm_model_info_uses_configured_ollama_url(monkeypatch):
    from app.config import get_settings

    # Registered first so monkeypatch restores the process value afterwards.
    monkeypatch.setenv("OLLAMA_API_BASE", "http://stale.invalid:1")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:49837")
    get_settings.cache_clear()
    try:
        get_settings()
        response = MagicMock()
        response.json.return_value = {"model_info": {}, "template": ""}
        with patch.object(litellm.module_level_client, "post", return_value=response) as post:
            litellm.OllamaConfig().get_model_info("ollama/qwen3.5:4b")
        assert post.call_args.kwargs["url"] == "http://127.0.0.1:49837/api/show"
    finally:
        get_settings.cache_clear()
