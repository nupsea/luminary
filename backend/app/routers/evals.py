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
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db, get_session_factory
from app.models import DocumentModel, EvalRunModel, GoldenDatasetModel, GoldenQuestionModel
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


def _utc_iso(dt: datetime | None) -> str | None:
    """Serialize a stored datetime as UTC-aware ISO. aiosqlite returns tz-naive
    datetimes even when stored tz-aware; bare isoformat() makes browsers parse
    UTC wall-clock as local time, shifting every timestamp by the UTC offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


async def _persist_failed_run(
    dataset_name: str, *, model_used: str, eval_kind: str, error: str
) -> None:
    """Record a failed eval as an eval_runs row. The in-flight tracker is
    process-local and prunes after 30 min (and dies on --reload), so without
    this a failed run leaves no trace anywhere in the UI."""
    try:
        async with get_session_factory()() as session:
            session.add(
                EvalRunModel(
                    id=str(uuid.uuid4()),
                    dataset_name=dataset_name,
                    run_at=datetime.now(UTC),
                    model_used=model_used,
                    eval_kind=eval_kind,
                    status="failed",
                    error_message=error[:500],
                )
            )
            await session.commit()
    except Exception:
        logger.exception("could not persist failed eval run for %s", dataset_name)

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
    # Answering model override for /qa. None/"" = the app's default QA pipeline
    # (the shipped path); generation metrics always score real generated answers.
    model: str | None = None
    judge_model: str | None = None
    check_citations: bool = False
    max_questions: int | None = None
    rerank: bool = False
    ablation: bool = False


class EvalRunListItem(BaseModel):
    id: str
    dataset_name: str
    # Human-readable name: generated-dataset runs store the dataset ID in
    # dataset_name (it is the eval key); the label resolves it for display.
    dataset_label: str | None = None
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
    status: str = "complete"
    error_message: str | None = None


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
    # Source documents the questions pin (via source_document_id) that no
    # longer exist in the library. Retrieval scoped to them returns nothing,
    # so runs must be blocked/repaired rather than silently scoring 0%.
    missing_document_ids: list[str] = []
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
    rerank: bool = False
    ablation: bool = False


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
    model: str | None = None,
) -> None:
    cmd = [
        "uv", "run", "python", "run_eval.py",
        "--dataset", dataset,
        "--backend-url", _BACKEND_URL,
    ]
    if assert_thresholds:
        cmd.append("--assert-thresholds")
    if model:
        cmd.extend(["--model", model])
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
        if error:
            await _persist_failed_run(
                dataset,
                model_used=judge_model or "no-llm",
                eval_kind="ablation" if ablation else "generation" if judge_model else "retrieval",
                error=error,
            )


async def _run_generated_eval_subprocess(
    dataset_id: str,
    run_id: str,
    model: str | None,
    judge_model: str | None,
    assert_thresholds: bool,
    check_citations: bool,
    max_questions: int | None,
    rerank: bool = False,
    ablation: bool = False,
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
    if rerank:
        cmd.append("--rerank")
    if ablation:
        cmd.append("--ablation")
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
            if stderr_tail.strip():
                logger.warning(
                    "eval subprocess (rc=0) STDERR for dataset_id=%s:\n%s",
                    dataset_id, stderr_tail,
                )
    except Exception as exc:
        logger.exception("eval subprocess raised: dataset_id=%s", dataset_id)
        error = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        _record_run_finish(dataset_id, error=error)
        if error:
            await _persist_failed_run(
                dataset_id,
                model_used=model or judge_model or "no-llm",
                eval_kind=(
                    "ablation"
                    if ablation
                    else "generation"
                    if (model or judge_model)
                    else "retrieval"
                ),
                error=error,
            )


def _last_run_payload(run: EvalRunModel | None) -> dict[str, Any] | None:
    """Serialize a run for dataset lists. Ablation runs carry their scores in
    ablation_metrics only; surface the shipped arm (rrf+rerank, else rrf) so
    the freshest measurement isn't rendered as a dash."""
    if run is None:
        return None
    hit_rate_5 = run.hit_rate_5
    mrr = run.mrr
    if run.eval_kind == "ablation" and isinstance(run.ablation_metrics, dict):
        shipped = run.ablation_metrics.get("rrf+rerank") or run.ablation_metrics.get("rrf")
        if isinstance(shipped, dict):
            hit_rate_5 = hit_rate_5 if hit_rate_5 is not None else shipped.get("hit_rate_5")
            mrr = mrr if mrr is not None else shipped.get("mrr")
    # Faithfulness only counts when the run judged real generated answers
    # (answer_model provenance) — legacy runs self-graded the golden answers.
    faithfulness = run.faithfulness
    extra = run.extra_metrics if isinstance(run.extra_metrics, dict) else {}
    if faithfulness is not None and not isinstance(extra.get("answer_model"), str):
        faithfulness = None
    return {
        "run_at": _utc_iso(run.run_at),
        "model_used": run.model_used,
        "hit_rate_5": hit_rate_5,
        "mrr": mrr,
        "faithfulness": faithfulness,
        "eval_kind": run.eval_kind,
    }


