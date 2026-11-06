"""TEMPORARY: crashes one Windows worker so the crash-record step can be read once. Removed next commit."""

import ctypes
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="checks the Windows crash records only")
def test_a_native_crash_is_recorded():
    ctypes.string_at(0)
