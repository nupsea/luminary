"""Monitoring endpoints — traces proxy and overview stats.

Routes:
  GET /monitoring/traces        — last 50 spans from Phoenix (empty if Phoenix not running)
  GET /monitoring/overview      — aggregated counts from SQLite + Phoenix status
  GET /monitoring/eval-history  — HR@5/MRR/Faithfulness history from scores_history.jsonl
"""

import json
import logging
import math
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import ChunkModel, DocumentModel, EvalRunModel, QAHistoryModel
from app.services.eval_regression_service import detect_regressions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

_PHOENIX_BASE = "http://127.0.0.1:6006"
# Must match the project_name registered in app/telemetry.py::setup_tracing.
_PHOENIX_PROJECT = "luminary"
_TRACES_TIMEOUT = 3.0  # seconds
_PHOENIX_REACHABILITY_TTL = 30.0  # seconds

# Module-level cache: {"value": bool, "ts": float}
_phoenix_reachability_cache: dict = {}

# evals/scores_history.jsonl relative to this file (repo-root/evals/)
_SCORES_HISTORY_PATH = Path(__file__).parent.parent.parent.parent / "evals" / "scores_history.jsonl"


class TraceItem(BaseModel):
    span_id: str
    trace_id: str
    operation_name: str
    span_kind: str = "UNKNOWN"  # OpenInference kind: CHAIN | LLM | RETRIEVER | ...
    parent_id: str | None = None
    start_time: str
    duration_ms: float
    status: str  # "ok" | "error" | "unset"
    status_message: str = ""
    attributes: dict


class TracesResponse(BaseModel):
    traces: list[TraceItem]
    message: str | None = None


class MonitoringOverview(BaseModel):
    llm_status: str
    phoenix_running: bool
    phoenix_configured: bool = False
    langfuse_configured: bool
    total_documents: int
    total_chunks: int
    qa_calls_today: int


class EvalRunCreate(BaseModel):
    dataset_name: str
    model_used: str
    eval_kind: str | None = "retrieval"
    hit_rate_5: float | None = None
    mrr: float | None = None
    faithfulness: float | None = None
    answer_relevance: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    citation_support_rate: float | None = None
    theme_coverage: float | None = None
    no_hallucination: float | None = None
    conciseness_pct: float | None = None
    factuality: float | None = None
    atomicity: float | None = None
    clarity_avg: float | None = None
    routing_accuracy: float | None = None
    per_route: dict | None = None
    ablation_metrics: dict | None = None
    extra_metrics: dict | None = None


class EvalRunResponse(BaseModel):
    id: str
    dataset_name: str
    model_used: str
    eval_kind: str | None
    run_at: datetime
    hit_rate_5: float | None
    mrr: float | None
    faithfulness: float | None
    answer_relevance: float | None
    context_precision: float | None
    context_recall: float | None
    citation_support_rate: float | None = None
    theme_coverage: float | None = None
    no_hallucination: float | None = None
    conciseness_pct: float | None = None
    factuality: float | None = None
    atomicity: float | None = None
    clarity_avg: float | None = None
    routing_accuracy: float | None = None
    per_route: dict | None = None
    ablation_metrics: dict | None = None
    extra_metrics: dict | None = None


class EvalRegressionResponse(BaseModel):
    dataset: str
    metric: str
    current_value: float
    baseline_value: float
    drop_pct: float
    eval_kind: str | None = None


class PhoenixUrlResponse(BaseModel):
    url: str
    enabled: bool  # configured AND currently reachable
    configured: bool = False  # PHOENIX_ENABLED in backend settings


async def _check_phoenix_running() -> bool:
    """GET /healthz with the result cached for 30 seconds.

    Shared by /overview, /traces and /phoenix-url so a page render costs at
    most one health probe instead of three.
    """
    now = time.monotonic()
    cached = _phoenix_reachability_cache
    if cached.get("ts") and now - cached["ts"] < _PHOENIX_REACHABILITY_TTL:
        return bool(cached["value"])
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{_PHOENIX_BASE}/healthz")
            reachable = resp.status_code < 400
    except Exception:
        reachable = False
    _phoenix_reachability_cache["value"] = reachable
    _phoenix_reachability_cache["ts"] = now
    return reachable


