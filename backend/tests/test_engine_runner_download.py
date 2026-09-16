"""The component downloader: resume, verification, and unpacking a subset.

Every case here is a way a 1.4GB download over a domestic link goes wrong. The
one that matters most is a corrupt archive: it must never be unpacked, and it
must not be kept as a resume point, or every later attempt resumes onto bad
bytes.
"""

import hashlib
import io
import json
import os
import tarfile
import zipfile

import httpx
import pytest

from app.services import component_download, components
from app.services.component_download import (
    download_verified,
    extract_prefix,
    install_archive_subset,
)

RUNNER_PREFIX = "lib/ollama/cuda_v13/"


def _zip_archive(path, members):
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return path.read_bytes()


def _tar_zst_archive(path, members):
    """`members` maps name -> bytes, or -> ("symlink", target)."""
    import zstandard

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            if isinstance(data, tuple):
                info.type, info.linkname, info.size = tarfile.SYMTYPE, data[1], 0
                bundle.addfile(info)
                continue
            info.size = len(data)
            info.mode = 0o755
            bundle.addfile(info, io.BytesIO(data))
    path.write_bytes(zstandard.ZstdCompressor().compress(raw.getvalue()))
    return path.read_bytes()


def _serve(body, *, support_range=True, status=200):
    """A transport that answers one URL, honouring Range when asked to."""

    def handler(request):
        header = request.headers.get("Range")
        if status != 200:
            return httpx.Response(status)
        if header and support_range:
            start = int(header.removeprefix("bytes=").split("-")[0])
            return httpx.Response(
                206,
                content=body[start:],
                headers={"Content-Length": str(len(body) - start)},
            )
        return httpx.Response(200, content=body, headers={"Content-Length": str(len(body))})

    return httpx.MockTransport(handler)


@pytest.fixture
def transport(monkeypatch):
    """Swap the module's client for one wired to whatever transport a test sets."""
    holder = {}
    # Bound before patching: `component_download.httpx` is the httpx module
    # itself, so a factory that looked the class up by name would call itself.
    real = httpx.AsyncClient

    def make(**kwargs):
        kwargs.pop("transport", None)
        return real(transport=holder["value"], **kwargs)

    monkeypatch.setattr(component_download.httpx, "AsyncClient", make)
    return holder


async def _drain(events):
    return [event async for event in events]


# --- verification ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_corrupt_archive_is_refused_and_not_kept(tmp_path, transport):
    body = b"not the archive you were promised" * 100
    transport["value"] = _serve(body)
    dest = tmp_path / "ollama.zip"

    events = await _drain(
        download_verified("https://example/ollama.zip", "0" * 64, dest, total_bytes=len(body))
    )

    assert events[-1]["state"] == "failed"
    assert "checksum" in events[-1]["detail"]
    assert not dest.exists(), "a file that failed its checksum was published anyway"
    assert not (tmp_path / "ollama.zip.part").exists(), (
        "the bad download was kept, so every later attempt would resume onto it"
    )


@pytest.mark.asyncio
async def test_a_good_archive_is_published_under_its_real_name(tmp_path, transport):
    body = b"payload" * 1000
    transport["value"] = _serve(body)
    dest = tmp_path / "ollama.zip"

    events = await _drain(
        download_verified(
            "https://example/ollama.zip",
            hashlib.sha256(body).hexdigest(),
            dest,
            total_bytes=len(body),
        )
    )

    assert events[-1]["state"] == "downloading"
    assert dest.read_bytes() == body
    assert events[-1]["completed_bytes"] == len(body)


@pytest.mark.asyncio
async def test_an_interrupted_download_resumes_instead_of_restarting(tmp_path, transport):
    body = b"abcdefghij" * 500
    sent = {}

    def handler(request):
        sent["range"] = request.headers.get("Range")
        start = int(request.headers["Range"].removeprefix("bytes=").split("-")[0])
        return httpx.Response(206, content=body[start:])

    transport["value"] = httpx.MockTransport(handler)
    dest = tmp_path / "ollama.zip"
    (tmp_path / "ollama.zip.part").write_bytes(body[:2000])

    events = await _drain(
        download_verified("https://example/ollama.zip", hashlib.sha256(body).hexdigest(), dest)
    )

    assert sent["range"] == "bytes=2000-"
    assert events[-1]["state"] == "downloading"
    assert dest.read_bytes() == body


