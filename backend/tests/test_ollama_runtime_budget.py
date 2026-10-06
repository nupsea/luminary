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
INSTALL_SH = (REPO / "scripts" / "install.sh").read_text()


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


def test_every_installer_we_control_sets_both_runtime_knobs():
    """Ollama's defaults are wrong for a laptop in two ways -- an 8192MB prompt
    cache and a 5-minute unload -- and the backend can set neither, so each
    install path has to. Compose and the Windows user environment are ours to
    write; on macOS and Linux the server belongs to the user, so install.sh
    exports them where it starts one and names them where it cannot."""
    for knob in ("OLLAMA_KEEP_ALIVE", "LLAMA_ARG_CACHE_RAM"):
        assert knob in COMPOSE, f"compose does not set {knob}"
        assert f'SetEnvironmentVariable("{knob}"' in INSTALL_PS1, f"install.ps1 misses {knob}"
        assert knob in INSTALL_SH, f"install.sh neither exports nor mentions {knob}"


def test_the_native_installer_exports_them_to_the_server_it_starts():
    """Exporting only the two older knobs meant a server this script launched
    itself still ran with Ollama's defaults for the two new ones."""
    assert (
        "export OLLAMA_MAX_LOADED_MODELS OLLAMA_NUM_PARALLEL "
        "OLLAMA_KEEP_ALIVE LLAMA_ARG_CACHE_RAM" in INSTALL_SH
    )


def test_the_desktop_shell_bounds_it_too():
    """I-64. The DMG/AppImage/MSI Ollama is spawned by `supervisor.rs` after
    `env_clear()`, so nothing the user exports reaches it: unset, its qwen3.5
    server grew to 13.4 GB (8 GiB of never-reused prompt cache) and jetsam killed
    the desktop."""
    rust = (REPO / "src-tauri" / "src" / "supervisor.rs").read_text()
    spawn = rust[rust.index("pub fn spawn_ollama") : rust.index("pub fn spawn_backend")]
    # rustfmt decides the line breaks, so compare without whitespace.
    assert '.env("LLAMA_ARG_CACHE_RAM",ollama_cache_ram_mib(data_dir)' in "".join(spawn.split())
    assert "const OLLAMA_CACHE_RAM_MIB: u32 = 512;" in rust


BOOTSTRAP = (REPO / "scripts" / "bootstrap.sh").read_text()
SUPERVISOR = (REPO / "src-tauri" / "src" / "supervisor.rs").read_text()

# Every path that starts an Ollama for the user, on every OS: the desktop shell (DMG, MSI and
# AppImage share supervisor.rs), compose, the native installers and the one-command Mac install.
# get-luminary.* install the desktop app, so the shell covers them.
LAUNCH_PATHS = {
    "supervisor.rs": SUPERVISOR,
    "docker-compose.yml": COMPOSE,
    "install.sh": INSTALL_SH,
    "install.ps1": INSTALL_PS1,
    "bootstrap.sh": BOOTSTRAP,
}


def test_every_launch_path_sets_every_runtime_cap():
    """A path missing one runs with Ollama's default: an 8 GiB prompt cache, three resident
    models, a 5-minute unload. bootstrap.sh missed two until 0.15.4 (I-64)."""
    caps = (
        "LLAMA_ARG_CACHE_RAM",
        "OLLAMA_KEEP_ALIVE",
        "OLLAMA_MAX_LOADED_MODELS",
        "OLLAMA_NUM_PARALLEL",
    )
    missing = [
        (path, cap) for path, text in LAUNCH_PATHS.items() for cap in caps if cap not in text
    ]
    assert missing == []


def test_bootstrap_hands_the_caps_to_both_ways_it_starts_ollama():
    """Ollama.app reads launchd's environment; the `nohup ollama serve` fallback reads this
    shell's. Each needs all four."""
    knobs = "OLLAMA_MAX_LOADED_MODELS OLLAMA_NUM_PARALLEL OLLAMA_KEEP_ALIVE LLAMA_ARG_CACHE_RAM"
    assert f"export {knobs}" in BOOTSTRAP
    assert f"for knob in {knobs}; do" in BOOTSTRAP
    assert 'launchctl setenv "$knob" "${!knob}"' in BOOTSTRAP
    assert "LLAMA_ARG_CACHE_RAM=512" in BOOTSTRAP
