"""GET/PATCH /settings/background, and the pace unattended model calls keep while quiet."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import background_prefs, chapter_backfill, llm_admission


@pytest.fixture(autouse=True)
def fresh_prefs(monkeypatch):
    monkeypatch.setattr(background_prefs, "_cache", {})


async def test_both_default_on(memory_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/settings/background")
    assert resp.status_code == 200
    assert resp.json() == {"chapter_backfill": True, "quiet_background": True}


async def test_a_change_is_stored_and_survives_a_restart(memory_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/settings/background", json={"chapter_backfill": False})
    assert resp.json() == {"chapter_backfill": False, "quiet_background": True}

    background_prefs._cache.clear()
    async with memory_db.factory() as session:
        await background_prefs.load_background_prefs(session)
    assert background_prefs.chapter_backfill() is False
    assert background_prefs.quiet_background() is True


async def test_the_backfill_waits_while_switched_off(memory_db):
    async with memory_db.factory() as session:
        await background_prefs.set_background_prefs(session, chapter_backfill=False)
    pick = chapter_backfill.Pick("d", "t", None, ahead=True)  # type: ignore[arg-type]
    assert await chapter_backfill.not_now(pick) == "turned off in Settings"


async def _one_call(seconds: float) -> None:
    async with llm_admission.background_call():
        await asyncio.sleep(seconds)


async def test_an_unattended_call_rests_as_long_as_the_last_one_ran():
    loop = asyncio.get_running_loop()
    with llm_admission.unattended():
        await _one_call(0.2)
        started = loop.time()
        await _one_call(0)
    assert loop.time() - started >= 0.18


@pytest.mark.parametrize(
    "setup",
    ["attended", "awaited", "first chapters", "loud"],
)
async def test_work_someone_waits_on_or_a_loud_setting_never_rests(setup, memory_db):
    if setup == "loud":
        async with memory_db.factory() as session:
            await background_prefs.set_background_prefs(session, quiet_background=False)
    loop = asyncio.get_running_loop()

    async def two_calls():
        await _one_call(0.2)
        started = loop.time()
        await _one_call(0)
        return loop.time() - started

    if setup == "attended":
        waited = await two_calls()
    elif setup == "awaited":
        with llm_admission.unattended(), llm_admission.awaited():
            waited = await two_calls()
    elif setup == "first chapters":
        # chapter_cards_handler runs inside the worker's unattended context.
        with llm_admission.unattended(), llm_admission.unattended(False):
            waited = await two_calls()
    else:
        with llm_admission.unattended():
            waited = await two_calls()
    assert waited < 0.1


async def test_concurrent_unattended_callers_keep_the_pace(monkeypatch):
    """Ingestion runs several unattended callers at once (summaries three wide, figures,
    diagrams). Checking the rest only before queueing let a queued caller walk past a rest
    earned while it waited: three callers kept the runtime 76% busy, and a real ingest 100%."""
    monkeypatch.setattr(llm_admission, "enrichment_concurrency", lambda: 1)
    # The queue polls every 0.2 s; left alone, its gaps between 0.1 s calls pass for rest.
    monkeypatch.setattr(llm_admission, "_POLL_SECONDS", 0.005)
    spans: list[tuple[float, float]] = []

    async def worker() -> None:
        for _ in range(4):
            async with llm_admission.background_call():
                t = asyncio.get_running_loop().time()
                await asyncio.sleep(0.1)
                spans.append((t, asyncio.get_running_loop().time()))

    with llm_admission.unattended():
        await asyncio.gather(*(worker() for _ in range(3)))
    spans.sort()
    busy = sum(e - s for s, e in spans)  # one slot, so calls never overlap
    assert busy / (spans[-1][1] - spans[0][0]) < 0.6
