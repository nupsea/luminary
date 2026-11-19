"""A test that reaches its timeout names itself in the job log before its worker ends.

pytest-timeout's `thread` method (the only one on Windows) writes its dump to the
worker's terminal and calls `os._exit(1)`. Under xdist that terminal is never forwarded,
so CI showed only "node down: Not properly terminated" and an exit status of 1, with no
test named (#211, #476). A worker's own stderr does reach the log, so the test and every
thread's stack are written there a moment before pytest-timeout ends the worker.
"""

import faulthandler
import sys
import threading

import pytest

_LEAD_S = 1.0
_pending: threading.Timer | None = None


def _report(item: pytest.Item, timeout: float) -> None:
    # Capture holds fd 2 while a test runs; released, the write reaches the real stderr.
    capman = item.config.pluginmanager.getplugin("capturemanager")
    if capman is not None:
        capman.suspend_global_capture(item)
    err = sys.__stderr__
    err.write(f"\n+++ {item.nodeid} reached its {timeout:.0f}s timeout; its worker ends next +++\n")
    faulthandler.dump_traceback(file=err, all_threads=True)
    err.flush()


@pytest.hookimpl(tryfirst=True)
def pytest_timeout_set_timer(item, settings):
    global _pending
    if settings.timeout and settings.timeout > _LEAD_S:
        _pending = threading.Timer(settings.timeout - _LEAD_S, _report, (item, settings.timeout))
        _pending.daemon = True
        _pending.start()
    # None: pytest-timeout still arms its own timer and ends the test.


@pytest.hookimpl(tryfirst=True)
def pytest_timeout_cancel_timer(item):
    global _pending
    if _pending is not None:
        _pending.cancel()
        _pending = None
