import os

from app.config import Settings, get_settings


def test_settings_defaults():
    # PHOENIX_ENABLED is set to 'false' by conftest for test isolation;
    # temporarily unset it so we can verify the true default value.
    prev = os.environ.pop("PHOENIX_ENABLED", None)
    try:
        settings = Settings()
        assert settings.LOG_LEVEL == "INFO"
        assert settings.LITELLM_DEFAULT_MODEL == "ollama/mistral"
        assert settings.PHOENIX_ENABLED is True
    finally:
        if prev is not None:
            os.environ["PHOENIX_ENABLED"] = prev


def test_get_settings_returns_singleton():
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
