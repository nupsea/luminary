"""A company laptop behind a TLS-inspecting proxy, with no GPU, on 0.13.3.

Every encoder download failed on the proxy's certificate, the setup screen blamed
"the local model server", a 3.2GB model the host refuses was offered anyway, and
five problem reports came out of one setup screen.
"""

import asyncio
import os
import ssl

import httpx
import pytest
import truststore
import urllib3.util.ssl_

from app.services import components, model_prefetch, network_errors, warmup
from app.services.startup_status import get_startup_status

# Real failure text, from that laptop's reports and from Ollama's Go client.
_HUB_INSPECTED = (
    "(MaxRetryError(\"HTTPSConnectionPool(host='huggingface.co', port=443): Max retries "
    "exceeded with url: /api/models/BAAI/bge-small-en-v1.5/revision/main (Caused by "
    "SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate "
    "verify failed: self-signed certificate in certificate chain (_ssl.c:1032)')))\"))"
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_HUB_INSPECTED, "inspected"),
        (
            "pull model manifest: tls: failed to verify certificate: x509: certificate "
            "signed by unknown authority",
            "inspected",
        ),
        ("max retries exceeded: EOF", "cut"),
        ("dial tcp: lookup registry.ollama.ai: no such host", "dns"),
        ("proxyconnect tcp: dial tcp 10.0.0.1:8080: connect: connection refused", "proxy"),
        ("HTTPSConnectionPool(host='x', port=443): [Errno 61] Connection refused", "refused"),
        ("ReadTimeout: HTTPSConnectionPool(host='x', port=443): Read timed out.", "timeout"),
        ("model 'qwen3.5:4b' not found", None),
        ("GEOFFREY", None),
    ],
)
def test_network_failures_are_named_by_class(text, expected):
    assert network_errors.kind(text) == expected
    said = network_errors.explain(text)
    assert (said is None) == (expected is None)
    if said:
        assert said.endswith(".") and "Errno" not in said


def test_tls_is_verified_against_the_os_trust_store():
    """I-59: certifi's bundle rejects a company's inspecting proxy that Windows trusts."""
    import app  # noqa: F401  -- the injection happens on package import

    assert ssl.SSLContext is truststore.SSLContext
    assert isinstance(httpx.create_ssl_context(), truststore.SSLContext)
    assert isinstance(urllib3.util.ssl_.create_urllib3_context(), truststore.SSLContext)


def test_a_configured_proxy_is_not_reported_as_offline(monkeypatch):
    """Behind a proxy a direct socket fails, yet the download itself would work."""
    import socket

    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")

    def _no_socket(*a, **k):
        raise AssertionError("probed a direct connection behind a proxy")

    monkeypatch.setattr(socket, "create_connection", _no_socket)
    assert model_prefetch.hub_reachable(timeout=0.1) is True


def test_only_the_embedder_is_fetched_without_being_asked(monkeypatch):
    """The entity and ranking models are the user's choice, installed from Settings."""
    auto = {s.key for s in model_prefetch.specs() if not s.on_request}
    assert auto == {"embedder"}

    monkeypatch.setattr(model_prefetch, "is_cached", lambda spec: False)
    monkeypatch.setattr(model_prefetch, "hub_reachable", lambda *a, **k: True)
    fetched: list[str] = []
    monkeypatch.setattr(
        model_prefetch,
        "prefetch",
        lambda specs, *a, **k: fetched.extend(s.key for s in specs) or {},
    )

    async def _noop():
        return None

    for name in ("_load_embedder", "_load_ner", "_load_reranker", "_warm_llm"):
        monkeypatch.setattr(warmup, name, _noop)
    monkeypatch.setattr(warmup, "_check_vision_model", _noop)

    asyncio.run(warmup.run_warmup())

    assert fetched == ["embedder"]
    phases = {p["key"]: p for p in get_startup_status().snapshot()["phases"]}
    assert phases["ner"]["state"] == "missing"
    assert phases["reranker"]["state"] == "missing"


def _refusing_host(monkeypatch, message="This system isn't supported."):
    from app import host_support
    from app.services import llm_routing

    monkeypatch.setattr(llm_routing, "refusal", lambda role: "refused")
    monkeypatch.setattr(
        host_support,
        "local_inference_support",
        lambda: host_support.HostSupport(False, "no_accelerator", "Windows/AMD64", message),
    )


def test_a_host_that_refuses_local_models_is_not_a_setup_failure(monkeypatch):
    _refusing_host(monkeypatch)
    status = get_startup_status()

    asyncio.run(warmup._warm_llm())
    asyncio.run(warmup._check_vision_model())

    snap = status.snapshot()
    phases = {p["key"]: p for p in snap["phases"]}
    assert phases["chat_model"]["state"] == "unavailable"
    assert phases["vision_model"]["state"] == "unavailable"
    assert phases["chat_model"]["detail"] == "This system isn't supported."
    assert not {"chat_model", "vision_model"} & set(snap["failed"])


