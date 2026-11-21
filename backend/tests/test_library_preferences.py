"""Each library is served under its own preferences; API keys stay the machine user's (#389).

Settings are the app's alone (#532), so the second library's are written by the app with
that library open, and a device paired into it is refused.
"""

import pytest

import app.services.background_prefs as background_prefs
import app.services.settings_service as settings_service
from app.database import get_session_factory
from app.library import DEFAULT_LIBRARY, use_library
from app.repos.settings_repo import SettingsRepo
from app.runtime.library_work import serve_library, stop_library
from app.services.settings_service import get_effective_routing
from tests.test_library_binding import OTHER, _app_in, _pair_into, client  # noqa: F401
from tests.test_route_scopes import LOCAL_ONLY


@pytest.fixture(autouse=True)
async def _restore_preferences():
    saved = (
        dict(settings_service._cache),
        set(settings_service._mode_chosen),
        dict(background_prefs._cache),
    )
    yield
    await stop_library(DEFAULT_LIBRARY)
    settings_service._cache.clear()
    settings_service._cache.update(saved[0])
    settings_service._mode_chosen.clear()
    settings_service._mode_chosen.update(saved[1])
    background_prefs._cache.clear()
    background_prefs._cache.update(saved[2])
    settings_service._library_caches.clear()
    background_prefs._library_caches.clear()


async def _restart() -> None:
    """Lose what a restart loses, the caches, then serve each library again."""
    settings_service._cache.clear()
    settings_service._cache.update(settings_service._DEFAULTS)
    settings_service._mode_chosen.clear()
    settings_service._library_caches.clear()
    background_prefs._cache.clear()
    background_prefs._library_caches.clear()
    for library in (DEFAULT_LIBRARY, OTHER):
        await stop_library(library)
        await serve_library(library)


async def _llm(client) -> tuple:  # noqa: F811
    body = (await client.get("/settings/llm")).json()
    return body["mode"], body["mode_chosen"], body["local_chat_model"], body["vision_model"]


async def _refused(client, device, path: str, body: dict) -> None:  # noqa: F811
    resp = await client.patch(path, json=body, headers=device)
    assert resp.status_code == 403 and resp.json()["detail"] == LOCAL_ONLY


async def test_each_library_is_served_under_its_own_preferences(client):  # noqa: F811
    device = await _pair_into(client, OTHER)
    own = {"mode": "hybrid", "local_chat_model": "qwen3.5:9b", "vision_model": "gemma3:4b"}
    assert (await client.patch("/settings/llm", json=own)).status_code == 200
    other = {"local_chat_model": "qwen3.5:0.8b"}
    quiet = {"quiet_background": False}
    await _refused(client, device, "/settings/llm", other)
    await _refused(client, device, "/settings/background", quiet)
    with _app_in(OTHER):
        assert (await client.patch("/settings/llm", json=other)).status_code == 200
        assert (await client.patch("/settings/background", json=quiet)).status_code == 200

    expected_own = ("hybrid", True, "ollama/qwen3.5:9b", "ollama/gemma3:4b")
    assert await _llm(client) == expected_own
    assert (await client.get("/settings/background")).json()["quiet_background"] is True
    with _app_in(OTHER):
        assert (await _llm(client))[:3] == ("private", False, "ollama/qwen3.5:0.8b")
        assert (await client.get("/settings/background")).json()["quiet_background"] is False
    assert get_effective_routing(background=True)[0] == "ollama/qwen3.5:9b"
    with use_library(OTHER):
        assert get_effective_routing(background=True)[0] == "ollama/qwen3.5:0.8b"

    # After a restart each library loads its own rows, not the first one loaded.
    await _restart()
    assert get_effective_routing(background=True)[0] == "ollama/qwen3.5:9b"
    with use_library(OTHER):
        assert get_effective_routing(background=True)[0] == "ollama/qwen3.5:0.8b"
        assert background_prefs.quiet_background() is False
    assert background_prefs.quiet_background() is True


async def test_a_key_saved_from_any_library_is_kept_in_the_default_one(client):  # noqa: F811
    device = await _pair_into(client, OTHER)
    await _refused(client, device, "/settings/llm", {"openai_api_key": "sk-device"})
    with _app_in(OTHER):
        resp = await client.patch("/settings/llm", json={"openai_api_key": "sk-phone"})
    assert resp.status_code == 200 and resp.json()["has_openai_key"] is True

    rows = {}
    for library in (DEFAULT_LIBRARY, OTHER):
        with use_library(library):
            async with get_session_factory()() as session:
                rows[library] = await SettingsRepo(session).find("openai_api_key")
    assert rows[OTHER] is None
    assert rows[DEFAULT_LIBRARY] is not None and "sk-phone" not in str(rows[DEFAULT_LIBRARY].value)

    await _restart()
    with use_library(OTHER):
        assert settings_service.resolve_provider_api_key("openai") == "sk-phone"
