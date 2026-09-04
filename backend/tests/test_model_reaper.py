"""An idle entity model gives its memory back; a busy one does not.

GLiNER is 1,417MB resident -- the largest single thing the backend holds, more
than the embedder and reranker together -- and 6.29s to reload. Both measured.
The trade only works because ingestion pays the reload and no interactive path
does, so the tests below pin the release, the threshold, and the scope.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import model_reaper


class _FakeExtractor:
    """Stands in for the real one: loading GLiNER in a unit test is 6s and 1.4GB."""

    def __init__(self, idle: float, loaded: bool = True) -> None:
        self._idle = idle
        self._loaded = loaded
        self.released = 0

    def idle_seconds(self) -> float:
        return self._idle if self._loaded else float("inf")

    def release(self) -> bool:
        if not self._loaded:
            return False
        self._loaded = False
        self.released += 1
        return True


@pytest.fixture
def patched(monkeypatch):
    def _install(extractor, threshold=180):
        monkeypatch.setattr(
            model_reaper.get_settings(), "NER_IDLE_RELEASE_SECONDS", threshold
        )
        import app.services.ner as ner

        monkeypatch.setattr(ner, "get_entity_extractor", lambda: extractor)
        return extractor

    return _install


async def test_an_idle_model_is_released(patched):
    ex = patched(_FakeExtractor(idle=600))

    await model_reaper.reap_idle_models(interval_seconds=0, iterations=1)

    assert ex.released == 1


async def test_a_recently_used_model_is_kept(patched):
    """The threshold exists so back-to-back ingestions do not reload between them."""
    ex = patched(_FakeExtractor(idle=10))

    await model_reaper.reap_idle_models(interval_seconds=0, iterations=3)

    assert ex.released == 0


async def test_an_unloaded_model_is_not_released_repeatedly(patched):
    ex = patched(_FakeExtractor(idle=0, loaded=False))

    await model_reaper.reap_idle_models(interval_seconds=0, iterations=3)

    assert ex.released == 0


async def test_zero_disables_it(patched):
    ex = patched(_FakeExtractor(idle=99999), threshold=0)

    await model_reaper.reap_idle_models(interval_seconds=0, iterations=5)

    assert ex.released == 0


async def test_a_failing_pass_does_not_kill_the_reaper(patched, monkeypatch):
    """A reaper that dies on one bad pass stops reaping silently.

    The symptom would be memory growth with nothing in the log, which is the
    hardest kind of regression to attribute.
    """
    ex = _FakeExtractor(idle=600)
    patched(ex)

    calls = {"n": 0}

    def _boom():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return ex

    import app.services.ner as ner

    monkeypatch.setattr(ner, "get_entity_extractor", _boom)

    await model_reaper.reap_idle_models(interval_seconds=0, iterations=2)

    assert ex.released == 1, "the second pass should still have run"


async def test_cancellation_stops_it(patched):
    patched(_FakeExtractor(idle=0))

    task = asyncio.create_task(model_reaper.reap_idle_models(interval_seconds=5))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


def test_only_the_entity_model_is_reaped():
    """The reranker is a tenth of the memory and sits on live retrieval.

    Reaping it would trade 303MB for a stall in front of a waiting user, which
    is the opposite of the trade this module exists to make.
    """
    source = (model_reaper.__file__ or "").replace(".pyc", ".py")
    text = open(source).read()

    body = text.split('"""', 2)[2]

    assert "get_entity_extractor" in text
    assert "reranker" not in body, "reaping the reranker is deliberate scope creep"