async def _question_document_ids(db: AsyncSession, dataset_id: str) -> set[str]:
    """Distinct source_document_id over a dataset's included questions — the
    ids /search is actually scoped to at eval time."""
    result = await db.execute(
        select(GoldenQuestionModel.source_document_id)
        .where(
            GoldenQuestionModel.dataset_id == dataset_id,
            GoldenQuestionModel.included.is_(True),
        )
        .distinct()
    )
    return {row[0] for row in result.fetchall() if row[0]}


async def _missing_document_ids(db: AsyncSession, doc_ids: set[str]) -> set[str]:
    if not doc_ids:
        return set()
    result = await db.execute(select(DocumentModel.id).where(DocumentModel.id.in_(doc_ids)))
    alive = {row[0] for row in result.fetchall()}
    return doc_ids - alive


async def _dataset_missing_document_ids(db: AsyncSession, dataset_id: str) -> set[str]:
    # Single LEFT JOIN instead of two round-trips — this runs per dataset on
    # the list endpoint, which the UI polls while a generation is in flight.
    result = await db.execute(
        select(GoldenQuestionModel.source_document_id)
        .outerjoin(DocumentModel, DocumentModel.id == GoldenQuestionModel.source_document_id)
        .where(
            GoldenQuestionModel.dataset_id == dataset_id,
            GoldenQuestionModel.included.is_(True),
            DocumentModel.id.is_(None),
        )
        .distinct()
    )
    return {row[0] for row in result.fetchall() if row[0]}


