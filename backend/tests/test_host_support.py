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

    # conftest pins LUMINARY_HOST_SUPPORTED for the whole session so the suite does
    # not read the hardware it runs on. These are the tests of the rule itself, so
    # they are the ones that must see it unset. Cleared here at fixture setup, not
    # inside `_set`: the two tests that set it deliberately do so in the test body,
    # which runs after this and would otherwise be undone.
    monkeypatch.delenv("LUMINARY_HOST_SUPPORTED", raising=False)

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


# The deployment's own declaration
#
# Under compose the model runs in a *sibling* container and `make
# docker-run-host-ollama` puts it on the host, so the app container has no device
# node to find however fast inference actually is. The thing that knows is the
# deployment, and `docker-compose.gpu.yml` says so.


def test_a_deployment_can_declare_the_accelerator(host, monkeypatch):
    monkeypatch.setenv("LUMINARY_HOST_SUPPORTED", "1")
    v = host("Linux", "aarch64", container=True, accel=False)
    assert v.supported is True
    assert "LUMINARY_HOST_SUPPORTED set" in v.detail


def test_the_declaration_overrides_even_the_intel_mac_refusal(host, monkeypatch):
    # An operator who sets it has been told what it means. The refusal is there
    # to stop a surprise, not to overrule someone who has decided.
    monkeypatch.setenv("LUMINARY_HOST_SUPPORTED", "1")
    assert host("Darwin", "x86_64", container=False, accel=False).supported is True


def test_a_present_but_empty_declaration_declares_nothing(host, monkeypatch):
    # An unset compose variable interpolates to "", which must not read as yes.
    monkeypatch.setenv("LUMINARY_HOST_SUPPORTED", "")
    assert host("Darwin", "x86_64", container=False, accel=False).supported is False


# Refusing the call, not just describing the host
#
# The refusal lives at the point a call is issued, keyed on the model that will
# actually run -- not in `get_effective_routing`, which describes a route as
# often as it picks one. Raising there broke role resolution, which only asks
# what an 8GB host *would* resolve to.


@pytest.fixture
def routing(monkeypatch):
    """Drive llm_mode with the module cache restored afterwards."""
    from app.services import settings_service as ss

    original = dict(ss._cache)
    yield ss
    ss._cache.clear()
    ss._cache.update(original)


def _unsupported():
    from app.host_support import HostSupport

    return HostSupport(False, "intel_mac", "Darwin/x86_64", "no local models here")


@pytest.mark.parametrize("background", [False, True])
def test_a_local_call_is_refused_on_an_unsupported_host(routing, background):
    from app.exceptions import DependencyUnavailable
    from app.services.llm import LLMService

    routing._cache.update({"llm_mode": "private"})
    with patch("app.host_support.local_inference_support", return_value=_unsupported()):
        with pytest.raises(DependencyUnavailable) as excinfo:
            LLMService()._resolve_model(None, background=background)
    # 503, and carrying why -- a refusal nobody can act on is the failure mode.
    assert excinfo.value.status_code == 503
    assert excinfo.value.extra["reason"] == "intel_mac"


def test_a_pinned_local_model_is_refused_on_the_same_terms(routing):
    # An explicit override used to return before any check ran, so pinning the
    # model was a way around the refusal.
    from app.exceptions import DependencyUnavailable
    from app.services.llm import LLMService

    with patch("app.host_support.local_inference_support", return_value=_unsupported()):
        with pytest.raises(DependencyUnavailable):
            LLMService()._resolve_model("ollama/qwen3.5:4b", background=False)


def test_a_key_still_answers_on_an_unsupported_host(routing):
    # I-16 and the message both promise this: the cloud arm is the way out the
    # refusal names, so it must not be refused alongside it.
    from app.services.llm import LLMService

    routing._cache.update(
        {
            "llm_mode": "hybrid",
            "cloud_provider": "openai",
            "cloud_model": "gpt-4o-mini",
            "openai_api_key": "sk-x",
        }
    )
    with patch("app.host_support.local_inference_support", return_value=_unsupported()):
        model, key = LLMService()._resolve_model(None, background=False)
    assert model == "openai/gpt-4o-mini"
    assert key == "sk-x"


def test_describing_a_route_is_never_refused(routing):
    """`get_effective_routing` must answer on an unsupported host.

    Role resolution and the environment report call it to ask what *would* run.
    Raising there failed `test_a_fresh_install_on_8gb_resolves_every_role_to_one_model`,
    which asks that question about a host this policy calls unsupported.
    """
    routing._cache.update({"llm_mode": "private"})
    with patch("app.host_support.local_inference_support", return_value=_unsupported()):
        model, key = routing.get_effective_routing(background=False)
    assert model.startswith("ollama/")
    assert key is None


def test_a_supported_host_calls_locally_as_before(routing):
    from app.host_support import HostSupport
    from app.services.llm import LLMService

    routing._cache.update({"llm_mode": "private"})
    ok = HostSupport(True, None, "Darwin/arm64", None)
    with patch("app.host_support.local_inference_support", return_value=ok):
        model, key = LLMService()._resolve_model(None, background=False)
    assert model.startswith("ollama/")
    assert key is None


def test_the_refusal_survives_the_llm_service_fallback(routing):
    """`_resolve_model` falls back to the default local model on any exception.

    That fallback runs on the path a refused host takes, so the check has to sit
    after it. Before it did, the fallback answered with the very model the
    refusal exists to stop.
    """
    from app.exceptions import DependencyUnavailable
    from app.services.llm import LLMService

    with (
        patch(
            "app.services.settings_service.get_effective_routing",
            side_effect=RuntimeError("routing blew up"),
        ),
        patch("app.host_support.local_inference_support", return_value=_unsupported()),
    ):
        with pytest.raises(DependencyUnavailable):
            LLMService()._resolve_model(None, background=False)
