"""Comparing models from the app, and the refusals that keep the numbers honest.

A comparison owns the model selection for its whole duration and writes
generated content into the library, so what these tests hold is mostly what the
surface must NOT do: run two at once, measure a model it did not switch to,
spread a value into a child's argv that could be re-parsed as a flag, or leave
the user's model changed when it finishes.
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import model_lab


@pytest.fixture(autouse=True)
def _clean_lab():
    model_lab.reset_for_tests()
    yield
    model_lab.reset_for_tests()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# What can be compared


def test_the_catalogue_covers_the_whole_workflow():
    catalogue = model_lab.task_catalogue(
        "http://x", qa_datasets=["book", "legal"], max_questions=40
    )

    assert {"intent", "flashcards", "summary", "qa:book", "qa:legal"} <= set(catalogue)


def test_a_qa_stage_exists_per_dataset_rather_than_one_pooled_run():
    """Retrieval quality is a property of the kind of writing more than of the
    funnel, so pooling a contract with a novel hides which one a model is bad at."""
    catalogue = model_lab.task_catalogue(
        "http://x", qa_datasets=["book", "legal"], max_questions=None
    )

    assert catalogue["qa:book"].argv[catalogue["qa:book"].argv.index("--dataset") + 1] == "book"
    assert catalogue["qa:legal"].argv[catalogue["qa:legal"].argv.index("--dataset") + 1] == "legal"


def test_summaries_are_regenerated_not_replayed():
    """`POST /summarize/{id}` returns the stored summary unless asked to refresh,
    so without this the stage scores whichever model wrote it first."""
    catalogue = model_lab.task_catalogue("http://x", qa_datasets=[], max_questions=None)

    assert "--force-refresh" in catalogue["summary"].argv


def test_stages_that_write_to_the_library_say_so():
    """The confirmation the UI shows has to be specific, not a generic warning."""
    catalogue = model_lab.task_catalogue("http://x", qa_datasets=[], max_questions=None)

    assert catalogue["flashcards"].mutates_library is True
    assert catalogue["intent"].mutates_library is False


# Refusals


@pytest.mark.parametrize("bad", ["--out", "ollama/x y", "", "nonprovider/model", "-rf"])
def test_a_model_id_that_could_be_reparsed_as_a_flag_is_refused(bad):
    """A list-valued option spread after a runner's flag lets a value like
    `--out` be re-parsed by the child's argparse -- a file write primitive with
    no shell involved. See docs/patterns.md."""
    assert model_lab.validate_models([bad]) is not None


def test_a_valid_model_id_passes():
    assert model_lab.validate_models(["ollama/qwen3.5:4b", "openai/gpt-5.4"]) is None


def test_the_same_model_twice_is_refused():
    """Two identical columns are not a comparison."""
    assert model_lab.validate_models(["ollama/a", "ollama/a"]) is not None


def test_a_dataset_with_no_golden_is_refused():
    assert model_lab.validate_datasets(["definitely-not-a-dataset"]) is not None
    assert model_lab.validate_datasets(["book"]) is None


@pytest.mark.asyncio
async def test_a_second_run_is_refused_while_one_is_in_flight(client, monkeypatch):
    """A run owns the model selection for its duration; two would interleave
    switches and attribute one model's numbers to another."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def _hold(spec, backend_url):
        started.set()
        await release.wait()
        return model_lab.TaskResult(task=spec.key, status="complete", exit_code=0)

    monkeypatch.setattr(model_lab, "_run_task", _hold)
    monkeypatch.setattr(model_lab, "_switch_model", _fake_switch)
    monkeypatch.setattr(model_lab, "_environment", _fake_env)

    body = {"models": ["ollama/a"], "tasks": ["intent"]}
    first = await client.post("/model-lab/runs", json=body)
    assert first.status_code == 202

    await asyncio.wait_for(started.wait(), timeout=5)
    second = await client.post(
        "/model-lab/runs", json={"models": ["ollama/b"], "tasks": ["intent"]}
    )

    assert second.status_code == 409

    release.set()
    await _settle()


