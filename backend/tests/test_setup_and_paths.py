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
    for key in ("db", "ollama_server", "chat_model", "vision_model", "embedder", "ner"):
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


def test_uninstalled_chat_model_is_missing_not_failed():
    """A fresh install has no chat model. Reporting that as a failure put a
    warning icon and a raw litellm traceback in front of a working install."""
    status = StartupStatus()
    for key in ("db", "embedder", "ollama_server", "reranker"):
        status.set_state(key, "ready")
    status.set_state("ner", "skipped")
    status.set_state("chat_model", "missing", "llama3.2")
    status.set_state("vision_model", "missing", "qwen2.5vl:7b")

    snap = status.snapshot()
    assert snap["status"] == "ready", "an uninstalled optional model is not a degraded app"
    assert snap["failed"] == []
    assert sorted(snap["missing"]) == ["chat_model", "vision_model"]
    assert snap["blocking"] is False


def test_offline_is_reported_not_inferred():
    """`litellm.APIConnectionError` contains the word "connection", so matching
    on message text told users with working internet that they had none."""
    status = StartupStatus()
    assert status.snapshot()["offline"] is False

    status.set_state("chat_model", "failed", "APIConnectionError: model not found")
    assert status.snapshot()["offline"] is False, "an API error is not an offline signal"

    status.set_offline(True)
    assert status.snapshot()["offline"] is True


def test_ollama_missing_model_is_classified_as_not_installed():
    from app.services.warmup import _friendly, _model_not_installed

    not_pulled = Exception(
        'litellm.APIConnectionError: OllamaException - {"error":"model \'llama3.2\' not found"}'
    )
    assert _model_not_installed(not_pulled) is True

    unreachable = Exception("APIConnectionError: [Errno 61] Connection refused")
    assert _model_not_installed(unreachable) is False
    # And whatever we do show a user is a sentence, not a traceback.
    assert "Errno" not in _friendly(unreachable)
    assert _friendly(unreachable).endswith(".")


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


def test_required_phases_are_exactly_these():
    """This set decides what every user waits for on a first run.

    Marking a new phase required is a product decision, not a detail -- the
    entity model alone is 1.1GB, and requiring it would put that download in
    front of a library that works without it.
    """
    from app.services.startup_status import _PHASES

    required = {key for key, _label, req in _PHASES if req}
    assert required == {"db", "embedder"}


def test_blocking_ignores_optional_phases():
    status = StartupStatus()
    status.set_state("db", "ready")
    status.set_state("embedder", "ready")
    status.set_state("ner", "downloading")
    assert status.snapshot()["blocking"] is False, "optional work must not gate the app"

    status.set_state("embedder", "failed", "network")
    assert status.snapshot()["blocking"] is True


# --- model prefetch --------------------------------------------------------


def test_prefetch_specs_cover_every_downloaded_phase():
    """A phase that downloads but has no spec would never be pre-fetched, and
    would silently fall back to serialized download inside the load lock."""
    from app.services import model_prefetch

    assert {s.key for s in model_prefetch.specs()} == {"embedder", "reranker", "ner"}
    for spec in model_prefetch.specs():
        assert spec.repo_id and spec.slug and spec.size_bytes > 0


