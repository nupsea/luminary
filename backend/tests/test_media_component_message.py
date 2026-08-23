"""What a user is told when audio/video support is missing.

The remediation has been wrong twice for the same underlying reason: it named
an action the user could not usefully take. First it said `brew install ffmpeg`
to bundled-app users who had already done exactly that (the bundle's minimal
PATH could not see it). Now it said the same thing to a Docker user, whose
backend is a Linux container that cannot see the host's PATH at all -- they run
it, it succeeds, and nothing changes.
"""

from pathlib import Path

import pytest

from app.routers.documents import _media_missing_message


@pytest.fixture()
def in_container(monkeypatch):
    monkeypatch.setattr("app.routers.documents.running_in_container", lambda: True)


@pytest.fixture()
def on_a_host(monkeypatch):
    monkeypatch.setattr("app.routers.documents.running_in_container", lambda: False)


def test_a_container_is_told_to_rebuild_the_image(in_container):
    message = _media_missing_message(["ffmpeg"])
    assert "WITH_MEDIA=1" in message, "the fix is a rebuild, and it must name the flag"
    assert "brew install" not in message, "host advice cannot reach a container"


def test_a_container_says_why_installing_on_the_host_will_not_work(in_container):
    """Otherwise the user tries the obvious thing first and loses another hour."""
    assert "does not reach the container" in _media_missing_message(["ffmpeg"])


def test_a_host_install_still_gets_host_advice(on_a_host):
    message = _media_missing_message(["ffmpeg"])
    assert "brew install ffmpeg" in message
    assert "WITH_MEDIA" not in message


def test_the_build_arg_the_message_names_is_wired_end_to_end():
    """A rebuild flag that reaches nothing is worse than no advice: the user
    runs it, the build succeeds, and the feature is still missing."""
    repo = Path(__file__).resolve().parents[2]
    dockerfile = (repo / "Dockerfile").read_text()
    compose = (repo / "docker-compose.yml").read_text()

    assert "ARG WITH_MEDIA" in dockerfile
    assert "WITH_MEDIA: ${WITH_MEDIA:-0}" in compose, "compose must pass the arg through"
    # One flag has to cover the whole path. ffmpeg alone leaves the downloader
    # and the transcriber missing and the user hits a second wall.
    media_step = dockerfile.split("ARG WITH_MEDIA", 1)[1]
    assert "ffmpeg" in media_step
    assert "--group media" in media_step, "yt-dlp and faster-whisper live there"
    # `full` also carries the tree-sitter grammars and code_parsing is a
    # full-mode surface, so pulling it here would ship libraries this image
    # has no surface for.
    assert "--group full" not in media_step
