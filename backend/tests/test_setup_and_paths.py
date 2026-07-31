"""Packaging-facing behaviour: resource paths, readiness reporting, components.

These guard the properties a shipped bundle depends on, each of which fails
silently rather than loudly if it regresses.
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import components as components_module
from app.services.components import CATALOGUE, get_component, resolve_tool, tool_bin_dir
from app.services.startup_status import StartupStatus

# --- paths -----------------------------------------------------------------


def test_app_root_honours_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINARY_APP_ROOT", str(tmp_path))
    import app.paths as paths_module

    paths_module.app_root.cache_clear()
    try:
        assert paths_module.app_root() == tmp_path.resolve()
        assert paths_module.is_packaged() is True
        assert paths_module.surface_manifest_path() == tmp_path.resolve() / "surface-manifest.json"
        assert paths_module.spa_dist() == tmp_path.resolve() / "frontend" / "dist"
        assert paths_module.alembic_ini() == tmp_path.resolve() / "backend" / "alembic.ini"
    finally:
        paths_module.app_root.cache_clear()


def test_data_dir_inside_bundle_is_refused(tmp_path, monkeypatch):
    """A packaged app must never resolve its library inside its own bundle.

    The resource root is read-only and replaced wholesale on upgrade, so a
    library there would be unwritable at best and deleted by the next update at
    worst -- silently, which is why this fails loudly instead.
    """
    monkeypatch.setenv("LUMINARY_APP_ROOT", str(tmp_path))
    import app.paths as paths_module
    from app.config import Settings

    paths_module.app_root.cache_clear()
    try:
        with pytest.raises(ValueError, match="inside the application bundle"):
            Settings(DATA_DIR=str(tmp_path / "library"))

        outside = tmp_path.parent / "elsewhere"
        assert Settings(DATA_DIR=str(outside)).DATA_DIR == str(outside)
    finally:
        paths_module.app_root.cache_clear()


# --- readiness -------------------------------------------------------------


def test_status_starts_unready_and_reports_usable_once_db_is_up():
    status = StartupStatus()
    snap = status.snapshot()
    assert snap["ready"] is False
    assert snap["usable"] is False

    status.set_state("db", "ready")
    snap = status.snapshot()
    assert snap["usable"] is True
    assert snap["ready"] is False, "model phases are still pending"


def test_status_reaches_ready_and_counts_skipped_as_satisfied():
    status = StartupStatus()
    for key in ("db", "ollama_server", "chat_model", "embedder", "ner"):
        status.set_state(key, "ready")
    status.set_state("reranker", "skipped", "Reranking is turned off")

    snap = status.snapshot()
    assert snap["status"] == "ready"
    assert snap["ready"] is True


def test_optional_phase_failure_degrades_rather_than_blocks():
    """Cloud routing works with no local model, so this must not be fatal."""
    status = StartupStatus()
    for key in ("db", "embedder"):
        status.set_state(key, "ready")
    for key in ("ner", "reranker"):
        status.set_state(key, "skipped")
    status.set_state("ollama_server", "ready")
    status.set_state("chat_model", "failed", "no model pulled")

    snap = status.snapshot()
    assert snap["status"] == "degraded"
    assert snap["usable"] is True
    assert "chat_model" in snap["failed"]


def test_required_phase_failure_is_not_ready():
    status = StartupStatus()
    status.set_state("db", "failed", "migration error")
    snap = status.snapshot()
    assert snap["ready"] is False
    assert snap["usable"] is False


def test_download_progress_reports_percent():
    status = StartupStatus()
    status.set_progress("chat_model", 512, 2048, "pulling")
    phase = next(p for p in status.snapshot()["phases"] if p["key"] == "chat_model")
    assert phase["state"] == "downloading"
    assert phase["percent"] == 25.0


async def test_setup_status_endpoint_is_served():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/setup/status")
    assert resp.status_code == 200
    body = resp.json()
    assert {"status", "ready", "usable", "phases", "version"} <= set(body)
    assert {p["key"] for p in body["phases"]} >= {"db", "embedder", "chat_model"}


# --- components ------------------------------------------------------------


def test_catalogue_entries_are_complete():
    assert CATALOGUE, "the catalogue is the single source of truth for model names"
    for comp in CATALOGUE:
        assert comp.label and comp.description
        assert comp.size_bytes > 0, f"{comp.id} needs a size so the UI can warn before downloading"
        assert comp.licence, f"{comp.id} must declare a licence before it can be offered"
        assert comp.ref


def test_copyleft_components_are_not_shipped():
    """Luminary is Apache-2.0, so GPL pieces may only ever be fetched on request."""
    for comp in CATALOGUE:
        if "GPL" in comp.licence.upper():
            assert "not distributed" in comp.licence.lower(), (
                f"{comp.id} is copyleft and must be marked as fetched at runtime"
            )


def test_resolve_tool_prefers_the_app_managed_directory(tmp_path, monkeypatch):
    """The bundled app runs with a minimal PATH, so this directory is searched first."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert resolve_tool("definitely-not-a-real-tool") is None

        bin_dir = tool_bin_dir()
        bin_dir.mkdir(parents=True, exist_ok=True)
        tool = bin_dir / "definitely-not-a-real-tool"
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)

        assert resolve_tool("definitely-not-a-real-tool") == str(tool)
    finally:
        get_settings.cache_clear()