def test_prefetch_cache_layout_matches_the_loaders(tmp_path, monkeypatch):
    """is_cached must agree with where the loaders actually look.

    They pass this directory as HuggingFace's cache root, so the marker is
    models--org--name/snapshots/<rev>. If these ever diverge, every start
    re-downloads and nothing reports it.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings
    from app.services import model_prefetch

    get_settings.cache_clear()
    try:
        spec = model_prefetch.spec_for("embedder")
        assert spec is not None
        assert model_prefetch.is_cached(spec) is False

        snapshot = (
            model_prefetch.cache_dir(spec)
            / f"models--{spec.repo_id.replace('/', '--')}"
            / "snapshots"
            / "abc123"
        )
        snapshot.mkdir(parents=True)
        assert model_prefetch.is_cached(spec) is False, "an empty snapshot is not cached"

        (snapshot / "config.json").write_text("{}")
        assert model_prefetch.is_cached(spec) is True
    finally:
        get_settings.cache_clear()


def test_prefetch_skips_alternate_frameworks_but_never_the_only_weights():
    """snapshot_download takes a whole repo; from_pretrained takes what it needs.

    The cross-encoder repo publishes 1.2GB of ONNX, OpenVINO and Flax variants
    beside a 127MB torch checkpoint, so pre-fetching without filters doubled the
    download. The filter is load-bearing in the other direction too: GLiNER
    ships only pytorch_model.bin, and excluding it would leave nothing to load.
    """
    from app.services import model_prefetch

    by_key = {s.key: s for s in model_prefetch.specs()}

    for key in ("embedder", "reranker", "ner"):
        assert "onnx/*" in by_key[key].ignore
        assert "openvino/*" in by_key[key].ignore

    assert "pytorch_model.bin" in by_key["embedder"].ignore
    assert "pytorch_model.bin" in by_key["reranker"].ignore
    assert "pytorch_model.bin" not in by_key["ner"].ignore, (
        "GLiNER publishes no safetensors; excluding the torch checkpoint "
        "would leave nothing to load"
    )


def test_hub_unreachable_when_offline_env_is_set(monkeypatch):
    """The offline check must not spend five seconds on a socket to say no."""
    from app.services import model_prefetch

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    assert model_prefetch.hub_reachable(timeout=0.1) is False


def test_offline_first_run_fails_fast_with_an_actionable_message(monkeypatch):
    """Previously this surfaced as ~75s of spinner, then a stuck setup screen."""
    from app.services import model_prefetch, warmup
    from app.services.startup_status import get_startup_status

    monkeypatch.setattr(model_prefetch, "is_cached", lambda spec: False)
    monkeypatch.setattr(model_prefetch, "hub_reachable", lambda *a, **k: False)

    called: list = []
    monkeypatch.setattr(
        model_prefetch, "prefetch", lambda *a, **k: called.append(a) or {}
    )
    for name in ("_load_embedder", "_load_ner", "_load_reranker", "_warm_llm"):
        async def _noop():
            return None

        monkeypatch.setattr(warmup, name, _noop)

    asyncio.run(warmup.run_warmup())

    assert not called, "must not attempt downloads when the hub is unreachable"
    phases = {p["key"]: p for p in get_startup_status().snapshot()["phases"]}
    assert phases["embedder"]["state"] == "failed"
    assert "internet" in phases["embedder"]["detail"].lower()


def test_retry_reruns_only_failed_phases(monkeypatch):
    from app.services import warmup
    from app.services.startup_status import get_startup_status

    status = get_startup_status()
    status.set_state("embedder", "failed", "boom")
    status.set_state("db", "ready")
    status.set_state("ner", "ready")
    status.set_state("reranker", "ready")
    status.set_state("chat_model", "ready")
    status.set_state("ollama_server", "ready")

    seen: list = []

    async def _fake(only=None):
        seen.append(only)

    monkeypatch.setattr(warmup, "run_warmup", _fake)
    retried = asyncio.run(warmup.retry_failed())

    assert retried == ["embedder"]
    assert seen == [{"embedder"}]


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


@pytest.mark.parametrize(
    "reported,expected",
    [
        # What settings hold.
        ("ollama/qwen2.5vl:7b", "vision_model"),
        # What the catalogue holds.
        ("qwen2.5vl:7b", "vision_model"),
        # What Ollama echoes back in the error -- it drops the tag.
        ("qwen2.5vl", "vision_model"),
        ("llama3.2", "chat_model"),
        ("llama3.2:latest", "chat_model"),
        ("ollama/llama3.2", "chat_model"),
        # Not ours to install.
        ("gpt-4o", None),
        ("", None),
    ],
)
def test_a_model_name_resolves_to_the_component_that_installs_it(reported, expected):
    """The name arrives three ways: with a provider prefix, with a tag, neither."""
    from app.services.components import component_for_model

    comp = component_for_model(reported)
    assert (comp.id if comp else None) == expected


def test_the_vision_model_is_a_startup_phase_users_can_act_on():
    """It installs from nowhere otherwise: not a default, and never warmed."""
    from app.services.startup_status import StartupStatus

    snapshot = StartupStatus().snapshot()
    phases = {p["key"]: p for p in snapshot["phases"]}
    assert "vision_model" in phases
    assert phases["vision_model"]["required"] is False, "6GB must never block the app"


def test_every_installer_resolves_the_full_dependency_group():
    """Both halves, on every install path.

    `--no-default-groups` alone drops trafilatura/cloudscraper/yt-dlp and the
    app refuses every URL; `--group full` alone re-resolves `dev`, whose
    arize-phoenix pulls a source-built sqlean-py that fails to build.
    """
    import re

    from app.paths import app_root

    # bootstrap.sh invokes uv through "$UV", the others by name.
    invocation = re.compile(r'uv"?\s+sync\b', re.IGNORECASE)

    installers = ("bootstrap.sh", "install.sh", "install.ps1")
    for name in installers:
        body = (app_root() / "scripts" / name).read_text()
        syncs = [line for line in body.splitlines() if invocation.search(line)]
        assert syncs, f"{name}: no `uv sync` found -- has the installer moved?"
        for line in syncs:
            assert "--no-default-groups" in line, f"{name}: {line.strip()}"
            assert "--group full" in line, f"{name}: {line.strip()}"


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


def test_capabilities_require_every_component_a_feature_depends_on(monkeypatch):
    """Video needs a transcriber AND ffmpeg; reporting either alone as enough
    sends the user through an upload that fails at the transcription step."""

    async def _fake_status():
        return [
            {"id": "transcription", "installed": True},
            {"id": "ffmpeg", "installed": False},
            {"id": "chat_model", "installed": True},
            {"id": "vision_model", "installed": False},
        ]

    monkeypatch.setattr(components_module, "component_status", _fake_status)
    caps = asyncio.run(components_module.capabilities())

    assert caps["audio_ingest"]["available"] is True
    assert caps["video_ingest"]["available"] is False
    assert "ffmpeg" in caps["video_ingest"]["requires"]
    assert caps["youtube_ingest"]["available"] is False
    assert caps["vision"]["available"] is False
    assert caps["vision"]["requires"] == ["vision_model"]
    assert caps["chat"]["available"] is True
    assert caps["chat"]["requires"] == []


def test_capabilities_endpoint_reports_every_key():
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/setup/capabilities")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert set(resp.json()) == {
        "audio_ingest",
        "video_ingest",
        "youtube_ingest",
        "web_ingest",
        "vision",
        "chat",
    }


def test_media_surfaces_ship_in_public_mode():
    """The desktop build is public mode; these were full-only while the upload
    dialog offered them unconditionally."""
    import json

    from app.paths import surface_manifest_path

    manifest = json.loads(surface_manifest_path().read_text())
    modes = {s["id"]: s["mode"] for s in manifest["surfaces"]}
    for surface in ("web_ingest", "youtube_ingest", "audio_transcribe", "image_enrichment"):
        assert modes[surface] == "public", f"{surface} is stripped from the shipped build"


def test_unknown_component_is_reported_not_raised():
    async def _run():
        return [e async for e in components_module.install_component("nope")]

    events = asyncio.run(_run())
    assert events == [{"state": "failed", "detail": "unknown component: nope"}]
    assert get_component("nope") is None
