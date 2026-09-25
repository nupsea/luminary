"""A graphics driver on disk is not a card the model server can use.

The device check passed a Windows T4: `nvcuda.dll` was there, and Ollama put 0 B
of the model on the card and ran it on the processor. Only a load can tell, so
the first one is measured (`/api/ps`) and a model held entirely by the processor
turns the host unsupported, with the same banner and the same refusal as a host
that has no card at all.
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app import host_support
from app.services import warmup
from app.services.startup_status import get_startup_status

_MODEL = "qwen3.5:4b"
_SIZE = 3_400_000_000


@pytest.fixture(autouse=True)
def gpu_host(monkeypatch):
    """A Windows host whose device check passes, with nothing measured yet."""
    from app.config import get_settings  # noqa: PLC0415

    monkeypatch.delenv("LUMINARY_HOST_SUPPORTED", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    monkeypatch.setattr("app.host_support._in_container", lambda: False)
    monkeypatch.setattr("app.host_support._has_accelerator", lambda: True)
    monkeypatch.setattr("app.memory_profile.host_ram_gb", lambda: 32)
    host_support._offload_path().unlink(missing_ok=True)
    host_support.forget_offload()
    yield
    host_support._offload_path().unlink(missing_ok=True)
    host_support.forget_offload()
    get_settings.cache_clear()


# The rule


def test_a_model_held_by_the_processor_makes_the_host_unsupported():
    assert host_support.local_inference_support().supported
    host_support.record_offload(_MODEL, _SIZE, 0)

    verdict = host_support.local_inference_support()
    assert not verdict.supported
    assert verdict.reason == "gpu_unused"
    assert verdict.message == host_support.UNSUPPORTED_MESSAGE
    assert "processor" in verdict.detail


def test_a_model_on_the_card_keeps_the_host_supported():
    host_support.record_offload(_MODEL, _SIZE, _SIZE)
    assert host_support.local_inference_support().supported


def test_a_model_partly_on_the_card_is_not_refused():
    # Only "none of it" is measured to mean the card is unused (the T4). A split
    # is slower, not a different product, and is not refused on a guess.
    host_support.record_offload(_MODEL, _SIZE, _SIZE // 3)
    assert host_support.local_inference_support().supported


def test_the_measurement_survives_a_relaunch():
    host_support.record_offload(_MODEL, _SIZE, 0)
    host_support.forget_offload()
    assert host_support.local_inference_support().reason == "gpu_unused"


def test_an_upgrade_measures_again(monkeypatch):
    host_support.record_offload(_MODEL, _SIZE, 0)
    saved = json.loads(host_support._offload_path().read_text())
    saved["app_version"] = "0.0.1"
    host_support._offload_path().write_text(json.dumps(saved))
    host_support.forget_offload()

    assert host_support.measured_offload() is None
    assert host_support.local_inference_support().supported


def test_an_unreadable_measurement_is_no_measurement():
    host_support._offload_path().write_text("{not json")
    host_support.forget_offload()
    assert host_support.measured_offload() is None
    assert host_support.local_inference_support().supported


def test_a_declared_accelerator_outranks_the_measurement(monkeypatch):
    host_support.record_offload(_MODEL, _SIZE, 0)
    monkeypatch.setenv("LUMINARY_HOST_SUPPORTED", "1")
    assert host_support.local_inference_support().supported


def test_the_device_reason_still_wins_where_the_device_check_fails(monkeypatch):
    host_support.record_offload(_MODEL, _SIZE, 0)
    monkeypatch.setattr("app.host_support._has_accelerator", lambda: False)
    assert host_support.local_inference_support().reason == "no_accelerator"


# The measurement, at warm-up


def _ollama(monkeypatch, loaded: list[dict]) -> list[httpx.Request]:
    """Serve `/api/ps` from *loaded*; record every request."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": loaded})
        return httpx.Response(200, json={})

    real = httpx.AsyncClient
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(warmup.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))

    async def generate(*_a, **_kw):
        return "pong"

    monkeypatch.setattr(
        "app.services.llm.get_llm_service", lambda: SimpleNamespace(generate=generate)
    )
    monkeypatch.setattr(
        "app.services.model_router.resolve",
        lambda role, **_kw: SimpleNamespace(model=f"ollama/{_MODEL}", is_local=True),
    )
    monkeypatch.setattr("app.services.llm_routing.refusal", lambda role: None)
    return seen