@pytest.mark.asyncio
async def test_a_server_that_ignores_range_restarts_cleanly(tmp_path, transport):
    """The splice that would otherwise corrupt the file silently."""
    body = b"0123456789" * 500
    transport["value"] = _serve(body, support_range=False)
    dest = tmp_path / "ollama.zip"
    (tmp_path / "ollama.zip.part").write_bytes(body[:2000])

    events = await _drain(
        download_verified("https://example/ollama.zip", hashlib.sha256(body).hexdigest(), dest)
    )

    assert events[-1]["state"] == "downloading"
    assert dest.read_bytes() == body, "the resume offset was applied to a full-body response"


@pytest.mark.asyncio
async def test_an_already_downloaded_archive_is_not_fetched_again(tmp_path, transport):
    body = b"cached" * 100
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, content=body)

    transport["value"] = httpx.MockTransport(handler)
    dest = tmp_path / "ollama.zip"
    dest.write_bytes(body)

    await _drain(
        download_verified("https://example/ollama.zip", hashlib.sha256(body).hexdigest(), dest)
    )
    assert calls == []


# --- unpacking -------------------------------------------------------------


@pytest.mark.parametrize("builder,name", [(_zip_archive, "a.zip"), (_tar_zst_archive, "a.tar.zst")])
def test_only_the_named_directory_is_unpacked(tmp_path, builder, name):
    builder(
        tmp_path / name,
        {
            f"{RUNNER_PREFIX}libggml-cuda.so": b"runner",
            f"{RUNNER_PREFIX}nested/libcudart.so": b"more",
            "lib/ollama/vulkan/libggml-vulkan.so": b"not this one",
            "ollama": b"nor the binary",
        },
    )
    into = tmp_path / "out"

    written = extract_prefix(tmp_path / name, RUNNER_PREFIX, into)

    assert written == 2
    assert (into / "libggml-cuda.so").read_bytes() == b"runner"
    assert (into / "nested/libcudart.so").read_bytes() == b"more"
    assert not (into / "libggml-vulkan.so").exists()
    assert sorted(p.name for p in into.rglob("*") if p.is_file()) == [
        "libcudart.so",
        "libggml-cuda.so",
    ]


def test_a_member_that_escapes_the_target_is_refused(tmp_path):
    _zip_archive(tmp_path / "evil.zip", {f"{RUNNER_PREFIX}../../../escaped": b"pwned"})

    with pytest.raises(ValueError, match="escapes"):
        extract_prefix(tmp_path / "evil.zip", RUNNER_PREFIX, tmp_path / "out")

    assert not (tmp_path / "escaped").exists()


def test_versioned_sonames_survive_as_links(tmp_path):
    """The shape Ollama actually ships.

    In `ollama-linux-amd64.tar.zst` the CUDA directory is mostly symlinks --
    `libcublas.so.13 -> libcublas.so.13.x.y` -- and the unversioned name is the
    one the loader asks for. They are also stored BEFORE the file they point at.
    Skipping them leaves every real file present and the runner unable to start,
    which looks exactly like a successful install.
    """
    _tar_zst_archive(
        tmp_path / "a.tar.zst",
        {
            f"{RUNNER_PREFIX}libcublas.so.13": ("symlink", "libcublas.so.13.1.2"),
            f"{RUNNER_PREFIX}libcublas.so.13.1.2": b"the real library",
        },
    )
    into = tmp_path / "out"

    written = extract_prefix(tmp_path / "a.tar.zst", RUNNER_PREFIX, into)

    assert written == 2
    link = into / "libcublas.so.13"
    assert link.is_symlink(), "the soname the loader resolves was dropped"
    assert link.read_bytes() == b"the real library"


def test_a_symlink_that_escapes_the_target_is_refused(tmp_path):
    _tar_zst_archive(
        tmp_path / "evil.tar.zst",
        {f"{RUNNER_PREFIX}libc.so": ("symlink", "/etc/passwd")},
    )

    with pytest.raises(ValueError, match="escapes"):
        extract_prefix(tmp_path / "evil.tar.zst", RUNNER_PREFIX, tmp_path / "out")


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows has no executable bit -- chmod there only toggles read-only -- and "
    "the archive this guards is the .tar.zst one, which only Linux hosts fetch.",
)
def test_a_runner_keeps_its_executable_bit(tmp_path):
    _tar_zst_archive(tmp_path / "a.tar.zst", {f"{RUNNER_PREFIX}libggml-cuda.so": b"runner"})
    into = tmp_path / "out"

    extract_prefix(tmp_path / "a.tar.zst", RUNNER_PREFIX, into)

    assert (into / "libggml-cuda.so").stat().st_mode & 0o111, "the runner cannot be loaded"


