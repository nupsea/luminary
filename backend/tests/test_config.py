from app.config import Settings, get_settings


def test_settings_defaults():
    settings = Settings()
    assert settings.LOG_LEVEL == "INFO"
    assert settings.LITELLM_DEFAULT_MODEL == "ollama/mistral"
    assert settings.PHOENIX_ENABLED is True


def test_get_settings_returns_singleton():
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
