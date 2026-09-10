"""Which hosts Luminary will offer local inference on, and why.

The rule is about the accelerator, never about Docker. A container with a GPU
passed through is a first-class host; a Mac running Docker Desktop is not, and
no configuration changes that -- Apple's Virtualization.framework exposes
neither Metal nor the Neural Engine to the VM. Measured on the case that
prompted this: an Intel Mac through Docker decodes at ~6 tok/s and takes ~121s
to answer one question.
"""

from unittest.mock import patch

import pytest

from app.host_support import UNSUPPORTED_MESSAGE, local_inference_support


@pytest.fixture
def host(monkeypatch):
    """Drive the three inputs the verdict reads."""

    def _set(system: str, machine: str, *, container: bool, accel: bool, ram: int = 32):
        monkeypatch.setattr("platform.system", lambda: system)
        monkeypatch.setattr("platform.machine", lambda: machine)
        monkeypatch.setattr("app.host_support._in_container", lambda: container)
        monkeypatch.setattr("app.host_support._has_accelerator", lambda: accel)
        monkeypatch.setattr("app.memory_profile.host_ram_gb", lambda: ram)
        return local_inference_support()

    return _set


def test_apple_silicon_is_supported(host):
    v = host("Darwin", "arm64", container=False, accel=True)
    assert v.supported is True
    assert v.reason is None
    assert v.message is None


def test_an_intel_mac_is_not(host):
    v = host("Darwin", "x86_64", container=False, accel=False)
    assert v.supported is False
    assert v.reason == "intel_mac"
    assert v.message == UNSUPPORTED_MESSAGE


def test_a_mac_in_docker_is_not_either(host):
    # What the container actually reports: it cannot see it is on a Mac, and it
    # does not need to. No accelerator reaches it, which is the deciding fact.
    v = host("Linux", "aarch64", container=True, accel=False)
    assert v.supported is False
    assert v.reason == "container_without_accelerator"


def test_a_container_with_a_gpu_is_supported(host):
    # The rule is the accelerator, not Docker. Linux with the NVIDIA container
    # toolkit is a fast host and must not be refused for being containerised.
    v = host("Linux", "x86_64", container=True, accel=True)
    assert v.supported is True


def test_bare_metal_without_an_accelerator_is_refused_the_same_way(host):
    v = host("Linux", "x86_64", container=False, accel=False)
    assert v.supported is False
    assert v.reason == "no_accelerator"


def test_a_gpu_does_not_excuse_too_little_memory(host):
    # 16GB is memory_profile._STANDARD_MIN_RAM_GB. Docker Desktop hands its VM
    # roughly half the host, which is how a 16GB Mac presents as 7GB.
    v = host("Linux", "x86_64", container=True, accel=True, ram=7)
    assert v.supported is False
    assert v.reason == "under_memory_floor"
    assert "7GB" in v.detail


def test_unreadable_memory_is_not_by_itself_a_refusal(host):
    # host_ram_gb() answers 0 when it cannot read the machine. A host that got
    # this far has an accelerator; refusing it on an unknown number would
    # refuse working machines to no purpose.
    v = host("Linux", "x86_64", container=False, accel=True, ram=0)
    assert v.supported is True


def test_the_message_names_both_ways_forward():
    # I-16: no key must keep meaning a working app, so the message may not read
    # as a lock-out. It has to name the key arm and the hosted version.
    assert "API key" in UNSUPPORTED_MESSAGE
    assert "coming soon" in UNSUPPORTED_MESSAGE
    assert "work as normal" in UNSUPPORTED_MESSAGE


async def test_the_endpoint_reports_this_host():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/setup/host-support")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"supported", "reason", "host", "message"}
    assert isinstance(body["supported"], bool)
    # Supported hosts carry no message; unsupported ones must carry one.
    assert (body["message"] is None) is body["supported"]


def test_docker_alone_never_decides_it():
    """A container is not the disqualifier -- the missing accelerator is.

    Guards the mistake this module exists to avoid: refusing Docker as a class
    would refuse the Linux/NVIDIA host that is the fastest way to run Luminary,
    and would delete the shape the hosted version is going to be built in.
    """
    with (
        patch("app.host_support._in_container", return_value=True),
        patch("app.host_support._has_accelerator", return_value=True),
        patch("platform.system", return_value="Linux"),
        patch("platform.machine", return_value="x86_64"),
        patch("app.memory_profile.host_ram_gb", return_value=64),
    ):
        assert local_inference_support().supported is True
