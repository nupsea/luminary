import os

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
        assert settings.PHOENIX_ENABLED is True
    finally:
        for var, val in saved_vars.items():
            os.environ[var] = val


def test_get_settings_returns_singleton():
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
