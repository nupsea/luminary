"""Monitoring endpoints — traces proxy and overview stats.

Routes:
  GET /monitoring/traces    — last 50 spans from Phoenix (empty if Phoenix not running)
  GET /monitoring/overview  — aggregated counts from SQLite + Phoenix status
"""

import logging
from datetime import UTC, datetime

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

_PHOENIX_BASE = "http://localhost:6006"
_TRACES_TIMEOUT = 3.0  # seconds


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