def _dataset_to_item(
    dataset: GoldenDatasetModel,
    question_count: int,
    last_run: EvalRunModel | None,
    missing_document_ids: set[str] | None = None,
) -> GoldenDatasetListItem:
    return GoldenDatasetListItem(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        size=dataset.size,
        generator_model=dataset.generator_model,
        source_document_ids=list(dataset.source_document_ids or []),
        missing_document_ids=sorted(missing_document_ids or set()),
        status=dataset.status,
        generated_count=question_count,
        target_count=dataset.target_count,
        created_at=_utc_iso(dataset.created_at),
        completed_at=_utc_iso(dataset.completed_at),
        error_message=dataset.error_message,
        last_run=_last_run_payload(last_run),
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
    id_to_name: dict[str, str] = {}
    if runs:
        id_names_result = await db.execute(
            select(GoldenDatasetModel.id, GoldenDatasetModel.name).where(
                GoldenDatasetModel.id.in_({r.dataset_name for r in runs})
            )
        )
        id_to_name = {row[0]: row[1] for row in id_names_result.fetchall()}
    return [
        EvalRunListItem(
            id=r.id,
            dataset_name=r.dataset_name,
            dataset_label=id_to_name.get(r.dataset_name, r.dataset_name),
            run_at=_utc_iso(r.run_at) or "",
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
            status=getattr(r, "status", None) or "complete",
            error_message=r.error_message,
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
        missing = await _dataset_missing_document_ids(db, dataset.id)
        items.append(_dataset_to_item(dataset, question_count, last_run, missing).model_dump())

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
            items.append(
                GoldenDatasetListItem(
                    name=f.stem,
                    status="complete",
                    generated_count=count,
                    target_count=count,
                    source="file",
                    last_run=_last_run_payload(last_run),
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
    missing = await _dataset_missing_document_ids(db, dataset_id)
    item = _dataset_to_item(dataset, question_count, last_run, missing)
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


class DatasetRelinkRequest(BaseModel):
    document_id: str
    # Required when the dataset spans multiple source documents: only
    # questions pinned to this id are retargeted.
    from_document_id: str | None = None


@router.patch("/datasets/{dataset_id}/relink")
async def relink_golden_dataset(
    dataset_id: str,
    req: DatasetRelinkRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Repoint a dataset's questions at a live document.

    Generated goldens pin source_document_id per question; when that document
    is deleted and re-ingested it gets a new id, and every eval run scores an
    honest-looking 0% because scoped retrieval finds nothing. Re-linking
    updates the pins in place. The stale source_chunk_id is cleared — it
    pointed into the dead document and nothing at eval time depends on it.
    """
    dataset = await db.get(GoldenDatasetModel, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    target = await db.get(DocumentModel, req.document_id)
    if target is None:
        raise HTTPException(status_code=422, detail="Target document does not exist")

    question_docs = await _question_document_ids(db, dataset_id)
    if not question_docs:
        raise HTTPException(status_code=409, detail="Dataset has no included questions")
    if req.from_document_id is not None:
        if req.from_document_id not in question_docs:
            raise HTTPException(
                status_code=422,
                detail="from_document_id does not match any question in this dataset",
            )
        old_ids = {req.from_document_id}
    elif len(question_docs) == 1:
        old_ids = question_docs
    else:
        raise HTTPException(
            status_code=422,
            detail=(
                "Dataset spans multiple source documents "
                f"({', '.join(sorted(question_docs))}); pass from_document_id."
            ),
        )

    result = await db.execute(
        update(GoldenQuestionModel)
        .where(
            GoldenQuestionModel.dataset_id == dataset_id,
            GoldenQuestionModel.source_document_id.in_(old_ids),
        )
        .values(source_document_id=req.document_id, source_chunk_id="")
    )
    new_source_ids = [
        d for d in (dataset.source_document_ids or []) if d not in old_ids
    ]
    if req.document_id not in new_source_ids:
        new_source_ids.append(req.document_id)
    dataset.source_document_ids = new_source_ids
    await db.commit()
    logger.info(
        "relinked dataset %s: %s -> %s (%d questions)",
        dataset_id,
        sorted(old_ids),
        req.document_id,
        result.rowcount,
    )
    missing = await _dataset_missing_document_ids(db, dataset_id)
    return {
        "dataset_id": dataset_id,
        "document_id": req.document_id,
        "relinked_questions": result.rowcount,
        "missing_document_ids": sorted(missing),
    }


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
    # Refuse to measure a dataset whose questions all point at deleted
    # documents: retrieval scoped to a dead id returns nothing, so the run
    # would record an all-zero score that looks like a retrieval regression.
    question_docs = await _question_document_ids(db, dataset_id)
    missing = await _missing_document_ids(db, question_docs)
    if question_docs and missing == question_docs:
        raise HTTPException(
            status_code=409,
            detail=(
                "All source documents for this dataset were deleted from the library "
                f"({', '.join(sorted(missing))}). Re-link the dataset to the re-ingested "
                "document (Re-link on the dataset row), or regenerate it."
            ),
        )
    settings = get_settings()
    for candidate in (req.model, req.judge_model):
        if candidate:
            err = _validate_model_available(candidate, settings)
            if err:
                raise HTTPException(status_code=422, detail=err)
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
            rerank=req.rerank,
            ablation=req.ablation,
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
            "run_at": _utc_iso(run.run_at),
            "hit_rate_5": run.hit_rate_5,
            "mrr": run.mrr,
            "faithfulness": run.faithfulness,
            "answer_relevance": run.answer_relevance,
            "context_precision": run.context_precision,
            "context_recall": run.context_recall,
            "model_used": run.model_used,
            "eval_kind": run.eval_kind,
            "status": getattr(run, "status", None) or "complete",
            "error_message": run.error_message,
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
        req.model = None
    settings = get_settings()
    for candidate in (req.judge_model, req.model):
        if candidate:
            err = _validate_model_available(candidate, settings)
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
            req.model,
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


# Model ids flow into subprocess argv (run_eval.py / generate_golden.py). A
# value like "--source" or "--out" would be parsed by the harness's argparse as
# an injected flag (verify_models is spread after a nargs="*" option), giving an
# arbitrary-file read/write primitive. Enforce a strict provider/name shape so
# no argv token can begin with "-" or carry separators.
_MODEL_ID_RE = re.compile(r"^(ollama|openai|anthropic|gemini)/[A-Za-z0-9._:-]+$")


def _validate_model_available(model: str, settings) -> str | None:
    """Actionable error message if *model* can't be used, else None. '' means no model."""
    if not model:
        return None
    if not _MODEL_ID_RE.match(model):
        return (
            f"Invalid model id {model!r}. Expected '<provider>/<name>' "
            "(provider: ollama, openai, anthropic, gemini)."
        )
    if model.startswith("ollama/"):
        names, err = _ollama_models(settings)
        if err:
            return f"{err} — cannot use {model}. Start Ollama or pick a frontier model."
        # Ollama treats a tagless name as ":latest" (llama3.2 == llama3.2:latest),
        # so accept a bare id whenever its :latest tag is pulled — /api/tags lists
        # the fully-qualified "llama3.2:latest".
        candidates = {model} if ":" in model.split("/", 1)[1] else {model, f"{model}:latest"}
        if candidates.isdisjoint(names):
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
        frontier += ["openai/gpt-5.4", "openai/gpt-5.1", "openai/gpt-4.1", "openai/gpt-4o-mini"]
    return {"local": sorted(local), "frontier": frontier}


@router.post("/golden/generate", status_code=202)
async def generate_golden_file(req: GoldenGenerateRequest) -> dict[str, str]:
    """Generate or REPLACE a file-backed golden with the good pipeline (personas +
    cross-model verification), chosen models, and a provenance sidecar."""
    if not _GOLDEN_NAME_RE.match(req.name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")
    src = (REPO_ROOT / req.source_file).resolve()
    # is_relative_to avoids the sibling-prefix hole in a raw startswith check
    # (e.g. "<repo>-evil" starts with "<repo>" but is outside it).
    if not src.is_relative_to(REPO_ROOT.resolve()):
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