@pytest.mark.asyncio
async def test_an_unknown_task_is_refused(client):
    resp = await client.post(
        "/model-lab/runs", json={"models": ["ollama/a"], "tasks": ["not-a-stage"]}
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_an_injectable_model_is_refused_at_the_wire(client):
    resp = await client.post("/model-lab/runs", json={"models": ["--out"], "tasks": ["intent"]})

    assert resp.status_code == 422


# Running


async def _fake_switch(model: str) -> str:
    return model


async def _fake_env() -> dict:
    return {"chat_model": "stub"}


async def _settle(tries: int = 200) -> None:
    for _ in range(tries):
        if model_lab.current_run() is None:
            return
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_a_run_records_a_column_per_model_and_restores_the_original(client, monkeypatch):
    switched: list[str] = []

    async def _track(model: str) -> str:
        switched.append(model)
        return model

    async def _ok(spec, backend_url):
        return model_lab.TaskResult(
            task=spec.key,
            status="complete",
            exit_code=0,
            metrics={"routing_accuracy": 0.9 if "b" in switched[-1] else 0.5},
        )

    monkeypatch.setattr(model_lab, "_switch_model", _track)
    monkeypatch.setattr(model_lab, "_environment", _fake_env)
    monkeypatch.setattr(model_lab, "_run_task", _ok)
    resp = await client.post(
        "/model-lab/runs", json={"models": ["ollama/a", "ollama/b"], "tasks": ["intent"]}
    )
    run_id = resp.json()["id"]
    await _settle()

    detail = (await client.get(f"/model-lab/runs/{run_id}")).json()

    assert detail["status"] == "complete"
    assert [arm["model"] for arm in detail["arms"]] == ["ollama/a", "ollama/b"]
    # Two candidates plus the restore: the model the user chose is put back, and
    # the restore is the last switch rather than a candidate being left selected.
    assert switched[:2] == ["ollama/a", "ollama/b"]
    assert len(switched) == 3
    assert detail["restore_error"] is None


@pytest.mark.asyncio
async def test_a_failed_stage_contributes_no_metrics(client, monkeypatch):
    """A task that did not finish describes however much of the work it got
    through, and a truncated pass compared against a whole one reads as a
    difference between the models."""

    async def _fail(spec, backend_url):
        return model_lab.TaskResult(
            task=spec.key,
            status="failed",
            exit_code=1,
            metrics={"routing_accuracy": 0.1},
            error="timed out",
        )

    monkeypatch.setattr(model_lab, "_switch_model", _fake_switch)
    monkeypatch.setattr(model_lab, "_environment", _fake_env)
    monkeypatch.setattr(model_lab, "_run_task", _fail)

    resp = await client.post("/model-lab/runs", json={"models": ["ollama/a"], "tasks": ["intent"]})
    run_id = resp.json()["id"]
    await _settle()

    detail = (await client.get(f"/model-lab/runs/{run_id}")).json()
    arm = detail["arms"][0]

    assert arm["metrics"] == {}
    assert arm["failed_tasks"] == ["intent"]
    assert detail["rows"] == []


@pytest.mark.asyncio
async def test_metrics_are_tiered_so_a_judged_score_cannot_gate(client, monkeypatch):
    async def _mixed(spec, backend_url):
        return model_lab.TaskResult(
            task=spec.key,
            status="complete",
            exit_code=0,
            metrics={"routing_accuracy": 0.9, "faithfulness": 0.4, "hit_rate_5": 0.5},
        )

    monkeypatch.setattr(model_lab, "_switch_model", _fake_switch)
    monkeypatch.setattr(model_lab, "_environment", _fake_env)
    monkeypatch.setattr(model_lab, "_run_task", _mixed)

    resp = await client.post("/model-lab/runs", json={"models": ["ollama/a"], "tasks": ["intent"]})
    run_id = resp.json()["id"]
    await _settle()

    detail = (await client.get(f"/model-lab/runs/{run_id}")).json()
    rows = {r["metric"]: r["tier"] for r in detail["rows"]}

    assert rows["routing_accuracy"] == "structural"
    assert rows["faithfulness"] == "quality"
    assert rows["hit_rate_5"] == "excluded"


@pytest.mark.asyncio
async def test_a_metric_identical_on_every_model_is_flagged(client, monkeypatch):
    """Two models do not score the same to full precision on work that depends
    on them, so an identical metric measured something else."""

    async def _same(spec, backend_url):
        return model_lab.TaskResult(
            task=spec.key, status="complete", exit_code=0, metrics={"routing_accuracy": 0.75}
        )

    monkeypatch.setattr(model_lab, "_switch_model", _fake_switch)
    monkeypatch.setattr(model_lab, "_environment", _fake_env)
    monkeypatch.setattr(model_lab, "_run_task", _same)

    resp = await client.post(
        "/model-lab/runs", json={"models": ["ollama/a", "ollama/b"], "tasks": ["intent"]}
    )
    run_id = resp.json()["id"]
    await _settle()

    rows = (await client.get(f"/model-lab/runs/{run_id}")).json()["rows"]

    assert [r["identical"] for r in rows] == [True]


@pytest.mark.asyncio
async def test_an_unknown_run_id_is_a_404(client):
    assert (await client.get("/model-lab/runs/nope")).status_code == 404
    assert (await client.post("/model-lab/runs/nope/cancel")).status_code == 404


@pytest.mark.asyncio
async def test_the_catalogue_endpoint_reports_what_is_available(client):
    resp = await client.get("/model-lab/catalogue")

    assert resp.status_code == 200
    body = resp.json()
    assert {t["key"] for t in body["tasks"]} >= {"intent", "flashcards", "summary"}
    assert "book" in body["qa_datasets"]
    assert body["busy"] is False