async def _fetch_phoenix_spans(limit: int = 50) -> list[TraceItem]:
    """Fetch recent spans from Phoenix REST API. Returns [] on failure.

    Uses GET /v1/projects/{project}/spans (arize-phoenix >= 9). The older
    GET /v1/spans is deprecated and requires a request body, so a plain GET
    against it 422s — that was why the traces panel always came back empty.
    Spans are returned newest-first. 404 means the project has no traces yet.
    """
    try:
        async with httpx.AsyncClient(timeout=_TRACES_TIMEOUT) as client:
            resp = await client.get(
                f"{_PHOENIX_BASE}/v1/projects/{_PHOENIX_PROJECT}/spans",
                params={"limit": limit},
            )
            if resp.status_code != 200:
                return []
            spans_raw = resp.json().get("data", [])
            items: list[TraceItem] = []
            for s in spans_raw[:limit]:
                context = s.get("context") or {}
                start = s.get("start_time") or ""
                end = s.get("end_time") or ""
                duration_ms = 0.0
                if start and end:
                    try:
                        t_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        t_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
                        duration_ms = (t_end - t_start).total_seconds() * 1000
                    except ValueError:
                        pass
                attrs = s.get("attributes")
                items.append(
                    TraceItem(
                        span_id=str(context.get("span_id") or ""),
                        trace_id=str(context.get("trace_id") or ""),
                        operation_name=str(s.get("name") or "unknown"),
                        span_kind=str(s.get("span_kind") or "UNKNOWN"),
                        parent_id=s.get("parent_id"),
                        start_time=start,
                        duration_ms=round(duration_ms, 2),
                        status=str(s.get("status_code") or "UNSET").lower(),
                        status_message=str(s.get("status_message") or ""),
                        attributes=attrs if isinstance(attrs, dict) else {},
                    )
                )
            return items
    except Exception as exc:
        logger.debug("Phoenix span fetch failed: %s", exc)
        return []


@router.get("/phoenix-url", response_model=PhoenixUrlResponse)
async def get_phoenix_url() -> PhoenixUrlResponse:
    """Return the Phoenix UI URL, whether tracing is configured, and reachability."""
    settings = get_settings()
    if not settings.PHOENIX_ENABLED:
        return PhoenixUrlResponse(url=_PHOENIX_BASE, enabled=False, configured=False)
    reachable = await _check_phoenix_running()
    return PhoenixUrlResponse(url=_PHOENIX_BASE, enabled=reachable, configured=True)


@router.get("/traces", response_model=TracesResponse)
async def get_traces(limit: int = 50) -> TracesResponse:
    """Return recent spans from Phoenix. Returns empty list if Phoenix is not running."""
    settings = get_settings()
    if not settings.PHOENIX_ENABLED:
        return TracesResponse(traces=[], message="Phoenix is disabled")

    running = await _check_phoenix_running()
    if not running:
        return TracesResponse(traces=[], message="Phoenix is not running")

    spans = await _fetch_phoenix_spans(limit=max(1, min(limit, 200)))
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
    today_start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    qa_result = await db.execute(
        select(func.count())
        .select_from(QAHistoryModel)
        .where(QAHistoryModel.created_at >= today_start)
    )
    qa_calls_today = qa_result.scalar_one() or 0

    # Phoenix health
    phoenix_running = await _check_phoenix_running() if settings.PHOENIX_ENABLED else False

    return MonitoringOverview(
        llm_status=settings.LITELLM_DEFAULT_MODEL,
        phoenix_running=phoenix_running,
        phoenix_configured=settings.PHOENIX_ENABLED,
        langfuse_configured=bool(settings.LANGFUSE_PUBLIC_KEY),
        total_documents=total_documents,
        total_chunks=total_chunks,
        qa_calls_today=qa_calls_today,
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
        eval_kind=payload.eval_kind or "retrieval",
        run_at=datetime.now(tz=UTC),
        hit_rate_5=payload.hit_rate_5,
        mrr=payload.mrr,
        faithfulness=payload.faithfulness,
        answer_relevance=payload.answer_relevance,
        context_precision=payload.context_precision,
        context_recall=payload.context_recall,
        citation_support_rate=payload.citation_support_rate,
        theme_coverage=payload.theme_coverage,
        no_hallucination=payload.no_hallucination,
        conciseness_pct=payload.conciseness_pct,
        factuality=payload.factuality,
        atomicity=payload.atomicity,
        clarity_avg=payload.clarity_avg,
        routing_accuracy=payload.routing_accuracy,
        per_route=payload.per_route,
        ablation_metrics=payload.ablation_metrics,
        extra_metrics=payload.extra_metrics,
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
        eval_kind=run.eval_kind,
        # aiosqlite reads back tz-naive; attach UTC so clients don't parse as local
        run_at=run.run_at.replace(tzinfo=UTC) if run.run_at.tzinfo is None else run.run_at,
        hit_rate_5=run.hit_rate_5,
        mrr=run.mrr,
        faithfulness=run.faithfulness,
        answer_relevance=run.answer_relevance,
        context_precision=run.context_precision,
        context_recall=run.context_recall,
        citation_support_rate=run.citation_support_rate,
        theme_coverage=run.theme_coverage,
        no_hallucination=run.no_hallucination,
        conciseness_pct=run.conciseness_pct,
        factuality=run.factuality,
        atomicity=run.atomicity,
        clarity_avg=run.clarity_avg,
        routing_accuracy=run.routing_accuracy,
        per_route=run.per_route,
        ablation_metrics=run.ablation_metrics,
        extra_metrics=run.extra_metrics,
    )