def _chat_phase() -> dict:
    return {p["key"]: p for p in get_startup_status().snapshot()["phases"]}["chat_model"]


def test_warmup_turns_the_host_when_the_model_lands_on_the_processor(monkeypatch):
    seen = _ollama(monkeypatch, [{"name": _MODEL, "model": _MODEL, "size": _SIZE, "size_vram": 0}])
    asyncio.run(warmup._warm_llm())

    assert _chat_phase()["state"] == "unavailable"
    assert _chat_phase()["detail"] == host_support.UNSUPPORTED_MESSAGE
    assert host_support.local_inference_support().reason == "gpu_unused"
    # The refused model is unloaded rather than left holding gigabytes.
    unload = [r for r in seen if r.url.path == "/api/generate"]
    assert len(unload) == 1
    assert json.loads(unload[0].content) == {"model": _MODEL, "keep_alive": 0}


def test_warmup_leaves_a_host_whose_card_holds_the_model(monkeypatch):
    _ollama(monkeypatch, [{"name": _MODEL, "model": _MODEL, "size": _SIZE, "size_vram": _SIZE}])
    asyncio.run(warmup._warm_llm())

    assert _chat_phase()["state"] == "ready"
    assert host_support.measured_offload().size_vram == _SIZE
    assert host_support.local_inference_support().supported


def test_a_model_the_server_no_longer_lists_records_nothing(monkeypatch):
    _ollama(monkeypatch, [{"name": "other:1b", "model": "other:1b", "size": 1, "size_vram": 0}])
    asyncio.run(warmup._warm_llm())

    assert _chat_phase()["state"] == "ready"
    assert host_support.measured_offload() is None


def test_a_declared_accelerator_keeps_the_phase_ready(monkeypatch):
    monkeypatch.setenv("LUMINARY_HOST_SUPPORTED", "1")
    _ollama(monkeypatch, [{"name": _MODEL, "model": _MODEL, "size": _SIZE, "size_vram": 0}])
    asyncio.run(warmup._warm_llm())

    assert _chat_phase()["state"] == "ready"


async def test_the_endpoint_says_whether_the_card_was_measured():
    from app.main import app  # noqa: PLC0415

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/setup/host-support")).json()["measured"] is False
        host_support.record_offload(_MODEL, _SIZE, 0)
        body = (await client.get("/setup/host-support")).json()
    assert body["measured"] is True
    assert body["supported"] is False
    assert body["reason"] == "gpu_unused"


def test_installing_the_chat_model_loads_it(monkeypatch):
    from app.services import components  # noqa: PLC0415

    async def pull(_model):
        yield {"state": "downloading", "detail": "pulling"}
        yield {"state": "ready", "detail": _MODEL}

    warmed: list[bool] = []
    monkeypatch.setattr(components, "install_ollama_model", pull)
    monkeypatch.setattr(warmup, "warm_chat_model", lambda: warmed.append(True))

    async def run():
        return [e async for e in components.install_component("chat_model")]

    events = asyncio.run(run())
    assert events[-1]["state"] == "ready"
    assert warmed == [True]


def test_changing_the_gpu_runner_measures_again(monkeypatch, tmp_path):
    # The T4 ran on the processor without the CUDA runner. Installing it is the
    # fix, so a verdict taken on the old runners must not outlive it.
    from app.services import components  # noqa: PLC0415

    runner = SimpleNamespace(id="cuda_runner", label="NVIDIA GPU acceleration", ref="cuda_v12")

    async def unpacked(**_kw):
        yield {"state": "ready", "detail": "done"}

    monkeypatch.setattr(
        components,
        "engine_source",
        lambda: {
            "url": "u",
            "sha256": "s",
            "asset": "a",
            "member_prefix": "p",
            "archive_bytes": 1,
        },
    )
    monkeypatch.setattr(components, "engine_lib_dir", lambda: tmp_path)
    monkeypatch.setattr(components, "install_archive_subset", unpacked)
    monkeypatch.setattr(components, "get_component", lambda _id: runner)

    host_support.record_offload(_MODEL, _SIZE, 0)

    async def install():
        return [e async for e in components.install_engine_runner(runner)]

    asyncio.run(install())
    assert host_support.measured_offload() is None
    assert not host_support._offload_path().exists()
    assert host_support.local_inference_support().supported

    host_support.record_offload(_MODEL, _SIZE, _SIZE)
    runner.kind = "engine_runner"
    asyncio.run(components.remove_component("cuda_runner"))
    assert host_support.measured_offload() is None
