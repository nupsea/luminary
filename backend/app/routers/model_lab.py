"""Compare models across the Luminary workflow, from the app.

`POST /model-lab/runs` starts a comparison and returns immediately; the run is
long (a stage can be twenty minutes per model) so everything else here is about
watching it and reading what it found.

Two things this surface refuses, both because the alternative is a number that
cannot be defended: a second run while one is in flight, since a run owns the
model selection for its duration; and any model id that could be re-parsed as a
flag by a child runner's argparse.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.services import model_lab
from app.services.eval_tiers import metric_name, tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/model-lab", tags=["model-lab"])

_BACKEND_URL = "http://localhost:7820"


class TaskInfo(BaseModel):
    key: str
    label: str
    description: str
    typical_seconds: int
    # True when running this stage writes generated content into the library.
    # Surfaced so the confirmation the UI shows is specific rather than generic.
    mutates_library: bool


class LabCatalogue(BaseModel):
    """What can be compared, and what a comparison will do to this machine."""

    tasks: list[TaskInfo]
    qa_datasets: list[str]
    installed_models: list[str]
    registry_models: list[str]
    current_model: str
    busy: bool
    running_id: str | None = None


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[str] = Field(min_length=1, max_length=6)
    tasks: list[str] = Field(min_length=1)
    qa_datasets: list[str] = []
    # 0 means every row in the golden.
    max_questions: int = Field(default=0, ge=0, le=500)


class TaskRunView(BaseModel):
    task: str
    status: str
    exit_code: int | None = None
    duration_s: float | None = None
    error: str | None = None
    # The runner's own WARNING lines, kept whether or not it failed: a stage that
    # skipped rows still reports, and the reason belongs beside the number.
    warnings: list[str] = []
    # Enough of the failure to diagnose it from the UI rather than from a
    # terminal someone would have to have been watching.
    stderr_tail: list[str] = []


class ArmView(BaseModel):
    model: str
    tasks: list[TaskRunView]
    metrics: dict[str, Any]
    failed_tasks: list[str]
    environment: dict[str, Any]


class MetricRow(BaseModel):
    """One metric across every arm, with the tier that decides whether it counts."""

    key: str
    metric: str
    tier: str
    values: dict[str, float | None]
    # True when every arm reported the identical value. Two models do not score
    # the same to full precision on work that depends on them, so this means the
    # metric measured something other than the model.
    identical: bool


class RunView(BaseModel):
    id: str
    status: str
    models: list[str]
    tasks: list[str]
    started_at: str
    finished_at: str | None = None
    total_units: int
    completed_units: int
    arms: list[ArmView]
    rows: list[MetricRow]
    separation: dict[str, Any] | None = None
    error: str | None = None
    restore_error: str | None = None


def _rows(run_dict: dict[str, Any]) -> list[MetricRow]:
    """Pivot arm metrics into one row per metric, tiered.

    Built here rather than in the client so the tier that decides whether a
    metric may gate a swap is the same one the CLI applies.
    """
    models = [arm["model"] for arm in run_dict["arms"]]
    keys: list[str] = []
    for arm in run_dict["arms"]:
        for key in arm["metrics"]:
            if key not in keys:
                keys.append(key)

    rows: list[MetricRow] = []
    for key in sorted(keys):
        values: dict[str, float | None] = {}
        for arm in run_dict["arms"]:
            raw = arm["metrics"].get(key)
            values[arm["model"]] = (
                float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
            )
        present = [v for v in values.values() if v is not None]
        rows.append(
            MetricRow(
                key=key,
                metric=metric_name(key),
                tier=tier(key),
                values=values,
                identical=(
                    len(present) > 1
                    and len(set(present)) == 1
                    and len(present) == len(models)
                ),
            )
        )
    return rows


def _view(run: model_lab.MatrixRun) -> RunView:
    data = model_lab.to_dict(run)
    return RunView(
        id=data["id"],
        status=data["status"],
        models=data["models"],
        tasks=data["tasks"],
        started_at=data["started_at"],
        finished_at=data["finished_at"],
        total_units=data["total_units"],
        completed_units=data["completed_units"],
        arms=[
            ArmView(
                model=arm["model"],
                tasks=[
                    TaskRunView(**{k: t[k] for k in TaskRunView.model_fields})
                    for t in arm["tasks"]
                ],
                metrics=arm["metrics"],
                failed_tasks=arm["failed_tasks"],
                environment=arm["environment"],
            )
            for arm in data["arms"]
        ],
        rows=_rows(data),
        separation=data["separation"],
        error=data["error"],
        restore_error=data["restore_error"],
    )


@router.get("/catalogue", response_model=LabCatalogue)
async def get_catalogue() -> LabCatalogue:
    """Every stage that can be compared, and every model available to compare."""
    from app.config import get_settings  # noqa: PLC0415
    from app.model_registry import REGISTRY  # noqa: PLC0415
    from app.routers.settings import _fetch_ollama_models  # noqa: PLC0415
    from app.services import settings_service  # noqa: PLC0415

    _, installed = await _fetch_ollama_models(get_settings().OLLAMA_URL)
    goldens = sorted(
        p.stem
        for p in (model_lab.EVALS_DIR / "golden").glob("*.jsonl")
        if not p.stem.endswith(".flagged")
    )
    catalogue = model_lab.task_catalogue(_BACKEND_URL, qa_datasets=[], max_questions=None)
    running = model_lab.current_run()
    return LabCatalogue(
        tasks=[
            TaskInfo(
                key=spec.key,
                label=spec.label,
                description=spec.description,
                typical_seconds=spec.typical_seconds,
                mutates_library=spec.mutates_library,
            )
            for spec in catalogue.values()
        ],
        qa_datasets=goldens,
        installed_models=sorted(installed),
        registry_models=sorted(REGISTRY),
        current_model=settings_service.get_local_chat_model(),
        busy=running is not None,
        running_id=running.id if running else None,
    )


@router.post("/runs", status_code=202, response_model=RunView)
async def start_run(req: StartRunRequest) -> RunView:
    """Start a comparison. 409 when one is already in flight."""
    if err := model_lab.validate_models(req.models):
        raise HTTPException(status_code=422, detail=err)
    if err := model_lab.validate_datasets(req.qa_datasets):
        raise HTTPException(status_code=422, detail=err)

    try:
        run = await model_lab.start(
            req.models,
            req.tasks,
            qa_datasets=req.qa_datasets,
            max_questions=req.max_questions or None,
            backend_url=_BACKEND_URL,
        )
    except model_lab.MatrixBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _view(run)


class RunSummaryView(BaseModel):
    """Enough to list a run without carrying its results.

    The full view repeats every metric for every arm, so a list of them grows
    with each comparison until the page is fetching a payload nobody reads.
    Expanding one asks for its detail.
    """

    id: str
    status: str
    models: list[str]
    tasks: list[str]
    started_at: str
    finished_at: str | None = None
    total_units: int
    completed_units: int
    # Per-stage status only -- no metrics -- so a run in flight still shows
    # which stage it is on.
    stage_status: dict[str, str]
    failed_tasks: list[str]
    separated: bool | None = None
    separating_count: int = 0
    unmeasured_tasks: list[str] = []
    error: str | None = None
    restore_error: str | None = None


def _summary(run: model_lab.MatrixRun) -> RunSummaryView:
    data = model_lab.to_dict(run)
    sep = data["separation"] or {}
    return RunSummaryView(
        id=data["id"],
        status=data["status"],
        models=data["models"],
        tasks=data["tasks"],
        started_at=data["started_at"],
        finished_at=data["finished_at"],
        total_units=data["total_units"],
        completed_units=data["completed_units"],
        stage_status={
            f"{arm['model']}::{t['task']}": t["status"]
            for arm in data["arms"]
            for t in arm["tasks"]
        },
        failed_tasks=[f"{arm['model']} {t}" for arm in data["arms"] for t in arm["failed_tasks"]],
        separated=sep.get("separated"),
        separating_count=len(sep.get("separating_metrics") or []),
        unmeasured_tasks=sep.get("unmeasured_tasks") or [],
        error=data["error"],
        restore_error=data["restore_error"],
    )


@router.get("/runs", response_model=list[RunSummaryView])
async def list_runs(limit: int = 20) -> list[RunSummaryView]:
    """Recent runs, newest first, without their results."""
    return [_summary(run) for run in model_lab.recent_runs(limit)]


@router.get("/runs/{run_id}", response_model=RunView)
async def get_run(run_id: str) -> RunView:
    run = model_lab.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No model-lab run {run_id}")
    return _view(run)


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str) -> dict[str, Any]:
    """Stop after the task currently in flight.

    A completed call is the finest granularity available: interrupting a runner
    mid-generation leaves its counters describing a partial pass, and a partial
    pass is not evidence.
    """
    run = model_lab.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No model-lab run {run_id}")
    return {"cancelling": model_lab.request_cancel(), "run_id": run_id}
