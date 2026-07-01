"""Evals endpoints — RAGAS eval results and trigger.

Routes:
  GET  /evals/results   — latest result per dataset from scores_history.jsonl
  POST /evals/run       — trigger a background eval run; returns 202 immediately
"""

import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import EvalRunModel, GoldenDatasetModel, GoldenQuestionModel
from app.services.dataset_generator_service import (
    count_questions,
    create_dataset,
    delete_dataset,
    latest_run_for_dataset,
)
from app.services.golden_quality import golden_dataset_quality

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evals", tags=["evals"])

# Repo root: 4 levels up from app/routers/evals.py
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCORES_HISTORY_PATH = REPO_ROOT / "evals" / "scores_history.jsonl"
_EVALS_DIR = REPO_ROOT / "evals"

# Strong references to background tasks — prevents GC before they complete.
_background_tasks: set[asyncio.Task] = set()

# In-flight + recently-completed eval run tracker.
# Key: dataset key (file-backed -> dataset name, db-backed -> dataset id).
# Survives across browser refreshes (process-local but persistent within
# backend lifetime). Failed/completed entries linger so the UI can surface
# their final status on the first page load after they finish.
import time as _time  # noqa: E402

_in_flight_runs: dict[str, dict[str, Any]] = {}
_RUN_RETENTION_SECONDS = 30 * 60  # keep terminal entries 30 min for UI pickup


def _record_run_start(
    key: str,
    *,
    run_id: str,
    judge_model: str | None,
    is_generated: bool,
) -> None:
    _in_flight_runs[key] = {
        "key": key,
        "run_id": run_id,
        "judge_model": judge_model,
        "is_generated": is_generated,
        "status": "running",
        "started_at": _time.time(),
        "finished_at": None,
        "error": None,
    }


def _record_run_finish(key: str, *, error: str | None) -> None:
    entry = _in_flight_runs.get(key)
    if entry is None:
        return
    entry["status"] = "failed" if error else "done"
    entry["finished_at"] = _time.time()
    entry["error"] = error


def _prune_in_flight() -> None:
    cutoff = _time.time() - _RUN_RETENTION_SECONDS
    stale = [
        k for k, v in _in_flight_runs.items()
        if v["status"] != "running" and (v.get("finished_at") or 0) < cutoff
    ]
    for k in stale:
        _in_flight_runs.pop(k, None)

# Luminary backend always runs on port 7820; eval subprocess needs this to call /search etc.
_BACKEND_URL = "http://localhost:7820"

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
    judge_model: str | None = None
    check_citations: bool = False
    max_questions: int | None = None
    rerank: bool = False
    ablation: bool = False


class EvalRunListItem(BaseModel):
    id: str
    dataset_name: str
    run_at: str
    hit_rate_5: float | None
    mrr: float | None
    faithfulness: float | None
    answer_relevance: float | None
    routing_accuracy: float | None
    per_route: dict | None
    ablation_metrics: dict | None
    eval_kind: str | None
    model_used: str
    citation_support_rate: float | None
    extra_metrics: dict | None = None


class GoldenFileQuestion(BaseModel):
    q: str
    a: str
    context_hint: str | None = None
    source_file: str | None = None


class GoldenFileResponse(BaseModel):
    name: str
    total: int
    questions: list[GoldenFileQuestion]
    offset: int
    limit: int


class GoldenDatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    document_ids: list[str] = Field(min_length=1)
    size: str = "small"
    generator_model: str | None = None
    description: str | None = None
    question_count: int | None = Field(default=None, ge=1, le=500)


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


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.exception("background eval task crashed", exc_info=exc)

    task.add_done_callback(_on_done)