def _advice_for(comp_id, host):
    comp = components.get_component(comp_id)
    assert comp is not None, comp_id
    return components._advice(comp, host)


def test_local_models_are_not_offered_where_the_host_refuses_them(monkeypatch):
    refused = components._Host(local_models=False, refusal="No GPU here.", ram_gb=32)
    for comp_id in ("chat_model", "vision_model"):
        advice = _advice_for(comp_id, refused)
        assert advice == {"offered": False, "recommended": False, "advice": "No GPU here."}

    monkeypatch.setattr(components, "_host_facts", lambda: refused)
    pulled: list = []

    async def _pull(model):
        pulled.append(model)
        yield {"state": "ready"}

    monkeypatch.setattr(components, "install_ollama_model", _pull)

    async def _run():
        return [e async for e in components.install_component("vision_model")]

    events = asyncio.run(_run())
    assert pulled == []
    assert events == [{"state": "failed", "detail": "No GPU here."}]


def test_recommendations_follow_the_host():
    small = components._Host(local_models=False, refusal="x", ram_gb=8)
    large = components._Host(local_models=True, refusal=None, ram_gb=32)

    assert _advice_for("reranker", small)["recommended"] is True
    assert _advice_for("ner", small)["recommended"] is False
    assert _advice_for("ner", small)["offered"] is True
    assert _advice_for("ner", large)["recommended"] is True
    assert _advice_for("chat_model", large)["recommended"] is True
    assert _advice_for("vision_model", large)["recommended"] is False


def test_a_failed_model_pull_names_the_network_not_go(monkeypatch):
    """Ollama reported 'max retries exceeded: EOF' after its parts were cut off."""

    def _handler(request):
        body = b'{"status":"pulling manifest"}\n{"error":"max retries exceeded: EOF"}\n'
        return httpx.Response(200, content=body)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        components.httpx,
        "AsyncClient",
        lambda **k: real(transport=httpx.MockTransport(_handler), **k),
    )

    async def _run():
        return [e async for e in components.install_ollama_model("qwen3.5:4b")]

    last = asyncio.run(_run())[-1]
    assert last["state"] == "failed"
    assert last["detail"] == network_errors.explain("EOF")


def _pin(monkeypatch, env_proxies, system_proxies, environ):
    import urllib.request

    from app import proxy_env

    monkeypatch.setattr(urllib.request, "getproxies_environment", lambda: dict(env_proxies))
    monkeypatch.setattr(urllib.request, "getproxies", lambda: dict(system_proxies))
    monkeypatch.setattr(proxy_env, "_windows_bypass", lambda: ["intranet.example"])
    proxy_env.pin_system_proxy(environ)
    return environ


def test_a_system_proxy_is_used_for_the_internet_and_never_for_this_machine(monkeypatch):
    """httpx reads the Windows proxy but not its bypass list, so calls to Ollama on
    127.0.0.1 went to a company proxy that cannot reach this computer."""
    system = {"http": "http://proxy.corp:8080", "https": "http://proxy.corp:8080"}
    environ = _pin(monkeypatch, {}, system, {})

    assert environ["https_proxy"] == "http://proxy.corp:8080"
    no_proxy = environ["no_proxy"].split(",")
    assert {"localhost", "127.0.0.1", "::1", "intranet.example"} <= set(no_proxy)

    import urllib.request

    monkeypatch.undo()  # the pinned environment alone decides, as it will in the app
    for key in [k for k in os.environ if k.lower().endswith("_proxy")]:
        monkeypatch.delenv(key)
    for key, value in environ.items():
        monkeypatch.setenv(key, value)
    mounts = httpx._utils.get_environment_proxies()
    assert mounts["all://127.0.0.1"] is None
    assert mounts["https://"] == "http://proxy.corp:8080"
    assert urllib.request.proxy_bypass_environment("127.0.0.1")


def test_an_explicit_proxy_keeps_its_bypass_list_and_gains_loopback(monkeypatch):
    environ = _pin(
        monkeypatch,
        {"https": "http://p:3128", "no": "git.corp,127.0.0.1"},
        {},
        {"HTTPS_PROXY": "http://p:3128"},
    )
    assert environ["no_proxy"].split(",")[:2] == ["git.corp", "127.0.0.1"]
    assert "localhost" in environ["no_proxy"].split(",")
    assert "https_proxy" not in environ


def test_no_proxy_configured_changes_nothing(monkeypatch):
    assert _pin(monkeypatch, {}, {}, {}) == {}


def test_a_scanning_proxy_has_time_to_release_a_large_model():
    """Behind a proxy that holds the whole file before sending any of it, the 1.1GB
    entity model failed at the hub's 10s read timeout and installed at 300s (61s)."""
    from huggingface_hub import constants

    import app  # noqa: F401  -- sets the default before huggingface_hub reads it

    assert constants.HF_HUB_DOWNLOAD_TIMEOUT >= 300