def test_transcription_is_kept_out_of_the_bundle_dependency_set():
    """faster-whisper pulls PyAV, whose wheels carry libx264/libx265 (GPL).

    Luminary is Apache-2.0, so it must not sit in a group the installer
    installs. The bundle builds `--no-default-groups --group full`; this is the
    guard that keeps `media` separate.
    """
    import tomllib

    from app.paths import pyproject_path

    with pyproject_path().open("rb") as fh:
        groups = tomllib.load(fh)["dependency-groups"]

    full = " ".join(groups["full"])
    media = " ".join(groups["media"])
    assert "faster-whisper" in media
    assert "faster-whisper" not in full, "GPL-carrying deps must not ship in the installer"


def test_python_extra_installs_outside_the_bundle(tmp_path, monkeypatch):
    """Extras go to DATA_DIR, never into the read-only, code-signed bundle."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    captured: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = None

        async def wait(self):
            return 0

    async def _fake_exec(*cmd, **kwargs):
        captured.append(list(cmd))
        proc = _Proc()

        async def _empty():
            return
            yield  # pragma: no cover

        proc.stdout = _empty()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    async def _run():
        return [e async for e in components_module.install_component("transcription")]

    try:
        asyncio.run(_run())
    finally:
        get_settings.cache_clear()

    assert captured, "expected an install to be attempted"
    cmd = captured[0]
    assert "pip" in cmd and "install" in cmd
    target = cmd[cmd.index("--target") + 1]
    assert target.startswith(str(tmp_path)), f"extras must land in DATA_DIR, got {target}"


def test_tool_install_never_spawns_a_subprocess(monkeypatch):
    """Ollama pulls and tool checks go over HTTP or the filesystem.

    The subprocess route needed the `ollama` binary on PATH, which a
    GUI-launched process does not get -- the installer only worked around that
    by injecting a PATH into the launchd plist.
    """
    called: list = []

    def _boom(*args, **kwargs):
        called.append(args)
        raise AssertionError("component install must not spawn a subprocess")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _boom, raising=False)

    async def _run():
        events = []
        async for event in components_module.install_component("ffmpeg"):
            events.append(event)
        return events

    events = asyncio.run(_run())
    assert not called
    # ffmpeg has no automatic source yet; it must say so rather than guess a build.
    assert events[-1]["state"] == "failed"
    assert "no automatic installer" in events[-1]["detail"]


def test_unknown_component_is_reported_not_raised():
    async def _run():
        return [e async for e in components_module.install_component("nope")]

    events = asyncio.run(_run())
    assert events == [{"state": "failed", "detail": "unknown component: nope"}]
    assert get_component("nope") is None
