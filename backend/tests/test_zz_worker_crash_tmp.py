"""TEMPORARY: crashes one Windows worker so the crash-record step is read once."""

import ctypes
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="checks the Windows crash records only")
def test_a_native_crash_is_recorded():
    # ctypes turns an access violation into OSError; fail-fast skips every handler.
    ctypes.windll.kernel32.RaiseFailFastException(None, None, 0)
