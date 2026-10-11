"""I-64 for an Ollama we did not start: read its cap, name its fix, trim a runner that outgrew it.

The guard's threshold is bracketed by measured runners: capped at 512 MiB, 40 summary and
vision calls left 1.60 GB beyond the model; uncapped, the same calls passed 3 GB by call 13.
"""

import subprocess
import sys

import psutil
import pytest

from app.services import llm_admission, runtime_memory

GB = 1024**3
MODEL_SIZE = 3_412_255_046


@pytest.fixture(autouse=True)
def fresh_guard(monkeypatch):
    monkeypatch.setattr(runtime_memory, "_last_check", 0.0)
    monkeypatch.setattr(runtime_memory, "_ballooned_pid", None)
    monkeypatch.setattr(runtime_memory, "_local_port", lambda: 11434)


class FakeProcess:
    def __init__(self, args=(), env=None, readable=True, exe="/opt/homebrew/bin/ollama", pid=4242):
        self._args, self._env, self._readable = list(args), env or {}, readable
        self._exe, self.pid, self.runners = exe, pid, []

    def cmdline(self):
        return ["llama-server", "--model", "m.gguf", *self._args]

    def environ(self):
        if not self._readable:
            raise psutil.AccessDenied(1)
        return self._env

    def exe(self):
        return self._exe

    def children(self, recursive=False):
        return self.runners

    def name(self):
        return "llama-server"


@pytest.mark.parametrize(
    ("runner", "cap"),
    [
        (FakeProcess(env={"LLAMA_ARG_CACHE_RAM": "512"}), 512),
        (FakeProcess(args=["--cache-ram", "0"]), 0),
        (FakeProcess(), 8192),
        (FakeProcess(readable=False), None),
    ],
)
def test_the_cap_is_read_from_flags_then_environment(runner, cap):
    assert runtime_memory.cache_cap_mib(runner) == cap


@pytest.mark.parametrize(("cap", "bounded"), [(0, True), (512, True), (2048, True), (8192, False)])
def test_a_cap_above_the_supervisor_clamp_is_unbounded(cap, bounded):
    assert runtime_memory._bounded(cap) is bounded


# How the server was started decides its fix: `launchctl setenv` never reaches an
# `ollama serve` started from a terminal, which is how the banner first misled.


@pytest.mark.parametrize(
    ("platform", "server", "launch"),
    [
        (
            "darwin",
            FakeProcess(exe="/Applications/Ollama.app/Contents/Resources/ollama"),
            ("macos_app", None),
        ),
        (
            "darwin",
            FakeProcess(env={"XPC_SERVICE_NAME": "homebrew.mxcl.ollama"}),
            ("launchd", "homebrew.mxcl.ollama"),
        ),
        ("darwin", FakeProcess(env={"XPC_SERVICE_NAME": "0"}), ("terminal", None)),
        (
            "darwin",
            FakeProcess(env={"XPC_SERVICE_NAME": "application.com.microsoft.VSCode.1.2"}),
            ("terminal", None),
        ),
        ("darwin", FakeProcess(readable=False), ("terminal", None)),
        ("win32", FakeProcess(), ("windows", None)),
    ],
)
def test_the_launch_is_named(monkeypatch, platform, server, launch):
    monkeypatch.setattr(sys, "platform", platform)
    assert runtime_memory._launch(server) == launch


@pytest.mark.parametrize(
    ("cgroup", "unit"),
    [
        ("0::/system.slice/ollama.service\n", "ollama.service"),
        ("0::/user.slice/user-1000.slice/session-2.scope\n", None),
        ("0::/user.slice/user-1000.slice/user@1000.service/app.slice/vte-spawn-1.scope\n", None),
        ("0::/user.slice/user-1000.slice/user@1000.service\n", None),
    ],
)
def test_only_a_system_unit_is_systemd(cgroup, unit):
    assert runtime_memory._unit_of(cgroup) == unit


def _systemctl(monkeypatch, stdout):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    monkeypatch.setattr(runtime_memory.subprocess, "run", fake_run)


def test_a_system_unit_s_environment_is_read_through_systemctl(monkeypatch):
    _systemctl(monkeypatch, 'Environment="PATH=/usr/bin" LLAMA_ARG_CACHE_RAM=512\n')
    assert runtime_memory._systemd_env("ollama.service")["LLAMA_ARG_CACHE_RAM"] == "512"


def test_an_environment_file_makes_a_missing_cap_unknowable(monkeypatch):
    _systemctl(monkeypatch, "Environment=PATH=/usr/bin\nEnvironmentFiles=/etc/ollama.env\n")
    assert runtime_memory._systemd_env("ollama.service") is None


def test_a_loaded_runner_outranks_the_server_environment():
    server = FakeProcess(env={})
    server.runners = [FakeProcess(env={"LLAMA_ARG_CACHE_RAM": "512"})]
    assert runtime_memory._server_cap(server, None) == 512


