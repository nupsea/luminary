"""A refused write is explained from the folder, never shown as a bare mkdir error."""

import os
import sys

import pytest

from app.services import storage_errors

_MESSAGE = "mkdir {}: operation not permitted"


def test_an_unrelated_error_is_left_to_other_explainers():
    assert storage_errors.explain("connection refused") is None


def test_a_writable_folder_refused_on_macos_names_full_disk_access(tmp_path, monkeypatch):
    """The fresh macOS 27 install: the folder allowed the write and the system refused it."""
    monkeypatch.setattr(storage_errors.sys, "platform", "darwin")
    text = storage_errors.explain(_MESSAGE.format(tmp_path / "manifests" / "registry.ollama.ai"))
    assert text is not None
    assert str(tmp_path) in text
    assert "Quit Luminary" in text and "Full Disk Access" in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_a_read_only_folder_names_the_finder_fix(tmp_path):
    locked = tmp_path / "models"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("running as a user that ignores permission bits")
        text = storage_errors.explain(_MESSAGE.format(locked / "manifests"))
        assert text is not None
        assert "cannot write to it" in text and "Get Info" in text
        assert "Full Disk Access" not in text
    finally:
        locked.chmod(0o700)


def test_another_owner_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_errors.os, "getuid", lambda: os.stat(tmp_path).st_uid + 1)
    assert storage_errors.folder_problem(tmp_path) is not None
    assert "another account" in storage_errors.folder_problem(tmp_path)


def test_a_writable_folder_has_no_problem(tmp_path):
    assert storage_errors.folder_problem(tmp_path / "not-yet-created") is None
