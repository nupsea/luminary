"""Concept-layer rebuild endpoints (the UI's "make concepts").

A single background job: POST /concepts/regenerate starts it, GET .../status polls it, and a
second POST while running is rejected. run_pipeline is mocked so the state machine is tested
without the real (heavy) clustering + LLM pipeline.
"""

import pytest
from fastapi import HTTPException

import app.routers.concepts as cr


@pytest.fixture(autouse=True)
def _reset_state():
    cr._regen_state.update(
        status="idle", started_at=None, finished_at=None, concepts=None, error=None
    )
    yield


async def test_regenerate_runs_and_reports_done(monkeypatch):
    async def fake_run_pipeline(*, dry_run):
        assert dry_run is False
        return {"diagnostics": {"persist_concepts": {"concepts": 7}}}

    monkeypatch.setattr("app.workflows.concept_pipeline.run_pipeline", fake_run_pipeline)

    started = await cr.regenerate_concepts()
    assert started.status == "running" and started.started_at is not None

    # a second start while one is in flight is rejected
    with pytest.raises(HTTPException) as ei:
        await cr.regenerate_concepts()
    assert ei.value.status_code == 409

    await cr._regen_task  # let the background job finish
    status = await cr.regenerate_concepts_status()
    assert status.status == "done" and status.concepts == 7 and status.finished_at is not None


async def test_regenerate_surfaces_errors(monkeypatch):
    async def boom(*, dry_run):
        raise RuntimeError("ollama down")

    monkeypatch.setattr("app.workflows.concept_pipeline.run_pipeline", boom)

    await cr.regenerate_concepts()
    await cr._regen_task
    status = await cr.regenerate_concepts_status()
    assert status.status == "error" and "ollama down" in (status.error or "")


async def test_status_idle_before_any_run():
    status = await cr.regenerate_concepts_status()
    assert status.status == "idle" and status.concepts is None