async def _run_eval_subprocess(
    dataset: str,
    assert_thresholds: bool,
    judge_model: str | None = None,
    check_citations: bool = False,
    max_questions: int | None = None,
    rerank: bool = False,
    ablation: bool = False,
) -> None:
    cmd = [
        "uv", "run", "python", "run_eval.py",
        "--dataset", dataset,
        "--backend-url", _BACKEND_URL,
    ]
    if assert_thresholds:
        cmd.append("--assert-thresholds")
    if judge_model is not None:
        cmd.extend(["--judge-model", judge_model])
    if check_citations:
        cmd.append("--check-citations")
    if max_questions is not None:
        cmd.extend(["--max-questions", str(max_questions)])
    if rerank:
        cmd.append("--rerank")
    if ablation:
        cmd.append("--ablation")
    logger.info("eval subprocess starting: dataset=%s cmd=%s", dataset, cmd)
    error: str | None = None
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(_EVALS_DIR),
            capture_output=True,
        )
        stdout_tail = (result.stdout or b"")[-1000:].decode(errors="replace")
        stderr_tail = (result.stderr or b"")[-1000:].decode(errors="replace")
        if result.returncode != 0:
            logger.warning(
                "eval subprocess FAILED: dataset=%s returncode=%d\nSTDOUT:\n%s\nSTDERR:\n%s",
                dataset, result.returncode, stdout_tail, stderr_tail,
            )
            error = (stderr_tail.strip().splitlines() or ["eval subprocess failed"])[-1][:500]
        else:
            logger.info(
                "eval subprocess finished OK: dataset=%s\n%s", dataset, stdout_tail
            )
            if stderr_tail.strip():
                logger.warning(
                    "eval subprocess (rc=0) STDERR for dataset=%s:\n%s",
                    dataset, stderr_tail,
                )
    except Exception as exc:
        logger.exception("eval subprocess raised: dataset=%s", dataset)
        error = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        _record_run_finish(dataset, error=error)


async def _run_generated_eval_subprocess(
    dataset_id: str,
    run_id: str,
    model: str | None,
    judge_model: str | None,
    assert_thresholds: bool,
    check_citations: bool,
    max_questions: int | None,
) -> None:
    cmd = [
        "uv", "run", "python", "run_eval.py",
        "--dataset-id", dataset_id,
        "--backend-url", _BACKEND_URL,
    ]
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
    logger.info("eval subprocess starting: dataset_id=%s cmd=%s", dataset_id, cmd)
    error: str | None = None
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, cwd=str(_EVALS_DIR), capture_output=True
        )
        stdout_tail = (result.stdout or b"")[-1000:].decode(errors="replace")
        stderr_tail = (result.stderr or b"")[-1000:].decode(errors="replace")
        if result.returncode != 0:
            logger.warning(
                "eval subprocess FAILED: dataset_id=%s returncode=%d\nSTDOUT:\n%s\nSTDERR:\n%s",
                dataset_id, result.returncode, stdout_tail, stderr_tail,
            )
            error = (stderr_tail.strip().splitlines() or ["eval subprocess failed"])[-1][:500]
        else:
            logger.info(
                "eval subprocess finished OK: dataset_id=%s\n%s", dataset_id, stdout_tail
            )
    except Exception as exc:
        logger.exception("eval subprocess raised: dataset_id=%s", dataset_id)
        error = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        _record_run_finish(dataset_id, error=error)
        if stderr_tail.strip():
            logger.warning(
                "eval subprocess (rc=0) STDERR for dataset_id=%s:\n%s",
                dataset_id, stderr_tail,
            )


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


_GOLDEN_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _file_golden_question_count(path: Path) -> int | None:
    """Retrieval-evaluable question count for a golden file, or None when it is
    not a retrieval golden (missing question/context_hint/source_file) or empty.

    Used to hide non-evaluable files (flashcards/intents/summaries goldens,
    `.flagged` sidecars, empty files) from the dataset picker.
    """
    first: dict | None = None
    count = 0
    try:
        with path.open() as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if first is None:
                    first = row
                count += 1
    except OSError:
        return None
    if not first:
        return None
    if not (first.get("question") and first.get("context_hint") and first.get("source_file")):
        return None
    return count