def test_with_no_model_loaded_the_server_environment_decides():
    assert runtime_memory._server_cap(FakeProcess(env={"LLAMA_ARG_CACHE_RAM": "512"}), None) == 512
    assert runtime_memory._server_cap(FakeProcess(env={}), None) == 8192


def test_another_user_s_server_is_read_from_its_unit(monkeypatch):
    _systemctl(monkeypatch, "Environment=LLAMA_ARG_CACHE_RAM=512\n")
    server = FakeProcess(readable=False)
    assert runtime_memory._server_cap(server, "ollama.service") == 512
    assert runtime_memory._server_cap(server, None) is None


def _serving(monkeypatch, server):
    monkeypatch.setattr(runtime_memory, "_server", lambda port: server)
    monkeypatch.setattr(sys, "platform", "darwin")


async def test_an_uncapped_server_raises_the_banner(monkeypatch):
    _serving(monkeypatch, FakeProcess(env={"XPC_SERVICE_NAME": "0"}))
    status = await runtime_memory.prompt_cache_status()
    assert status == runtime_memory.PromptCacheStatus(True, "terminal")


async def test_a_restarted_capped_server_clears_the_banner(monkeypatch):
    _serving(monkeypatch, FakeProcess(env={}, pid=1))
    assert (await runtime_memory.prompt_cache_status()).unbounded
    _serving(monkeypatch, FakeProcess(env={"LLAMA_ARG_CACHE_RAM": "512"}, pid=2))
    assert not (await runtime_memory.prompt_cache_status()).unbounded


async def test_an_unreadable_server_raises_nothing(monkeypatch):
    _serving(monkeypatch, FakeProcess(readable=False))
    assert await runtime_memory.prompt_cache_status() is None
    _serving(monkeypatch, None)
    assert await runtime_memory.prompt_cache_status() is None


async def test_a_balloon_holds_the_banner_until_that_server_restarts(monkeypatch):
    monkeypatch.setattr(runtime_memory, "_ballooned_pid", 1)
    _serving(monkeypatch, FakeProcess(env={"LLAMA_ARG_CACHE_RAM": "512"}, pid=1))
    assert (await runtime_memory.prompt_cache_status()).unbounded
    _serving(monkeypatch, FakeProcess(env={"LLAMA_ARG_CACHE_RAM": "512"}, pid=2))
    assert not (await runtime_memory.prompt_cache_status()).unbounded


async def test_host_support_reports_the_status_as_it_stands(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    status = runtime_memory.PromptCacheStatus(True, "launchd", "homebrew.mxcl.ollama")

    async def fake_status():
        return status

    monkeypatch.setattr(runtime_memory, "prompt_cache_status", fake_status)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/setup/host-support")).json()
        assert body["prompt_cache_unbounded"] is True
        assert body["ollama_launch"] == "launchd"
        assert body["ollama_service"] == "homebrew.mxcl.ollama"

        status = runtime_memory.PromptCacheStatus(False, "launchd", "homebrew.mxcl.ollama")
        body = (await client.get("/setup/host-support")).json()
        assert body["prompt_cache_unbounded"] is False


def _server(monkeypatch, excess_bytes):
    calls = []

    async def fake_ollama(path, payload=None):
        calls.append((path, payload))
        return {"models": [{"name": "qwen3.5:4b", "size": MODEL_SIZE}]}

    monkeypatch.setattr(runtime_memory, "_ollama", fake_ollama)
    monkeypatch.setattr(
        runtime_memory, "_resident_bytes", lambda port: (7, MODEL_SIZE + excess_bytes)
    )
    return calls


async def test_a_ballooned_runner_is_unloaded(monkeypatch):
    calls = _server(monkeypatch, int(8.2e9))
    assert await runtime_memory.trim_if_ballooned()
    assert ("/api/generate", {"model": "qwen3.5:4b", "keep_alive": 0}) in calls
    assert runtime_memory._ballooned_pid == 7


async def test_a_capped_runner_at_its_measured_peak_is_left_alone(monkeypatch):
    calls = _server(monkeypatch, int(1.60e9))
    assert not await runtime_memory.trim_if_ballooned()
    assert [path for path, _ in calls] == ["/api/ps"]
    assert runtime_memory._ballooned_pid is None


async def test_the_check_is_throttled(monkeypatch):
    calls = _server(monkeypatch, int(8.2e9))
    assert await runtime_memory.trim_if_ballooned()
    seen = len(calls)
    assert not await runtime_memory.trim_if_ballooned()
    assert len(calls) == seen


async def test_no_runner_means_no_request(monkeypatch):
    calls = _server(monkeypatch, 0)
    monkeypatch.setattr(runtime_memory, "_resident_bytes", lambda port: (7, 0))
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
