"""Fixture connectors, written against the SDK in a folder outside this repo and installed into
an environment of their own, as a third-party connector would be."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from app.services import connectors
from app.services.components import resolve_tool

REPO = Path(__file__).resolve().parents[2]
SDK = REPO / "packages" / "luminary-source-sdk"

# A talk as yt-dlp describes it, which both the built-in download and the video connector
# hand the core.
TALK = {
    "title": "Building RAG pipelines on your laptop",
    "uploader": "DataEngBytes",
    "tags": ["vector search", "LanceDB"],
    "chapters": [{"title": "Intro"}, {"title": "Why Kimi K3 changes the cost"}],
    "description": "Recorded at DataEngBytes 2025. Jane Doe walks through LanceDB and Kimi K3.",
}
VTT = """WEBVTT

00:00:01.000 --> 00:00:03.500
We store vectors in <c>LanceDB</c>

00:01:05.250 --> 00:01:07.000
R&amp;D on Kimi K3
"""


def flac_header(seconds: float, rate: int = 16_000) -> bytes:
    """A FLAC STREAMINFO block: what `_flac_duration` reads. Not playable audio."""
    bits = rate << 44 | 0 << 41 | 15 << 36 | int(rate * seconds)
    return b"fLaC" + b"\x80\x00\x00\x22" + bytes(10) + bits.to_bytes(8, "big") + bytes(16)


AUDIO = flac_header(70.0)
SECRET = "fixture-token-5f2c"

_SOURCE = """
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
from luminary_source_sdk import (
    Account, Choice, Connector, ConnectorError, Description, Field, Option, Preview, Terms,
)

TERMS = Terms(
    statement="Fixture pages may be downloaded for personal study.",
    url="https://fixture.example/terms",
)
BODY = "A log is an append-only sequence of records on disk. " * 3


class FixtureSource(Connector):
    def describe(self):
        return Description(
            name="fixture-source", version="0.1.0", licence="Apache-2.0", terms=TERMS,
            url_prefixes=["https://fixture.example/"], label="Fixture Books",
            credentials=[Field("token", "Access token", secret=True, help="From your account")],
            inputs=[Field("edition", "Edition", required=False)], preview=True,
        )

    def check(self, credentials):
        if credentials.get("token") == SECRET:
            return Account(True, account="reader@fixture.example")
        return Account(False, message="that token was refused")

    def preview(self, input, credentials):
        options = [Option("one", "Storage"), Option("two", "Replication", "chapter 2")]
        return Preview(title="Fixture Systems", detail="Ada Author", choices=[
            Choice("parts", "Sections", options, multiple=True, default=["one", "two"])])

    def fetch(self, input, credentials, bundle, report):
        kind = input["url"].rsplit("/", 1)[-1]
        if kind == "auth":
            raise ConnectorError("auth", "Sign in to Fixture again.")
        print("chatter a connector prints, which must not reach the protocol")
        if kind == "env":
            seen = {"argv": sys.argv, "env": dict(os.environ), "token": credentials.get("token"),
                    "input": input}
            bundle.add_section("seen", "Seen", markdown=json.dumps(seen))
            bundle.finish(connector=("fixture-source", "0.1.0"), title="Seen", terms=TERMS)
            return
        parts = input.get("parts") or ["one", "two"]
        if "one" in parts:
            bundle.add_section("one", "Storage", html=f"<h1>Storage</h1><p>{BODY}</p>")
        report(0.5, "downloading")
        if kind == "crash":
            os._exit(3)
        if kind == "hang":
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
            (bundle.dest / "pids").write_text(f"{os.getpid()} {child.pid}")
            time.sleep(600)
        if "two" in parts:
            bundle.add_section("two", "Replication", html=f"<h1>Replication</h1><p>{BODY}</p>")
        bundle.finish(connector=("fixture-source", "0.1.0"), title="Fixture Systems",
                      terms=TERMS, source_url=input["url"])


class FixtureVideo(Connector):
    def describe(self):
        return Description(
            name="fixture-video", version="0.1.0", licence="Apache-2.0", terms=TERMS,
            label="Fixture Video", url_prefixes=["https://www.youtube.com/watch"],
            media=["youtube"], tools=["ffmpeg"],
        )

    def fetch(self, input, credentials, bundle, report):
        if not input.get("tools", {}).get("ffmpeg"):
            raise ConnectorError("input", "the core did not pass ffmpeg's path")
        with tempfile.TemporaryDirectory() as scratch:
            audio = Path(scratch) / "audio.flac"
            audio.write_bytes(AUDIO)
            media = {"kind": "youtube", "url": input["url"],
                     "audio": bundle.add_asset_file("audio.flac", audio)}
        if "nocaps" not in input["url"]:
            media["captions"] = bundle.add_asset("captions.en.vtt", VTT.encode())
        bundle.finish(
            connector=("fixture-video", "0.1.0"), title=TALK["title"], terms=TERMS,
            media=media, authors=[TALK["uploader"]], tags=TALK["tags"],
            description=TALK["description"], chapters=[c["title"] for c in TALK["chapters"]],
            source_url=input["url"],
        )
"""


def write_fixture(folder: Path, *, entry_points: str) -> Path:
    package = folder / "fixture_source"
    package.mkdir(parents=True)
    constants = f"TALK = {TALK!r}\nVTT = {VTT!r}\nAUDIO = {AUDIO!r}\nSECRET = {SECRET!r}\n"
    (package / "__init__.py").write_text(_SOURCE + constants)
    (folder / "pyproject.toml").write_text(
        textwrap.dedent(f"""
        [project]
        name = "fixture-source"
        version = "0.1.0"
        requires-python = ">=3.11"
        dependencies = ["luminary-source-sdk"]
        {entry_points}

        [tool.uv.sources]
        luminary-source-sdk = {{ path = "{SDK.as_posix()}" }}

        [build-system]
        requires = ["hatchling"]
        build-backend = "hatchling.build"

        [tool.hatch.build.targets.wheel]
        packages = ["fixture_source"]
        """)
    )
    return folder


def entry(name: str, target: str) -> str:
    return f'[project.entry-points."luminary.connectors"]\n{name} = "fixture_source:{target}"'


def install(tmp_path_factory, root: Path, name: str, target: str):
    """Install one fixture connector under `root`, which must be `connectors_root()`."""
    if resolve_tool("uv") is None:
        pytest.skip("installing a connector needs uv")
    folder = write_fixture(
        tmp_path_factory.mktemp("elsewhere") / "src", entry_points=entry(name, target)
    )
    assert connectors.connectors_root() == root
    return asyncio.run(connectors.install_from_folder(folder))
