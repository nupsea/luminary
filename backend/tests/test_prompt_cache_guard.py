"""I-64 for an Ollama Luminary did not start: read its cap, and trim a runner that outgrew it.

The guard's threshold is bracketed by measured runners: capped at 512 MiB, 40 summary and
vision calls left 1.60 GB beyond the model; uncapped, the same calls passed 3 GB by call 13.
"""

import psutil
import pytest

from app.services import llm_admission, runtime_memory

GB = 1024**3
MODEL_SIZE = 3_412_255_046


@pytest.fixture(autouse=True)
def fresh_guard(monkeypatch):
    monkeypatch.setattr(runtime_memory, "_last_check", 0.0)
    monkeypatch.setattr(runtime_memory, "_unbounded", False)
    monkeypatch.setattr(runtime_memory, "_local_port", lambda: 11434)


class FakeRunner:
    def __init__(self, args=(), env=None, readable=True):
        self._args, self._env, self._readable = list(args), env or {}, readable

    def cmdline(self):
        return ["llama-server", "--model", "m.gguf", *self._args]

    def environ(self):
        if not self._readable:
            raise psutil.AccessDenied(1)
        return self._env


@pytest.mark.parametrize(
    ("runner", "cap"),
    [
        (FakeRunner(env={"LLAMA_ARG_CACHE_RAM": "512"}), 512),
        (FakeRunner(args=["--cache-ram", "0"]), 0),
        (FakeRunner(), 8192),
        (FakeRunner(readable=False), None),
    ],
)
def test_the_cap_is_read_from_flags_then_environment(runner, cap):
    assert runtime_memory.cache_cap_mib(runner) == cap


@pytest.mark.parametrize(("cap", "bounded"), [(0, True), (512, True), (2048, True), (8192, False)])
def test_a_cap_above_the_supervisor_clamp_is_unbounded(cap, bounded):
    assert runtime_memory._bounded(cap) is bounded


async def test_an_uncapped_runner_raises_the_banner(monkeypatch):
    monkeypatch.setattr(runtime_memory, "_read_caps", lambda port: [8192])
    assert await runtime_memory.check_prompt_cache_cap() is False
    assert runtime_memory.prompt_cache_unbounded()


async def test_an_unreadable_runner_raises_nothing(monkeypatch):
    monkeypatch.setattr(runtime_memory, "_read_caps", lambda port: [None])
    assert await runtime_memory.check_prompt_cache_cap() is None
    assert not runtime_memory.prompt_cache_unbounded()


def _server(monkeypatch, excess_bytes):
    calls = []

    async def fake_ollama(path, payload=None):
        calls.append((path, payload))
        return {"models": [{"name": "qwen3.5:4b", "size": MODEL_SIZE}]}

    monkeypatch.setattr(runtime_memory, "_ollama", fake_ollama)
    monkeypatch.setattr(runtime_memory, "_resident_bytes", lambda port: MODEL_SIZE + excess_bytes)
    return calls


async def test_a_ballooned_runner_is_unloaded(monkeypatch):
    calls = _server(monkeypatch, int(8.2e9))
    assert await runtime_memory.trim_if_ballooned()
    assert ("/api/generate", {"model": "qwen3.5:4b", "keep_alive": 0}) in calls
    assert runtime_memory.prompt_cache_unbounded()


async def test_a_capped_runner_at_its_measured_peak_is_left_alone(monkeypatch):
    calls = _server(monkeypatch, int(1.60e9))
    assert not await runtime_memory.trim_if_ballooned()
    assert [path for path, _ in calls] == ["/api/ps"]
    assert not runtime_memory.prompt_cache_unbounded()


async def test_the_check_is_throttled(monkeypatch):
    calls = _server(monkeypatch, int(8.2e9))
    assert await runtime_memory.trim_if_ballooned()
    seen = len(calls)
    assert not await runtime_memory.trim_if_ballooned()
    assert len(calls) == seen


async def test_no_runner_means_no_request(monkeypatch):
    calls = _server(monkeypatch, 0)
    monkeypatch.setattr(runtime_memory, "_resident_bytes", lambda port: 0)
    assert not await runtime_memory.trim_if_ballooned()
    assert calls == []


async def test_the_gate_trims_only_with_nothing_in_flight(monkeypatch):
    trims = []

    async def fake_trim():
        trims.append(True)
        return False

    monkeypatch.setattr(llm_admission, "trim_if_ballooned", fake_trim)
    # Off, so a background call beside an interactive one is admitted instead of held.
    monkeypatch.setattr(llm_admission, "admission_enabled", lambda: False)
    async with llm_admission.background_call():
        pass
    assert trims == [True]

    async with llm_admission.interactive_call():
        async with llm_admission.background_call():
            pass
    assert trims == [True]
