"""Provider reachability probe used by offline-aware routing."""

import app.services.connectivity as conn


def setup_function():
    conn.reset_cache()


def test_local_models_are_always_reachable(monkeypatch):
    # Even with every probe failing, an ollama/ model must never be probed.
    monkeypatch.setattr(conn, "_probe", lambda *a, **k: False)
    assert conn.provider_reachable("ollama/qwen2.5:14b-instruct") is True


def test_cloud_model_reflects_probe(monkeypatch):
    monkeypatch.setattr(conn, "_probe", lambda *a, **k: False)
    assert conn.provider_reachable("openai/gpt-5-mini") is False
    conn.reset_cache()
    monkeypatch.setattr(conn, "_probe", lambda *a, **k: True)
    assert conn.provider_reachable("openai/gpt-5-mini") is True


def test_result_is_cached(monkeypatch):
    calls = {"n": 0}

    def counting_probe(*a, **k):
        calls["n"] += 1
        return False

    monkeypatch.setattr(conn, "_probe", counting_probe)
    conn.provider_reachable("anthropic/claude-sonnet-5")
    conn.provider_reachable("anthropic/claude-sonnet-5")
    assert calls["n"] == 1, "second call within TTL must use the cache"


def test_is_cloud_model():
    assert conn.is_cloud_model("openai/gpt-5-mini")
    assert conn.is_cloud_model("anthropic/claude-sonnet-5")
    assert conn.is_cloud_model("gemini/gemini-2.0-flash")
    assert not conn.is_cloud_model("ollama/qwen2.5:14b-instruct")
