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
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/datasets", response_model=list[str])
async def get_datasets() -> list[str]:
    """Return a list of available evaluation datasets (golden JSONL files)."""
    golden_dir = _EVALS_DIR / "golden"
    if not golden_dir.exists():
        return []
    files = list(golden_dir.glob("*.jsonl"))
    return sorted([f.stem for f in files])


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
    _fire_and_forget(_run_eval_subprocess(req.dataset, req.assert_thresholds))
    logger.info(
        "eval run started: dataset=%s assert_thresholds=%s", req.dataset, req.assert_thresholds
    )
    return {"status": "started", "dataset": req.dataset}
