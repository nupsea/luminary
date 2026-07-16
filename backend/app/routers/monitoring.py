"""Monitoring endpoints — traces proxy and overview stats.

Routes:
  GET /monitoring/traces        — last 50 spans from Phoenix (empty if Phoenix not running)
  GET /monitoring/overview      — aggregated counts from SQLite + Phoenix status
"""

import logging
import math
import time
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import ChunkModel, DocumentModel, QAHistoryModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

_PHOENIX_BASE = "http://127.0.0.1:6006"
# Must match the project_name registered in app/telemetry.py::setup_tracing.
_PHOENIX_PROJECT = "luminary"
_TRACES_TIMEOUT = 3.0  # seconds
_PHOENIX_REACHABILITY_TTL = 30.0  # seconds

# Module-level cache: {"value": bool, "ts": float}
_phoenix_reachability_cache: dict = {}


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


