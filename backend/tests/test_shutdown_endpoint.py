"""Who may stop this process, and what happens when they do.

The API is unauthenticated on localhost and CSRF is deliberately open, so any
page in any tab can POST here. A shutdown with no secret would be a button for
closing someone else's app, which is why the refusals are most of this file.

Nothing here delivers a real signal: `_raise_term` is replaced in every test that
reaches it. A test that actually raised SIGTERM would take the suite with it.
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.exceptions import Forbidden
from app.services import lifecycle

TOKEN = "a-token-only-the-shell-knows"
HEADER = "X-Luminary-Shutdown-Token"


@pytest.fixture
def fired(monkeypatch):
    """Hold the signal, and record that it was reached."""
    calls: list[int] = []
    monkeypatch.setattr(lifecycle, "_raise_term", lambda: calls.append(1))
    # The real delay is left in place: that the response lands first is the
    # property it exists for, and shortening it makes the ordering unobservable.
    return calls


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("LUMINARY_SHUTDOWN_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _post(token: str | None):
    from app.main import app

    headers = {HEADER: token} if token is not None else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/setup/shutdown", headers=headers)


async def test_the_shell_can_stop_the_backend_it_spawned(configured, fired):
    resp = await _post(TOKEN)

    assert resp.status_code == 202
    assert resp.json() == {"status": "shutting_down"}
    # Scheduled, not awaited: the whole request completed and nothing has fired.
    assert fired == []

    for _ in range(40):
        if fired:
            break
        await asyncio.sleep(0.05)
    assert fired == [1]


async def test_a_page_in_another_tab_cannot(configured, fired):
    resp = await _post("guessed")

    assert resp.status_code == 403
    assert fired == []


async def test_a_request_with_no_token_at_all_is_refused(configured, fired):
    resp = await _post(None)

    assert resp.status_code == 403
    assert fired == []


async def test_an_install_with_no_token_refuses_everyone(monkeypatch, fired):
    """`make dev` and every source install configure nothing, so nothing works.

    The endpoint is inert unless a supervisor put a secret in the environment.
    """
    monkeypatch.delenv("LUMINARY_SHUTDOWN_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        for token in (None, "", "anything"):
            resp = await _post(token)
            assert resp.status_code == 403, token
        assert fired == []
    finally:
        get_settings.cache_clear()


def test_an_empty_token_never_matches_an_empty_config(monkeypatch):
    """The refusal both ways is one branch, and it is the one worth firing.

    `compare_digest("", "")` is true, so a configured-empty token would accept a
    header the caller did not have to know -- which is every caller.
    """
    monkeypatch.setenv("LUMINARY_SHUTDOWN_TOKEN", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(Forbidden):
            lifecycle.request_shutdown("")
    finally:
        get_settings.cache_clear()


def test_the_refusal_does_not_say_which_half_was_wrong(monkeypatch):
    """A different message for "no secret here" tells a caller where to spend time."""
    monkeypatch.setenv("LUMINARY_SHUTDOWN_TOKEN", TOKEN)
    get_settings.cache_clear()
    try:
        with pytest.raises(Forbidden) as wrong:
            lifecycle.request_shutdown("guessed")
        monkeypatch.delenv("LUMINARY_SHUTDOWN_TOKEN")
        get_settings.cache_clear()
        with pytest.raises(Forbidden) as unconfigured:
            lifecycle.request_shutdown("guessed")
    finally:
        get_settings.cache_clear()

    assert str(wrong.value) == str(unconfigured.value)
