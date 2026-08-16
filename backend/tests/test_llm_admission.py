"""Admission control: background LLM work yields to interactive work (P5).

The property under test is an ordering one, so every test drives it with explicit
events rather than sleeps -- a sleep only ever asserts that the gate did *not*
release early, which is the safe direction to be wrong in.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import app.config as config_module
from app.services import llm_admission
from app.services.llm import LLMService

LOCAL = "ollama/llama3.2"
CLOUD = "openai/gpt-5.4"


@pytest.fixture
def admission_settings(monkeypatch):
    """Override Settings for the admission gate only, without touching the env."""

    def _apply(**overrides):
        base = config_module.Settings()
        stub = base.model_copy(update=overrides)
        monkeypatch.setattr(config_module, "get_settings", lambda: stub)
        return stub

    return _apply


def _completion(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


def _chunk(content: str) -> MagicMock:
    delta = MagicMock()
    delta.content = content
    choice = MagicMock()
    choice.delta = delta
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


@pytest.mark.asyncio
async def test_background_waits_while_an_interactive_call_runs(admission_settings):
    admission_settings(OLLAMA_NUM_PARALLEL=1, LLM_ADMISSION_GRACE_SECONDS=0.0)
    order: list[str] = []
    interactive_started = asyncio.Event()
    release = asyncio.Event()

    async def interactive():
        async with llm_admission.interactive_call():
            order.append("interactive_start")
            interactive_started.set()
            await release.wait()
        order.append("interactive_end")

    async def background():
        await interactive_started.wait()
        async with llm_admission.background_call():
            order.append("background_start")

    tasks = [asyncio.create_task(interactive()), asyncio.create_task(background())]
    await interactive_started.wait()
    await asyncio.sleep(0.4)

    assert order == ["interactive_start"]
    assert llm_admission.paused_for_interaction() is True

    release.set()
    await asyncio.gather(*tasks)
    assert order == ["interactive_start", "interactive_end", "background_start"]
    assert llm_admission.paused_for_interaction() is False
    assert llm_admission.admission_stats()["deferred_calls"] == 1


@pytest.mark.asyncio
async def test_interactive_never_waits_for_background(admission_settings):
    admission_settings(OLLAMA_NUM_PARALLEL=1, LLM_ADMISSION_GRACE_SECONDS=0.0)
    release = asyncio.Event()
    admitted = asyncio.Event()

    async def background():
        async with llm_admission.background_call():
            admitted.set()
            await release.wait()

    task = asyncio.create_task(background())
    await admitted.wait()

    started = time.monotonic()
    async with llm_admission.interactive_call():
        pass
    assert time.monotonic() - started < 0.1

    release.set()
    await task


@pytest.mark.asyncio
async def test_grace_window_holds_the_gap_between_two_turns(admission_settings):
    admission_settings(OLLAMA_NUM_PARALLEL=1, LLM_ADMISSION_GRACE_SECONDS=0.5)

    async with llm_admission.interactive_call():
        pass
    turn_ended = time.monotonic()

    async with llm_admission.background_call():
        admitted_after = time.monotonic() - turn_ended

    assert admitted_after >= 0.4


@pytest.mark.asyncio
async def test_a_held_background_call_is_admitted_before_ingestion_stalls(
    admission_settings,
):
    admission_settings(
        OLLAMA_NUM_PARALLEL=1,
        LLM_ADMISSION_GRACE_SECONDS=0.0,
        LLM_ADMISSION_MAX_DEFER_SECONDS=0.5,
    )
    release = asyncio.Event()

    async def chatting():
        async with llm_admission.interactive_call():
            await release.wait()

    task = asyncio.create_task(chatting())
    await asyncio.sleep(0)

    started = time.monotonic()
    async with llm_admission.background_call():
        waited = time.monotonic() - started

    assert 0.4 <= waited < 3.0
    assert llm_admission.admission_stats()["forced_admissions"] == 1

    release.set()
    await task


@pytest.mark.asyncio
async def test_an_abandoned_interactive_call_does_not_hold_the_gate_for_ever(
    admission_settings, monkeypatch
):
    """A stream the client walked away from must not slow ingestion for the life of the process."""
    admission_settings(
        OLLAMA_NUM_PARALLEL=1,
        LLM_ADMISSION_GRACE_SECONDS=0.0,
        LLM_ADMISSION_MAX_DEFER_SECONDS=30.0,
    )
    monkeypatch.setattr(llm_admission, "_STALE_INTERACTIVE_SECONDS", 0.3)
    never = asyncio.Event()

    async def abandoned():
        async with llm_admission.interactive_call():
            await never.wait()

    task = asyncio.create_task(abandoned())
    await asyncio.sleep(0)

    started = time.monotonic()
    async with llm_admission.background_call():
        waited = time.monotonic() - started

    assert waited < 3.0
    assert llm_admission.admission_stats()["forced_admissions"] == 0

    task.cancel()


@pytest.mark.asyncio
async def test_reserve_comes_from_the_serving_width(admission_settings):
    admission_settings(OLLAMA_NUM_PARALLEL=2, LLM_ADMISSION_GRACE_SECONDS=0.0)
    assert llm_admission.background_reserve() == 1

    release = asyncio.Event()
    first_admitted = asyncio.Event()
    second_admitted = asyncio.Event()

    async def interactive():
        async with llm_admission.interactive_call():
            await release.wait()

    async def background(flag: asyncio.Event):
        async with llm_admission.background_call():
            flag.set()
            await release.wait()

    tasks = [
        asyncio.create_task(interactive()),
        asyncio.create_task(background(first_admitted)),
        asyncio.create_task(background(second_admitted)),
    ]
    await asyncio.wait_for(first_admitted.wait(), timeout=1.0)
    await asyncio.sleep(0.3)

    assert second_admitted.is_set() is False

    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_single_slot_suspends_background_outright(admission_settings):
    admission_settings(OLLAMA_NUM_PARALLEL=1)
    assert llm_admission.background_reserve() == 0


@pytest.mark.asyncio
async def test_a_cloud_call_is_not_gated(admission_settings):
    admission_settings(OLLAMA_NUM_PARALLEL=1, LLM_ADMISSION_GRACE_SECONDS=0.0)
    release = asyncio.Event()

    async def interactive():
        async with llm_admission.interactive_call():
            await release.wait()

    task = asyncio.create_task(interactive())
    await asyncio.sleep(0)

    started = time.monotonic()
    async with llm_admission.admit(CLOUD, background=True):
        pass
    assert time.monotonic() - started < 0.1

    release.set()
    await task


@pytest.mark.asyncio
async def test_disabled_gate_admits_immediately(admission_settings):
    admission_settings(
        OLLAMA_NUM_PARALLEL=1,
        LLM_ADMISSION_ENABLED=False,
        LLM_ADMISSION_GRACE_SECONDS=0.0,
    )
    release = asyncio.Event()

    async def interactive():
        async with llm_admission.interactive_call():
            await release.wait()

    task = asyncio.create_task(interactive())
    await asyncio.sleep(0)

    started = time.monotonic()
    async with llm_admission.background_call():
        pass
    assert time.monotonic() - started < 0.1

    release.set()
    await task


@pytest.mark.asyncio
async def test_llm_service_applies_the_gate_so_callers_do_not(admission_settings):
    """The gate lives inside LLMService: `background=True` is all a caller passes."""
    admission_settings(OLLAMA_NUM_PARALLEL=1, LLM_ADMISSION_GRACE_SECONDS=0.0)
    svc = LLMService()
    events: list[str] = []
    interactive_started = asyncio.Event()
    release = asyncio.Event()

    async def fake_acompletion(**kwargs):
        tag = kwargs["messages"][0]["content"]
        events.append(tag)
        if tag == "interactive":
            interactive_started.set()
            await release.wait()
        return _completion("ok")

    def _msg(tag: str) -> list[dict]:
        return [{"role": "user", "content": tag}]

    with patch("litellm.acompletion", side_effect=fake_acompletion):
        first = asyncio.create_task(svc.complete(_msg("interactive"), model=LOCAL))
        await interactive_started.wait()
        second = asyncio.create_task(
            svc.complete(_msg("background"), model=LOCAL, background=True)
        )
        await asyncio.sleep(0.4)

        assert events == ["interactive"]

        release.set()
        await asyncio.gather(first, second)

    assert events == ["interactive", "background"]


@pytest.mark.asyncio
async def test_a_stream_holds_the_gate_until_it_is_exhausted(admission_settings):
    """A stream is not finished when its first token lands -- the user is still being served."""
    admission_settings(OLLAMA_NUM_PARALLEL=1, LLM_ADMISSION_GRACE_SECONDS=0.0)
    svc = LLMService()
    events: list[str] = []
    first_token = asyncio.Event()
    release = asyncio.Event()

    async def stream_chunks():
        yield _chunk("one")
        await release.wait()
        yield _chunk("two")

    async def fake_acompletion(**kwargs):
        if kwargs.get("stream"):
            return stream_chunks()
        events.append("background")
        return _completion("ok")

    with patch("litellm.acompletion", side_effect=fake_acompletion):
        gen = await svc.stream_messages([{"role": "user", "content": "hi"}], model=LOCAL)

        async def consume():
            async for _ in gen:
                first_token.set()

        streaming = asyncio.create_task(consume())
        await first_token.wait()

        background = asyncio.create_task(
            svc.complete([{"role": "user", "content": "bg"}], model=LOCAL, background=True)
        )
        await asyncio.sleep(0.4)

        assert events == []

        release.set()
        await asyncio.gather(streaming, background)

    assert events == ["background"]


def test_admission_stats_outside_a_loop_is_empty():
    assert llm_admission.admission_stats() == {}
    assert llm_admission.paused_for_interaction() is False


@pytest.mark.asyncio
async def test_an_unreachable_provider_still_releases_the_gate(admission_settings):
    admission_settings(OLLAMA_NUM_PARALLEL=1, LLM_ADMISSION_GRACE_SECONDS=0.0)
    svc = LLMService()

    with (
        patch(
            "litellm.acompletion",
            new_callable=AsyncMock,
            side_effect=ConnectionRefusedError("down"),
        ),
        pytest.raises(ConnectionRefusedError),
    ):
        await svc.complete([{"role": "user", "content": "x"}], model=LOCAL, background=True)

    stats = llm_admission.admission_stats()
    assert stats["background_inflight"] == 0
    assert stats["interactive_inflight"] == 0


@pytest.mark.asyncio
async def test_status_endpoint_reports_the_pause_the_ui_shows(tmp_path, monkeypatch):
    """I-10: the pause has an explicit state, and it is the gate's own, not a guess."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.database as db_module
    from app.config import get_settings
    from app.database import make_engine
    from app.db_init import create_all_tables
    from app.main import app
    from app.models import DocumentModel

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory

    try:
        async with factory() as session:
            session.add(
                DocumentModel(
                    id="doc-1",
                    title="t",
                    format="txt",
                    content_type="book",
                    file_path="/tmp/t.txt",
                    stage="entity_extract",
                )
            )
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            body = (await client.get("/documents/doc-1/status")).json()
            assert body["paused_for_interaction"] is False

            release = asyncio.Event()
            held = asyncio.Event()

            async def interactive():
                async with llm_admission.interactive_call():
                    held.set()
                    await release.wait()

            async def background():
                await held.wait()
                async with llm_admission.background_call():
                    pass

            tasks = [asyncio.create_task(interactive()), asyncio.create_task(background())]
            await held.wait()
            await asyncio.sleep(0.3)

            body = (await client.get("/documents/doc-1/status")).json()
            assert body["paused_for_interaction"] is True

            release.set()
            await asyncio.gather(*tasks)

            body = (await client.get("/documents/doc-1/status")).json()
            assert body["paused_for_interaction"] is False
    finally:
        db_module._engine, db_module._session_factory = orig_engine, orig_factory
        get_settings.cache_clear()
        await engine.dispose()
