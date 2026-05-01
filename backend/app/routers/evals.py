"""Evals endpoints — RAGAS eval results and trigger.

Routes:
  GET  /evals/results   — latest result per dataset from scores_history.jsonl
  POST /evals/run       — trigger a background eval run; returns 202 immediately
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EvalRunModel, GoldenDatasetModel, GoldenQuestionModel
from app.services.dataset_generator_service import (
    count_questions,
    create_dataset,
    delete_dataset,
    latest_run_for_dataset,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evals", tags=["evals"])

# Repo root: 4 levels up from app/routers/evals.py
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCORES_HISTORY_PATH = REPO_ROOT / "evals" / "scores_history.jsonl"
_EVALS_DIR = REPO_ROOT / "evals"

# Strong references to background tasks — prevents GC before they complete.
_background_tasks: set[asyncio.Task] = set()

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class EvalResultItem(BaseModel):
    dataset: str
    run_at: str
    hit_rate_5: float | None
    mrr: float | None
    faithfulness: float | None
    context_precision: float | None
    context_recall: float | None
    answer_relevancy: float | None
    passed_thresholds: bool | None


class EvalRunRequest(BaseModel):
    dataset: str
    assert_thresholds: bool = False


class GoldenDatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    document_ids: list[str] = Field(min_length=1)
    size: str = "small"
    generator_model: str | None = None
    description: str | None = None


class GoldenDatasetListItem(BaseModel):
    id: str | None = None
    name: str
    description: str | None = None
    size: str | None = None
    generator_model: str | None = None
    source_document_ids: list[str] = []
    status: str
    generated_count: int
    target_count: int
    created_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    last_run: dict[str, Any] | None = None
    source: str = "db"


class GoldenDatasetStatusResponse(BaseModel):
    id: str
    status: str
    generated_count: int
    target_count: int
    error_message: str | None = None


class GoldenQuestionResponse(BaseModel):
    id: str
    question: str
    ground_truth_answer: str
    context_hint: str
    source_chunk_id: str
    source_document_id: str
    quality_score: float
    included: bool


class GoldenDatasetDetailResponse(GoldenDatasetListItem):
    questions: list[GoldenQuestionResponse]
    offset: int
    limit: int


class GeneratedRunRequest(BaseModel):
    model: str | None = None
    judge_model: str | None = None
    assert_thresholds: bool = False
    check_citations: bool = False
    max_questions: int | None = None


class GeneratedRunResponse(BaseModel):
    status: str
    run_id: str
    dataset_id: str


# ---------------------------------------------------------------------------
# Background task helper
# ---------------------------------------------------------------------------


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _run_eval_subprocess(dataset: str, assert_thresholds: bool) -> None:
    cmd = ["uv", "run", "python", "run_eval.py", "--dataset", dataset]
    if assert_thresholds:
        cmd.append("--assert-thresholds")
    logger.debug("starting eval subprocess: %s cwd=%s", cmd, _EVALS_DIR)
    result = await asyncio.to_thread(
        subprocess.run,
        cmd,
        cwd=str(_EVALS_DIR),
        capture_output=True,
    )
    logger.debug(
        "eval subprocess finished: returncode=%d stdout=%r stderr=%r",
        result.returncode,
        result.stdout[-500:] if result.stdout else b"",
        result.stderr[-500:] if result.stderr else b"",
    )


async def _run_generated_eval_subprocess(
    dataset_id: str,
    run_id: str,
    model: str | None,
    judge_model: str | None,
    assert_thresholds: bool,
    check_citations: bool,
    max_questions: int | None,
) -> None:
    cmd = ["uv", "run", "python", "run_eval.py", "--dataset-id", dataset_id]
    if model:
        cmd.extend(["--model", model])
    if judge_model is not None:
        cmd.extend(["--judge-model", judge_model])
    if assert_thresholds:
        cmd.append("--assert-thresholds")
    if check_citations:
        cmd.append("--check-citations")
    if max_questions is not None:
        cmd.extend(["--max-questions", str(max_questions)])
    logger.debug("starting generated eval subprocess: run_id=%s cmd=%s", run_id, cmd)
    await asyncio.to_thread(subprocess.run, cmd, cwd=str(_EVALS_DIR), capture_output=True)


def _dataset_to_item(
    dataset: GoldenDatasetModel,
    question_count: int,
    last_run: EvalRunModel | None,
) -> GoldenDatasetListItem:
    last_run_payload = None
    if last_run is not None:
        last_run_payload = {
            "run_at": last_run.run_at.isoformat(),
            "model_used": last_run.model_used,
            "hit_rate_5": last_run.hit_rate_5,
            "mrr": last_run.mrr,
            "faithfulness": last_run.faithfulness,
            "eval_kind": last_run.eval_kind,
        }
    return GoldenDatasetListItem(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        size=dataset.size,
        generator_model=dataset.generator_model,
        source_document_ids=list(dataset.source_document_ids or []),
        status=dataset.status,
        generated_count=question_count,
        target_count=dataset.target_count,
        created_at=dataset.created_at.isoformat() if dataset.created_at else None,
        completed_at=dataset.completed_at.isoformat() if dataset.completed_at else None,
        error_message=dataset.error_message,
        last_run=last_run_payload,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/datasets")
async def get_datasets(
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return generated datasets plus legacy JSONL golden datasets."""
    query = select(GoldenDatasetModel).order_by(GoldenDatasetModel.created_at.desc())
    if status:
        query = query.where(GoldenDatasetModel.status == status)
    result = await db.execute(query)
    datasets = list(result.scalars().all())

    items: list[dict[str, Any]] = []
    for dataset in datasets:
        question_count = await count_questions(db, dataset.id)
        last_run = await latest_run_for_dataset(db, dataset.id)
        items.append(_dataset_to_item(dataset, question_count, last_run).model_dump())

    golden_dir = _EVALS_DIR / "golden"
    if not golden_dir.exists():
        return items
    files = list(golden_dir.glob("*.jsonl"))
    if status is None:
        for f in sorted(files):
            items.append(
                GoldenDatasetListItem(
                    name=f.stem,
                    status="complete",
                    generated_count=0,
                    target_count=0,
                    source="file",
                ).model_dump()
            )
    return items