# --- the whole install -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_download_leaves_the_existing_runner_alone(tmp_path, transport):
    transport["value"] = _serve(b"rubbish" * 100)
    target = tmp_path / "cuda_v13"
    target.mkdir()
    (target / "keep-me").write_bytes(b"the runner already installed")

    events = await _drain(
        install_archive_subset(
            url="https://example/a.zip",
            sha256="0" * 64,
            archive_path=tmp_path / "dl" / "a.zip",
            member_prefix=RUNNER_PREFIX,
            target=target,
            total_bytes=700,
            label="NVIDIA GPU acceleration",
        )
    )

    assert events[-1]["state"] == "failed"
    assert (target / "keep-me").exists(), "a failed install destroyed the working runner"


@pytest.mark.asyncio
async def test_an_archive_without_the_prefix_fails_rather_than_installing_nothing(
    tmp_path, transport
):
    """An empty directory would otherwise report installed and change nothing."""
    body = _zip_archive(tmp_path / "src.zip", {"lib/ollama/vulkan/x.so": b"wrong runner"})
    transport["value"] = _serve(body)
    target = tmp_path / "cuda_v13"

    events = await _drain(
        install_archive_subset(
            url="https://example/a.zip",
            sha256=hashlib.sha256(body).hexdigest(),
            archive_path=tmp_path / "dl" / "a.zip",
            member_prefix=RUNNER_PREFIX,
            target=target,
            total_bytes=len(body),
            label="NVIDIA GPU acceleration",
        )
    )

    assert events[-1]["state"] == "failed"
    assert RUNNER_PREFIX in events[-1]["detail"]
    assert not target.exists()


@pytest.mark.asyncio
async def test_a_successful_install_replaces_the_runner_and_drops_the_archive(tmp_path, transport):
    body = _zip_archive(tmp_path / "src.zip", {f"{RUNNER_PREFIX}libggml-cuda.so": b"new runner"})
    transport["value"] = _serve(body)
    target = tmp_path / "cuda_v13"
    target.mkdir()
    (target / "stale.so").write_bytes(b"from the previous release")
    archive = tmp_path / "dl" / "a.zip"

    events = await _drain(
        install_archive_subset(
            url="https://example/a.zip",
            sha256=hashlib.sha256(body).hexdigest(),
            archive_path=archive,
            member_prefix=RUNNER_PREFIX,
            target=target,
            total_bytes=len(body),
            label="NVIDIA GPU acceleration",
        )
    )

    assert events[-1]["state"] == "ready"
    assert (target / "libggml-cuda.so").read_bytes() == b"new runner"
    assert not (target / "stale.so").exists(), "the old runner survived the replacement"
    assert not archive.exists(), "1.4GB of archive was kept after the install"


# --- what the catalogue offers ---------------------------------------------


def _write_source(tmp_path, monkeypatch, **overrides):
    import app.paths as paths_module

    source = {
        "version": "v0.32.5",
        "asset": "ollama-linux-amd64.tar.zst",
        "url": "https://example/ollama-linux-amd64.tar.zst",
        "sha256": "a" * 64,
        "archive_bytes": 1422000000,
        "runner": "cuda_v13",
        "member_prefix": RUNNER_PREFIX,
    }
    source.update(overrides)
    path = tmp_path / "engine-source.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(paths_module, "engine_source_path", lambda: path)
    monkeypatch.setattr(components, "engine_source_path", lambda: path)
    return path


def test_no_engine_source_means_nothing_is_offered(tmp_path, monkeypatch):
    monkeypatch.setattr(components, "engine_source_path", lambda: tmp_path / "absent.json")

    assert components.engine_source() is None
    assert "cuda_runner" not in [c.id for c in components.catalogue()]


def test_an_incomplete_engine_source_is_ignored_not_half_offered(tmp_path, monkeypatch):
    _write_source(tmp_path, monkeypatch, sha256="")

    assert components.engine_source() is None
    assert "cuda_runner" not in [c.id for c in components.catalogue()]


def test_the_runner_is_offered_when_the_stage_recorded_its_source(tmp_path, monkeypatch):
    _write_source(tmp_path, monkeypatch)

    comp = components.get_component("cuda_runner")
    assert comp is not None
    assert comp.kind == "engine_runner"
    assert comp.ref == "cuda_v13"
    assert comp.default is False, "a 1.4GB download must never be a default"
    assert "NVIDIA" in comp.licence
    assert comp.size_bytes == 1422000000
