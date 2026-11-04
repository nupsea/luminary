"""Tools the app fetches itself, each from its own release, pinned by version and sha256, into a
directory of its own so an install replaces only it. uv is the one: it builds each connector's
environment (#437), and the bundle ships none."""

from __future__ import annotations

import platform
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from app.services.component_download import install_archive_subset
from app.storage import machine_root

# (asset, sha256, bytes) of astral-sh/uv's release assets.
UV_VERSION = "0.13.5"
_UV_ASSETS = {
    ("darwin", "arm64"): ("uv-aarch64-apple-darwin.tar.gz",
        "743f85035a1996ecb350659e01cd9faea9709829be09b1b4b03c73eaf3c9cd73", 14365303),
    ("darwin", "x86_64"): ("uv-x86_64-apple-darwin.tar.gz",
        "b0f52b0e3945b4107d89024ea38e625683011fbfc05a0d98f9fa2d6dcee28c66", 17167423),
    ("linux", "x86_64"): ("uv-x86_64-unknown-linux-gnu.tar.gz",
        "f68d291c75783122dad58ab77def0e13f3233f358731db5d6d7e8715603b928f", 16682639),
    ("linux", "aarch64"): ("uv-aarch64-unknown-linux-gnu.tar.gz",
        "4bb69cf95ed13f23713bb7bc09f241896ea0c75b7c557e615a20604b82f9c403", 15914298),
    ("win32", "amd64"): ("uv-x86_64-pc-windows-msvc.zip",
        "a38b8d1902b7cfbc76b423ba1bb456f623f42064cdc72628b6075b89afd1019a", 15264056),
    ("win32", "arm64"): ("uv-aarch64-pc-windows-msvc.zip",
        "09f47edf90726084a70f9426f6e3ca4f46e9bf7cbf23b1716ec64d60b055fae3", 15439089),
}  # fmt: skip


def uv_source() -> dict | None:
    """The uv release asset for this host, or None where uv publishes none."""
    found = _UV_ASSETS.get((sys.platform, platform.machine().lower()))
    if found is None:
        return None
    asset, sha256, size = found
    return {
        "url": f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{asset}",
        "asset": asset,
        "sha256": sha256,
        "bytes": size,
        # A .tar.gz holds `uv-<target>/uv`; the Windows .zip holds `uv.exe` at its root.
        "member_prefix": "" if asset.endswith(".zip") else asset.removesuffix(".tar.gz") + "/",
    }


def managed_tool_dir(name: str) -> Path:
    """A tool the app fetched itself, in a directory of its own so an install replaces only it."""
    return machine_root() / "tools" / name


async def install(name: str, label: str) -> AsyncIterator[dict]:
    source = uv_source() if name == "uv" else None
    if source is None:
        yield {"state": "failed", "detail": f"no {label} download for this computer"}
        return
    async for event in install_archive_subset(
        url=source["url"],
        sha256=source["sha256"],
        archive_path=machine_root() / "downloads" / source["asset"],
        member_prefix=source["member_prefix"],
        target=managed_tool_dir(name),
        total_bytes=source["bytes"],
        label=label,
    ):
        yield event


def components() -> tuple:
    """The `Component` entries for the tools this host can fetch."""
    from app.services.components import Component  # noqa: PLC0415 - components imports this

    source = uv_source()
    if source is None:
        return ()
    return (
        Component(
            id="uv",
            label="Connector installer",
            description="Builds each connector its own Python environment (uv).",
            kind="managed_tool",
            ref="uv",
            size_bytes=source["bytes"],
            licence="MIT OR Apache-2.0",
            enables=("Installing connectors",),
        ),
    )