@router.get("/runs", response_model=list[EvalRunListItem])
async def get_eval_runs(
    dataset_name: str | None = Query(default=None),
    eval_kind: str | None = Query(default=None),
    model: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[EvalRunListItem]:
    """Return paginated eval_runs ordered by run_at DESC with optional filters."""
    query = select(EvalRunModel).order_by(EvalRunModel.run_at.desc())
    if dataset_name is not None:
        query = query.where(EvalRunModel.dataset_name == dataset_name)
    if eval_kind is not None:
        query = query.where(EvalRunModel.eval_kind == eval_kind)
    if model is not None:
        query = query.where(EvalRunModel.model_used == model)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    runs = result.scalars().all()
    return [
        EvalRunListItem(
            id=r.id,
            dataset_name=r.dataset_name,
            run_at=r.run_at.isoformat(),
            hit_rate_5=r.hit_rate_5,
            mrr=r.mrr,
            faithfulness=r.faithfulness,
            answer_relevance=r.answer_relevance,
            routing_accuracy=r.routing_accuracy,
            per_route=r.per_route,
            ablation_metrics=r.ablation_metrics,
            eval_kind=r.eval_kind,
            model_used=r.model_used,
            citation_support_rate=r.citation_support_rate,
            extra_metrics=r.extra_metrics,
        )
        for r in runs
    ]


class GoldenInfoResponse(BaseModel):
    name: str
    question_count: int
    source_file: str | None = None
    provenance: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None


@router.get("/golden/{name}/info", response_model=GoldenInfoResponse)
async def get_golden_info(name: str) -> GoldenInfoResponse:
    """Provenance (how the golden was generated) + deterministic quality metrics.

    Quality is computed structurally (no LLM judge) so it is unbiased and
    reproducible — see golden_dataset_quality.
    """
    if not _GOLDEN_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")
    golden_dir = _EVALS_DIR / "golden"
    path = golden_dir / f"{name}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Dataset not found")

    rows: list[dict] = []
    try:
        with path.open() as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not read golden file") from exc

    provenance: dict | None = None
    meta_path = golden_dir / f"{name}.meta.json"
    if meta_path.exists():
        try:
            provenance = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            provenance = None

    quality: dict | None = None
    source_file = rows[0].get("source_file") if rows else None
    if source_file:
        src_path = REPO_ROOT / source_file
        if src_path.exists():
            try:
                quality = golden_dataset_quality(
                    rows, src_path.read_text(encoding="utf-8", errors="replace")
                )
            except OSError:
                quality = None

    return GoldenInfoResponse(
        name=name,
        question_count=len(rows),
        source_file=source_file,
        provenance=provenance,
        quality=quality,
    )


