import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def test_settings_defaults():
    # Temporarily remove env vars that could override defaults
    vars_to_pop = ["PHOENIX_ENABLED", "LITELLM_DEFAULT_MODEL", "LOG_LEVEL"]
    saved_vars = {}
    for var in vars_to_pop:
        if var in os.environ:
            saved_vars[var] = os.environ.pop(var)
    try:
        settings = Settings(_env_file=None)
        assert settings.LOG_LEVEL == "INFO"
        assert settings.LITELLM_DEFAULT_MODEL == "ollama/llama3.2"
        assert settings.PHOENIX_ENABLED is False
    finally:
        for var, val in saved_vars.items():
            os.environ[var] = val


def test_get_settings_returns_singleton():
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_unrendered_env_example_placeholders_do_not_block_startup(tmp_path, monkeypatch):
    """A verbatim copy of .env.example must boot on defaults: its placeholders
    land on typed fields (a Literal and two ints)."""
    example = Path(__file__).resolve().parents[1] / ".env.example"
    env_file = tmp_path / ".env"
    env_file.write_text(example.read_text())
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.LUMINARY_MODE == "full"
    assert settings.OLLAMA_NUM_PARALLEL == 1
    assert settings.ENRICHMENT_VISION_CONCURRENCY == 1


def test_a_real_typo_is_still_rejected(tmp_path, monkeypatch):
    """Only the exact @@NAME@@ shape is forgiven; a typo must fail loudly."""
    (tmp_path / ".env").write_text("OLLAMA_NUM_PARALLEL=tow\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError):
        Settings()


def test_an_env_key_from_another_version_does_not_block_startup(tmp_path, monkeypatch):
    """`.env` outlives the binary reading it. Under the extra="forbid" default
    a key from another version stops the app from starting."""
    (tmp_path / ".env").write_text(
        "A_SETTING_FROM_THE_FUTURE=2\nENRICHMENT_VISION_CONCURRENCY=2\n"
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.ENRICHMENT_VISION_CONCURRENCY == 2
