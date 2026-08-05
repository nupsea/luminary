"""The environment block that ships with a bug report (nupsea/luminary#41).

Issues arrived with a version and an OS name, which was never enough to
reproduce anything, so answering one always cost a round trip.
"""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import diagnostics


@pytest.fixture
def no_ollama(monkeypatch):
    async def _unreachable():
        return ["ollama    not reachable"]

    monkeypatch.setattr(diagnostics, "_ollama", _unreachable)


async def test_the_block_carries_what_reproducing_needs(no_ollama):
    text = await diagnostics.environment_report()
    for field in ("version", "os", "kernel", "python", "chat", "vision", "ollama"):
        assert f"{field} " in text, f"missing {field!r} in:\n{text}"


async def test_the_account_name_never_reaches_the_tracker(no_ollama):
    """This block is pasted into a public issue."""
    text = await diagnostics.environment_report()
    home = str(Path.home())
    user = Path.home().name

    assert home not in text
    if len(user) >= 3:
        assert user not in text, f"leaked the account name:\n{text}"


def test_home_paths_are_replaced_rather_than_dropped():
    """The shape of the path is still useful; the name in it is not."""
    home = str(Path.home())
    scrubbed = diagnostics._scrub(f"library   {home}/.luminary")
    assert scrubbed == "library   ~/.luminary"


async def test_installed_models_are_listed(monkeypatch):
    async def _with_models():
        return [
            "ollama    running — 0.32.5",
            "          llama3.2:latest",
            "          qwen2.5vl:7b",
        ]

    monkeypatch.setattr(diagnostics, "_ollama", _with_models)
    text = await diagnostics.environment_report()
    assert "llama3.2:latest" in text
    assert "qwen2.5vl:7b" in text


async def test_an_unreachable_ollama_is_stated_not_omitted(no_ollama):
    """Silence would read as "no models", which is a different bug."""
    assert "not reachable" in await diagnostics.environment_report()


async def test_endpoint_returns_the_block(no_ollama):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/setup/report")

    assert resp.status_code == 200
    assert "version " in resp.json()["environment"]