@router.get("/evals", response_model=list[EvalRunResponse])
async def get_eval_runs(
    db: AsyncSession = Depends(get_db),
) -> list[EvalRunResponse]:
    """Return the last 10 eval runs per dataset, ordered by run_at desc."""
    result = await db.execute(select(EvalRunModel).order_by(EvalRunModel.run_at.desc()).limit(50))
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
            eval_kind=r.eval_kind,
            run_at=r.run_at.replace(tzinfo=UTC) if r.run_at.tzinfo is None else r.run_at,
            hit_rate_5=r.hit_rate_5,
            mrr=r.mrr,
            faithfulness=r.faithfulness,
            answer_relevance=r.answer_relevance,
            context_precision=r.context_precision,
            context_recall=r.context_recall,
            citation_support_rate=r.citation_support_rate,
            theme_coverage=r.theme_coverage,
            no_hallucination=r.no_hallucination,
            conciseness_pct=r.conciseness_pct,
            factuality=r.factuality,
            atomicity=r.atomicity,
            clarity_avg=r.clarity_avg,
            routing_accuracy=r.routing_accuracy,
            per_route=r.per_route,
            ablation_metrics=r.ablation_metrics,
        )
        for r in all_runs
    ]


@router.get("/evals/regressions", response_model=list[EvalRegressionResponse])
async def get_eval_regressions(
    window: int = 5,
    threshold_pct: float = 0.05,
    db: AsyncSession = Depends(get_db),
) -> list[EvalRegressionResponse]:
    """Return eval metrics whose latest value dropped versus a moving baseline."""
    regressions = await detect_regressions(db, window=window, threshold_pct=threshold_pct)
    return [EvalRegressionResponse(**regression.__dict__) for regression in regressions]


class QADailyCount(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    count: int


class MonitoringMetrics(BaseModel):
    phoenix_available: bool
    spans_sampled: int
    traces_sampled: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    error_count: int
    error_rate: float | None
    llm_calls: int
    llm_prompt_tokens: int
    llm_completion_tokens: int
    spans_by_kind: dict[str, int]
    qa_daily: list[QADailyCount]


def _percentile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, math.ceil(q * len(sorted_vals)) - 1))
    return round(sorted_vals[idx], 1)


@router.get("/metrics", response_model=MonitoringMetrics)
async def get_metrics(
    db: AsyncSession = Depends(get_db),
) -> MonitoringMetrics:
    """Operational metrics: latency/error/token stats from a sample of recent
    Phoenix spans, plus a 7-day QA activity trend from SQLite (available even
    when tracing is off)."""
    settings = get_settings()
    phoenix_available = (
        await _check_phoenix_running() if settings.PHOENIX_ENABLED else False
    )

    spans: list[TraceItem] = []
    if phoenix_available:
        spans = await _fetch_phoenix_spans(limit=200)

    root_durations = sorted(s.duration_ms for s in spans if s.parent_id is None)
    error_count = sum(1 for s in spans if s.status == "error")
    spans_by_kind: dict[str, int] = {}
    llm_calls = llm_prompt_tokens = llm_completion_tokens = 0
    for s in spans:
        spans_by_kind[s.span_kind] = spans_by_kind.get(s.span_kind, 0) + 1
        if s.span_kind == "LLM":
            llm_calls += 1
            try:
                llm_prompt_tokens += int(s.attributes.get("llm.token_count.prompt") or 0)
                llm_completion_tokens += int(
                    s.attributes.get("llm.token_count.completion") or 0
                )
            except (TypeError, ValueError):
                pass

    # QA activity per UTC day, zero-filled over the trailing 7 days.
    today = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=6)
    result = await db.execute(
        select(func.date(QAHistoryModel.created_at).label("day"), func.count())
        .where(QAHistoryModel.created_at >= since.replace(tzinfo=None))
        .group_by("day")
    )
    counts_by_day = {str(row[0]): row[1] for row in result.all()}
    qa_daily = [
        QADailyCount(
            date=(since + timedelta(days=i)).strftime("%Y-%m-%d"),
            count=counts_by_day.get((since + timedelta(days=i)).strftime("%Y-%m-%d"), 0),
        )
        for i in range(7)
    ]

    return MonitoringMetrics(
        phoenix_available=phoenix_available,
        spans_sampled=len(spans),
        traces_sampled=len({s.trace_id for s in spans}),
        latency_p50_ms=_percentile(root_durations, 0.50),
        latency_p95_ms=_percentile(root_durations, 0.95),
        error_count=error_count,
        error_rate=round(error_count / len(spans), 4) if spans else None,
        llm_calls=llm_calls,
        llm_prompt_tokens=llm_prompt_tokens,
        llm_completion_tokens=llm_completion_tokens,
        spans_by_kind=spans_by_kind,
        qa_daily=qa_daily,
    )


class ModelUsageItem(BaseModel):
    model: str
    call_count: int


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
    return [ModelUsageItem(model=row.model_used, call_count=row.call_count) for row in rows]


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
