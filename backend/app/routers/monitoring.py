"""Monitoring endpoints — traces proxy and overview stats.

Routes:
  GET /monitoring/traces        — last 50 spans from Phoenix (empty if Phoenix not running)
  GET /monitoring/overview      — aggregated counts from SQLite + Phoenix status
  GET /monitoring/eval-history  — HR@5/MRR/Faithfulness history from scores_history.jsonl
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import ChunkModel, DocumentModel, EvalRunModel, QAHistoryModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

_PHOENIX_BASE = "http://localhost:6006"
_TRACES_TIMEOUT = 3.0  # seconds

# evals/scores_history.jsonl relative to this file (repo-root/evals/)
_SCORES_HISTORY_PATH = Path(__file__).parent.parent.parent.parent / "evals" / "scores_history.jsonl"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TraceItem(BaseModel):
    span_id: str
    trace_id: str
    operation_name: str
    start_time: str
    duration_ms: float
    status: str  # "ok" | "error" | "unset"
    attributes: dict


class TracesResponse(BaseModel):
    traces: list[TraceItem]
    message: str | None = None


class MonitoringOverview(BaseModel):
    llm_status: str
    phoenix_running: bool
    langfuse_configured: bool
    total_documents: int
    total_chunks: int
    qa_calls_today: int
    avg_latency_ms: float | None


class EvalRunCreate(BaseModel):
    dataset_name: str
    model_used: str
    hit_rate_5: float | None = None
    mrr: float | None = None
    faithfulness: float | None = None
    answer_relevance: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None


class EvalRunResponse(BaseModel):
    id: str
    dataset_name: str
    model_used: str
    run_at: datetime
    hit_rate_5: float | None
    mrr: float | None
    faithfulness: float | None
    answer_relevance: float | None
    context_precision: float | None
    context_recall: float | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _check_phoenix_running() -> bool:
    try:
        async with httpx.AsyncClient(timeout=_TRACES_TIMEOUT) as client:
            resp = await client.get(f"{_PHOENIX_BASE}/healthz")
            return resp.status_code < 400
    except Exception:
        return False


async def _fetch_phoenix_spans(limit: int = 50) -> list[TraceItem]:
    """Fetch recent spans from Phoenix REST API. Returns [] on failure."""
    try:
        async with httpx.AsyncClient(timeout=_TRACES_TIMEOUT) as client:
            resp = await client.get(
                f"{_PHOENIX_BASE}/v1/spans",
                params={"limit": limit, "sort_col": "startTime", "sort_dir": "desc"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            spans_raw = data if isinstance(data, list) else data.get("data", [])
            items: list[TraceItem] = []
            for s in spans_raw[:limit]:
                attrs = s.get("attributes", s.get("context", {}))
                start = s.get("start_time", s.get("startTime", ""))
                end = s.get("end_time", s.get("endTime", ""))
                duration_ms = 0.0
                if start and end:
                    try:
                        t_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        t_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
                        duration_ms = (t_end - t_start).total_seconds() * 1000
                    except Exception:
                        pass
                items.append(
                    TraceItem(
                        span_id=str(s.get("span_id", s.get("context", {}).get("span_id", ""))),
                        trace_id=str(
                            s.get("trace_id", s.get("context", {}).get("trace_id", ""))
                        ),
                        operation_name=str(s.get("name", s.get("span_kind", "unknown"))),
                        start_time=start,
                        duration_ms=round(duration_ms, 2),
                        status=str(s.get("status_code", s.get("status", "unset"))).lower(),
                        attributes=attrs if isinstance(attrs, dict) else {},
                    )
                )
            return items
    except Exception as exc:
        logger.debug("Phoenix span fetch failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/traces", response_model=TracesResponse)
async def get_traces() -> TracesResponse:
    """Return last 50 spans from Phoenix. Returns empty list if Phoenix is not running."""
    settings = get_settings()
    if not settings.PHOENIX_ENABLED:
        return TracesResponse(traces=[], message="Phoenix is disabled")

    running = await _check_phoenix_running()
    if not running:
        return TracesResponse(traces=[], message="Phoenix is not running")

    spans = await _fetch_phoenix_spans(limit=50)
    return TracesResponse(traces=spans)


@router.get("/overview", response_model=MonitoringOverview)
async def get_overview(
    db: AsyncSession = Depends(get_db),
) -> MonitoringOverview:
    """Return aggregated monitoring stats from SQLite and Phoenix health check."""
    settings = get_settings()

    # Total documents
    doc_result = await db.execute(select(func.count()).select_from(DocumentModel))
    total_documents = doc_result.scalar_one() or 0

    # Total chunks
    chunk_result = await db.execute(select(func.count()).select_from(ChunkModel))
    total_chunks = chunk_result.scalar_one() or 0

    # QA calls today (UTC midnight)
    today_start = datetime.now(tz=UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    qa_result = await db.execute(
        select(func.count())
        .select_from(QAHistoryModel)
        .where(QAHistoryModel.created_at >= today_start)
    )
    qa_calls_today = qa_result.scalar_one() or 0

    # Phoenix health
    phoenix_running = await _check_phoenix_running() if settings.PHOENIX_ENABLED else False

    # LLM status
    llm_status = settings.LITELLM_DEFAULT_MODEL

    return MonitoringOverview(
        llm_status=llm_status,
        phoenix_running=phoenix_running,
        langfuse_configured=bool(settings.LANGFUSE_PUBLIC_KEY),
        total_documents=total_documents,
        total_chunks=total_chunks,
        qa_calls_today=qa_calls_today,
        avg_latency_ms=None,  # Would require span query if Phoenix running
    )


@router.post("/evals/store", response_model=EvalRunResponse, status_code=201)
async def store_eval_run(
    payload: EvalRunCreate,
    db: AsyncSession = Depends(get_db),
) -> EvalRunResponse:
    """Persist a completed evaluation run to SQLite."""
    run = EvalRunModel(
        id=str(uuid.uuid4()),
        dataset_name=payload.dataset_name,
        model_used=payload.model_used,
        run_at=datetime.now(tz=UTC),
        hit_rate_5=payload.hit_rate_5,
        mrr=payload.mrr,
        faithfulness=payload.faithfulness,
        answer_relevance=payload.answer_relevance,
        context_precision=payload.context_precision,
        context_recall=payload.context_recall,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    logger.info(
        "Stored eval run",
        extra={"id": run.id, "dataset_name": payload.dataset_name},
    )
    return EvalRunResponse(
        id=run.id,
        dataset_name=run.dataset_name,
        model_used=run.model_used,
        run_at=run.run_at,
        hit_rate_5=run.hit_rate_5,
        mrr=run.mrr,
        faithfulness=run.faithfulness,
        answer_relevance=run.answer_relevance,
        context_precision=run.context_precision,
        context_recall=run.context_recall,
    )


@router.get("/evals", response_model=list[EvalRunResponse])
async def get_eval_runs(
    db: AsyncSession = Depends(get_db),
) -> list[EvalRunResponse]:
    """Return the last 10 eval runs per dataset, ordered by run_at desc."""
    result = await db.execute(
        select(EvalRunModel).order_by(EvalRunModel.run_at.desc()).limit(50)
    )
    runs = result.scalars().all()

    # Keep at most 10 per dataset
    per_dataset: dict[str, list[EvalRunModel]] = {}
    for run in runs:
        per_dataset.setdefault(run.dataset_name, [])
        if len(per_dataset[run.dataset_name]) < 10:
            per_dataset[run.dataset_name].append(run)

    # Flatten, preserving desc order within each dataset
    all_runs: list[EvalRunModel] = []
    for dataset_runs in per_dataset.values():
        all_runs.extend(dataset_runs)
    all_runs.sort(key=lambda r: r.run_at, reverse=True)

    return [
        EvalRunResponse(
            id=r.id,
            dataset_name=r.dataset_name,
            model_used=r.model_used,
            run_at=r.run_at,
            hit_rate_5=r.hit_rate_5,
            mrr=r.mrr,
            faithfulness=r.faithfulness,
            answer_relevance=r.answer_relevance,
            context_precision=r.context_precision,
            context_recall=r.context_recall,
        )
        for r in all_runs
    ]


class ModelUsageItem(BaseModel):
    model: str
    call_count: int
    avg_latency_ms: float | None


@router.get("/model-usage", response_model=list[ModelUsageItem])
async def get_model_usage(
    db: AsyncSession = Depends(get_db),
) -> list[ModelUsageItem]:
    """Return call counts per model from QA history."""
    result = await db.execute(
        select(QAHistoryModel.model_used, func.count().label("call_count"))
        .group_by(QAHistoryModel.model_used)
        .order_by(func.count().desc())
    )
    rows = result.all()
    return [
        ModelUsageItem(
            model=row.model_used,
            call_count=row.call_count,
            avg_latency_ms=None,  # QAHistoryModel has no latency column
        )
        for row in rows
    ]


class EvalHistoryItem(BaseModel):
    timestamp: str
    dataset: str
    model: str
    hr5: float | None
    mrr: float | None
    faithfulness: float | None
    passed: bool


@router.get("/eval-history", response_model=list[EvalHistoryItem])
async def get_eval_history() -> list[EvalHistoryItem]:
    """Return eval score history from evals/scores_history.jsonl (all runs, oldest first)."""
    if not _SCORES_HISTORY_PATH.exists():
        return []
    items: list[EvalHistoryItem] = []
    with _SCORES_HISTORY_PATH.open() as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
                items.append(EvalHistoryItem(**row))
            except Exception:
                pass
    return items
