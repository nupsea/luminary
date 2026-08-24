"""Ollama's own defaults are not sized for the machines Luminary ships to.

Measured against `ollama/ollama:latest`, with the model loaded and a generate
issued:

    unset                     -> "prompt cache is enabled, size limit: 8192 MiB"
    LLAMA_ARG_CACHE_RAM=512   -> "size limit: 512 MiB"
    LLAMA_ARG_CACHE_RAM=0     -> "prompt cache is disabled"

8192 MiB is larger than a default Docker Desktop VM on a 16GB Mac, and a
reported run reached 1039 MiB of it while getting no reuse at all -- qwen3.5 is
hybrid/recurrent, so llama.cpp re-processes every prompt regardless. The bound
is not zero because the cache does work for a non-hybrid model.

`keep_alive` is here for the same reason: Ollama's default is 5m, and the
backend cannot set it per call (see test_ollama_keep_alive).
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPOSE = (REPO / "docker-compose.yml").read_text()
INSTALL_PS1 = (REPO / "scripts" / "install.ps1").read_text()


def test_compose_bounds_the_prompt_cache():
    assert "LLAMA_ARG_CACHE_RAM=${LLAMA_ARG_CACHE_RAM:-512}" in COMPOSE


def test_the_windows_installer_bounds_it_the_same_way():
    """Windows is the other environment whose Ollama server env we control:
    SetEnvironmentVariable(..., "User") reaches the server on restart."""
    assert 'SetEnvironmentVariable("LLAMA_ARG_CACHE_RAM", "512", "User")' in INSTALL_PS1


def test_the_bound_is_not_zero():
    """Disabling outright would cost real reuse on a non-hybrid model, which is
    every other entry in the registry."""
    assert "LLAMA_ARG_CACHE_RAM:-0}" not in COMPOSE
    assert 'SetEnvironmentVariable("LLAMA_ARG_CACHE_RAM", "0"' not in INSTALL_PS1