@router.post("/datasets", status_code=202)
async def create_golden_dataset(
    req: GoldenDatasetCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Create a generated golden dataset and start the background generation task."""
    if req.size not in {"small", "medium", "large"}:
        raise HTTPException(status_code=422, detail="size must be small, medium, or large")
    dataset = await create_dataset(
        db,
        name=req.name,
        description=req.description,
        document_ids=req.document_ids,
        size=req.size,
        generator_model=req.generator_model,
    )
    return {"id": dataset.id, "status": dataset.status}


@router.get("/datasets/{dataset_id}/status", response_model=GoldenDatasetStatusResponse)
async def get_golden_dataset_status(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
) -> GoldenDatasetStatusResponse:
    dataset = await db.get(GoldenDatasetModel, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return GoldenDatasetStatusResponse(
        id=dataset.id,
        status=dataset.status,
        generated_count=dataset.generated_count,
        target_count=dataset.target_count,
        error_message=dataset.error_message,
    )


@router.get("/datasets/{dataset_id}", response_model=GoldenDatasetDetailResponse)
async def get_golden_dataset(
    dataset_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> GoldenDatasetDetailResponse:
    dataset = await db.get(GoldenDatasetModel, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    result = await db.execute(
        select(GoldenQuestionModel)
        .where(GoldenQuestionModel.dataset_id == dataset_id)
        .order_by(GoldenQuestionModel.created_at)
        .offset(offset)
        .limit(limit)
    )
    questions = [
        GoldenQuestionResponse(
            id=q.id,
            question=q.question,
            ground_truth_answer=q.ground_truth_answer,
            context_hint=q.context_hint,
            source_chunk_id=q.source_chunk_id,
            source_document_id=q.source_document_id,
            quality_score=q.quality_score,
            included=q.included,
        )
        for q in result.scalars().all()
    ]
    question_count = await count_questions(db, dataset_id)
    last_run = await latest_run_for_dataset(db, dataset_id)
    item = _dataset_to_item(dataset, question_count, last_run)
    return GoldenDatasetDetailResponse(
        **item.model_dump(),
        questions=questions,
        offset=offset,
        limit=limit,
    )


@router.delete("/datasets/{dataset_id}", status_code=204)
async def remove_golden_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    deleted = await delete_dataset(db, dataset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Dataset not found")


@router.get("/datasets/{dataset_id}/golden")
async def get_golden_dataset_rows(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, str]]:
    dataset = await db.get(GoldenDatasetModel, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    result = await db.execute(
        select(GoldenQuestionModel)
        .where(
            GoldenQuestionModel.dataset_id == dataset_id,
            GoldenQuestionModel.included.is_(True),
        )
        .order_by(GoldenQuestionModel.created_at)
    )
    return [
        {
            "question": q.question,
            "ground_truth_answer": q.ground_truth_answer,
            "context_hint": q.context_hint,
            "source_file": "",
            "source_document_id": q.source_document_id,
            "source_chunk_id": q.source_chunk_id,
        }
        for q in result.scalars().all()
    ]


@router.post("/datasets/{dataset_id}/run", status_code=202, response_model=GeneratedRunResponse)
async def run_generated_dataset_eval(
    dataset_id: str,
    req: GeneratedRunRequest,
    db: AsyncSession = Depends(get_db),
) -> GeneratedRunResponse:
    dataset = await db.get(GoldenDatasetModel, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if dataset.status != "complete":
        raise HTTPException(status_code=409, detail="Dataset is not complete")
    run_id = f"generated-{dataset_id}-{len(_background_tasks) + 1}"
    _fire_and_forget(
        _run_generated_eval_subprocess(
            dataset_id,
            run_id,
            req.model,
            req.judge_model,
            req.assert_thresholds,
            req.check_citations,
            req.max_questions,
        )
    )
    return GeneratedRunResponse(status="started", run_id=run_id, dataset_id=dataset_id)


@router.get("/datasets/{dataset_id}/runs")
async def get_generated_dataset_runs(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    dataset = await db.get(GoldenDatasetModel, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    result = await db.execute(
        select(EvalRunModel)
        .where(EvalRunModel.dataset_name == dataset_id)
        .order_by(EvalRunModel.run_at.desc())
    )
    return [
        {
            "id": run.id,
            "run_at": run.run_at.isoformat(),
            "hit_rate_5": run.hit_rate_5,
            "mrr": run.mrr,
            "faithfulness": run.faithfulness,
            "answer_relevance": run.answer_relevance,
            "context_precision": run.context_precision,
            "context_recall": run.context_recall,
            "model_used": run.model_used,
            "eval_kind": run.eval_kind,
        }
        for run in result.scalars().all()
    ]


@router.get("/results", response_model=list[EvalResultItem])
async def get_eval_results() -> list[EvalResultItem]:
    """Return the most recent eval result per dataset.

    Reads REPO_ROOT/evals/scores_history.jsonl and groups by dataset,
    returning one row per dataset (the latest run_at).
    Returns [] if the file does not exist.
    """
    if not _SCORES_HISTORY_PATH.exists():
        return []

    latest: dict[str, dict] = {}
    try:
        with _SCORES_HISTORY_PATH.open() as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                dataset = row.get("dataset", "")
                if not dataset:
                    continue
                existing = latest.get(dataset)
                ts = row.get("timestamp", "")
                if existing is None or ts > existing.get("timestamp", ""):
                    latest[dataset] = row
    except OSError:
        logger.warning("could not read scores_history.jsonl at %s", _SCORES_HISTORY_PATH)
        return []

    results: list[EvalResultItem] = []
    for row in latest.values():
        results.append(
            EvalResultItem(
                dataset=row.get("dataset", ""),
                run_at=row.get("timestamp", ""),
                hit_rate_5=row.get("hr5"),
                mrr=row.get("mrr"),
                faithfulness=row.get("faithfulness"),
                context_precision=row.get("context_precision"),
                context_recall=row.get("context_recall"),
                answer_relevancy=row.get("answer_relevance"),
                passed_thresholds=row.get("passed"),
            )
        )
    return results


@router.post("/run", status_code=202)
async def run_eval(req: EvalRunRequest) -> dict:
    """Trigger a RAGAS eval run as a background task.

    Returns HTTP 202 immediately. The eval subprocess runs asynchronously
    via asyncio.to_thread so it never blocks the event loop.
    """
    golden_file = _EVALS_DIR / "golden" / f"{req.dataset}.jsonl"
    if not golden_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Dataset '{req.dataset}' not found (missing {golden_file.name})",
        )

    _fire_and_forget(_run_eval_subprocess(req.dataset, req.assert_thresholds))
    logger.info(
        "eval run started: dataset=%s assert_thresholds=%s", req.dataset, req.assert_thresholds
    )
    return {"status": "started", "dataset": req.dataset}
