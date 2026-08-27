"""Freeing a port must stop the listener and nothing else.

`lsof -ti :PORT` matches every socket on the port, clients included. A browser
tab left open on http://127.0.0.1:7820 holds a CLOSE_WAIT socket and was
returned by that query, so `make stop` SIGTERMed -- then SIGKILLed five seconds
later -- the user's browser, while the app it was asked to stop kept running.
Observed with Brave at PID 718. scripts/free_port.sh filters -sTCP:LISTEN.

Real processes on a real port, as in test_graph_lock.py: a mocked lsof would
only prove the mock still matches the mock.
"""

import shutil
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

FREE_PORT_SH = Path(__file__).resolve().parents[2] / "scripts" / "free_port.sh"

# Two structural skips, both real rather than defensive: the local Intel-Mac CI
# path builds its image from backend/ alone (Dockerfile.ci), so scripts/ is not
# in that context. GitHub CI runs `make ci` on ubuntu-latest against the whole
# checkout, which is where this test actually gates.
pytestmark = [
    pytest.mark.skipif(shutil.which("lsof") is None, reason="free_port.sh needs lsof"),
    pytest.mark.skipif(
        not FREE_PORT_SH.exists(),
        reason=f"{FREE_PORT_SH} not in this build context (backend-only CI image)",
    ),
]


def _free_tcp_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _spawn(src: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", textwrap.dedent(src)])


def _wait_until(predicate, timeout=10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def listener_and_client():
    """A listener on a port, and a separate process holding a connection to it."""
    port = _free_tcp_port()
    listener = _spawn(f"""
        import socket, time
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", {port}))
        s.listen(5)
        while True:
            try:
                s.accept()
            except OSError:
                time.sleep(0.1)
    """)
    assert _wait_until(
        lambda: _can_connect(port)
    ), "listener never came up"

    client = _spawn(f"""
        import socket, time
        s = socket.create_connection(("127.0.0.1", {port}))
        time.sleep(120)
    """)
    time.sleep(1.0)
    assert client.poll() is None, "client died before the test began"

    yield port, listener, client

    for proc in (listener, client):
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


def _can_connect(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def test_frees_the_listener_and_spares_the_client(listener_and_client):
    port, listener, client = listener_and_client

    subprocess.run(
        ["sh", str(FREE_PORT_SH), str(port)], check=True, timeout=60,
        capture_output=True, text=True,
    )

    assert listener.poll() is not None, "the listener holding the port was not stopped"
    assert client.poll() is None, (
        "the client was killed -- free_port.sh matched a non-LISTEN socket, "
        "which is the browser-killing bug this test exists to prevent"
    )


def test_reports_a_free_port_without_signalling_anything(listener_and_client):
    """A port nobody listens on is a no-op, not an error."""
    port, _listener, client = listener_and_client
    unused = _free_tcp_port()

    result = subprocess.run(
        ["sh", str(FREE_PORT_SH), str(unused)], check=True, timeout=60,
        capture_output=True, text=True,
    )

    assert "nothing listening" in result.stdout
    assert client.poll() is None
