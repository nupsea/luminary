"""GET/PATCH /settings/background, and the pace unattended model calls keep while quiet."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import background_prefs, chapter_backfill, llm_admission


@pytest.fixture(autouse=True)
def fresh_prefs(monkeypatch):
    monkeypatch.setattr(background_prefs, "_cache", {})


@pytest.fixture(autouse=True)
def no_runtime_scan(monkeypatch):
    # The gate's runtime check walks every process once per 15s per process; on Windows
    # that took a second and landed inside a timed call (1.03s against a 0.1s bound).
    async def unchanged() -> bool:
        return False

    monkeypatch.setattr(llm_admission, "trim_if_ballooned", unchanged)


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


@pytest.mark.parametrize("setup", ["attended", "awaited", "loud"])
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
    else:
        with llm_admission.unattended():
            waited = await two_calls()
    assert waited < 0.1


@pytest.mark.parametrize("width", [1, 2])
async def test_concurrent_unattended_callers_run_one_at_a_time_and_keep_the_pace(
    monkeypatch, width
):
    """Ingestion runs several unattended callers at once (summaries three wide, figures, web
    refs). A rest released every waiter together, so a two-slot runtime ran them in pairs and an
    ingest held the GPU at 99% with Quiet on; width 1 never showed it."""
    monkeypatch.setattr(llm_admission, "enrichment_concurrency", lambda: width)
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
    assert all(nxt[0] >= prev[1] for prev, nxt in zip(spans, spans[1:], strict=False))
    busy = sum(e - s for s, e in spans)
    assert busy / (spans[-1][1] - spans[0][0]) < 0.6


async def test_a_new_books_first_chapters_rest_but_go_first(monkeypatch):
    monkeypatch.setattr(llm_admission, "enrichment_concurrency", lambda: 2)
    monkeypatch.setattr(llm_admission, "_POLL_SECONDS", 0.005)
    order: list[str] = []

    async def call(name: str, seconds: float = 0.05) -> None:
        async with llm_admission.background_call():
            order.append(name)
            await asyncio.sleep(seconds)

    async def first_chapters() -> None:
        await asyncio.sleep(0.01)  # queues behind the summaries
        with llm_admission.ahead():
            await call("chapter")

    with llm_admission.unattended():
        started = asyncio.get_running_loop().time()
        await asyncio.gather(call("running", 0.1), call("summary"), first_chapters())
    assert order == ["running", "chapter", "summary"]
    # Two rests of a call's length each: the chapter is paced like the rest.
    assert asyncio.get_running_loop().time() - started >= 0.1 + 0.1 + 0.05 + 0.05