@router.get("/golden/{name}", response_model=GoldenFileResponse)
async def get_golden_file(
    name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> GoldenFileResponse:
    """Return paginated questions from a file-backed JSONL golden dataset."""
    if not _GOLDEN_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")
    golden_dir = _EVALS_DIR / "golden"
    allowed = {f.stem for f in golden_dir.glob("*.jsonl")} if golden_dir.exists() else set()
    if name not in allowed:
        raise HTTPException(status_code=404, detail="Dataset not found")
    golden_file = golden_dir / f"{name}.jsonl"
    rows: list[dict] = []
    try:
        with golden_file.open() as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not read golden file") from exc
    total = len(rows)
    page = rows[offset : offset + limit]
    def _str_hint(raw: object) -> str | None:
        if raw is None:
            return None
        if isinstance(raw, list):
            return " ".join(str(s) for s in raw)
        return str(raw)

    questions = [
        GoldenFileQuestion(
            q=row.get("q", row.get("question", "")),
            a=row.get("a", row.get("ground_truth_answer", "")),
            context_hint=_str_hint(row.get("context_hint") or row.get("hint")),
            source_file=row.get("source_file"),
        )
        for row in page
    ]
    return GoldenFileResponse(
        name=name, total=total, questions=questions, offset=offset, limit=limit
    )


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
    files = [f for f in golden_dir.glob("*.jsonl") if not f.name.endswith(".flagged.jsonl")]
    if status is None:
        for f in sorted(files):
            count = _file_golden_question_count(f)
            if count is None:
                continue  # not a retrieval golden / empty — don't surface as evaluable
            last_run = await latest_run_for_dataset(db, f.stem)
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
            items.append(
                GoldenDatasetListItem(
                    name=f.stem,
                    status="complete",
                    generated_count=count,
                    target_count=count,
                    source="file",
                    last_run=last_run_payload,
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
        question_count=req.question_count,
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
    _record_run_start(
        dataset_id,
        run_id=run_id,
        judge_model=req.judge_model,
        is_generated=True,
    )
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
    # Ablation is retrieval-only — it never calls a judge, so ignore any judge model.
    if req.ablation:
        req.judge_model = ""
    if req.judge_model:
        err = _validate_model_available(req.judge_model, get_settings())
        if err:
            raise HTTPException(status_code=422, detail=err)

    _record_run_start(
        req.dataset,
        run_id=f"file-{req.dataset}-{len(_background_tasks) + 1}",
        judge_model=req.judge_model,
        is_generated=False,
    )
    _fire_and_forget(
        _run_eval_subprocess(
            req.dataset,
            req.assert_thresholds,
            req.judge_model,
            req.check_citations,
            req.max_questions,
            req.rerank,
            req.ablation,
        )
    )
    logger.info(
        "eval run started: dataset=%s assert_thresholds=%s rerank=%s ablation=%s",
        req.dataset, req.assert_thresholds, req.rerank, req.ablation,
    )
    return {"status": "started", "dataset": req.dataset}


class GoldenGenerateRequest(BaseModel):
    name: str = Field(min_length=1)
    source_file: str
    generator_model: str = "openai/gpt-5.4"
    verify_models: list[str] = Field(
        default_factory=lambda: ["openai/gpt-5.1", "ollama/qwen2.5:14b-instruct"]
    )
    target: int = Field(default=50, ge=5, le=200)


async def _run_golden_generation_subprocess(req: GoldenGenerateRequest) -> None:
    out = _EVALS_DIR / "golden" / f"{req.name}.jsonl"
    cmd = [
        "uv", "run", "--project", str(REPO_ROOT / "backend"), "python",
        str(_EVALS_DIR / "generate_golden.py"),
        "--source", str(REPO_ROOT / req.source_file),
        "--out", str(out),
        "--generator-model", req.generator_model,
        "--target", str(req.target),
        "--source-file-label", req.source_file,
        "--verify-models", *req.verify_models,
    ]
    logger.info("golden generation starting: name=%s cmd=%s", req.name, cmd)
    error: str | None = None
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, cwd=str(REPO_ROOT), capture_output=True
        )
        if result.returncode != 0:
            tail = (result.stderr or b"")[-800:].decode(errors="replace")
            error = (tail.strip().splitlines() or ["golden generation failed"])[-1][:500]
            logger.warning("golden generation FAILED name=%s: %s", req.name, tail)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:500]
        logger.exception("golden generation raised: name=%s", req.name)
    finally:
        _record_run_finish(f"golden-{req.name}", error=error)


def _ollama_models(settings) -> tuple[set[str], str | None]:
    """Return (available ollama model ids, error). error is set when Ollama is unreachable."""
    try:
        resp = httpx.get(f"{settings.OLLAMA_URL}/api/tags", timeout=5.0)
        resp.raise_for_status()
        return {f"ollama/{m['name']}" for m in resp.json().get("models", [])}, None
    except Exception as exc:
        return set(), f"Ollama unreachable at {settings.OLLAMA_URL} ({type(exc).__name__})"


def _validate_model_available(model: str, settings) -> str | None:
    """Actionable error message if *model* can't be used, else None. '' means no model."""
    if not model:
        return None
    if model.startswith("ollama/"):
        names, err = _ollama_models(settings)
        if err:
            return f"{err} — cannot use {model}. Start Ollama or pick a frontier model."
        if model not in names:
            tag = model.split("/", 1)[1]
            return (
                f"Model {model} is not pulled in Ollama. Available: "
                f"{sorted(names) or 'none'}. Run `ollama pull {tag}` or pick another."
            )
        return None
    if model.startswith("openai/") and not settings.OPENAI_API_KEY:
        return f"{model} requires OPENAI_API_KEY in backend/.env."
    if model.startswith("anthropic/") and not getattr(settings, "ANTHROPIC_API_KEY", None):
        return f"{model} requires ANTHROPIC_API_KEY in backend/.env."
    return None


@router.get("/models")
async def get_eval_models() -> dict[str, list[str]]:
    """Models for the generate/run dropdowns: local Ollama + frontier (if keys set)."""
    settings = get_settings()
    local, _ = _ollama_models(settings)
    frontier: list[str] = []
    if settings.OPENAI_API_KEY:
        frontier += ["openai/gpt-5.4", "openai/gpt-4.1", "openai/gpt-4o-mini"]
    return {"local": sorted(local), "frontier": frontier}


@router.post("/golden/generate", status_code=202)
async def generate_golden_file(req: GoldenGenerateRequest) -> dict[str, str]:
    """Generate or REPLACE a file-backed golden with the good pipeline (personas +
    cross-model verification), chosen models, and a provenance sidecar."""
    if not _GOLDEN_NAME_RE.match(req.name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")
    src = (REPO_ROOT / req.source_file).resolve()
    if not str(src).startswith(str(REPO_ROOT.resolve())):
        raise HTTPException(status_code=400, detail="source_file must be within the repo")
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Source not found: {req.source_file}")
    settings = get_settings()
    for model in [req.generator_model, *req.verify_models]:
        err = _validate_model_available(model, settings)
        if err:
            raise HTTPException(status_code=422, detail=err)
    _record_run_start(
        f"golden-{req.name}",
        run_id=f"golden-{req.name}",
        judge_model=req.generator_model,
        is_generated=True,
    )
    _fire_and_forget(_run_golden_generation_subprocess(req))
    return {"status": "started", "name": req.name}


@router.get("/in-flight")
async def list_in_flight_runs() -> list[dict[str, Any]]:
    """Return currently-running and recently-finished eval runs.

    The frontend polls this on Quality-page mount so a browser refresh
    can re-attach to in-progress runs and surface failure toasts that
    were missed while the page was unmounted.
    """
    _prune_in_flight()
    return list(_in_flight_runs.values())
