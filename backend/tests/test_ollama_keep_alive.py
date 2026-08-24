"""Residency is a server setting, not a per-call kwarg.

`OLLAMA_KEEP_ALIVE=30m` never applied. LiteLLM's ollama_chat transformation
lifts keep_alive to the top level of the request, but the `ollama/` completion
path -- which every local call in this codebase takes, there is no ollama_chat
caller -- drops unrecognised kwargs into `options`. Ollama answered
`invalid option provided option=keep_alive` on every single request and unloaded
the model on its own 5-minute default instead.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_the_completion_path_does_not_send_keep_alive_as_an_option():
    llm = (REPO / "backend" / "app" / "services" / "llm.py").read_text()
    assert 'kwargs["keep_alive"]' not in llm, (
        "the ollama/ completion path folds this into options, where it is rejected"
    )


def test_compose_sets_residency_on_the_ollama_server():
    """Removing the kwarg only helps if something still keeps the model warm."""
    compose = (REPO / "docker-compose.yml").read_text()
    assert "OLLAMA_KEEP_ALIVE=${OLLAMA_KEEP_ALIVE:-30m}" in compose
