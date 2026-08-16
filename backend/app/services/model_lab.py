"""Compare models across the Luminary workflow, on demand, from the app.

Everything the CLI matrix does, owned by the backend so a comparison is a thing
you start and watch rather than a two-hour terminal session:

  - switch the model per candidate and **always** put it back, including when a
    task fails or the run is cancelled;
  - take the repair counters around every task, in-process, so the deltas belong
    to that task and nothing else;
  - run each workflow stage as its own subprocess, exactly as `make` invokes it,
    because a matrix that ran a runner differently from the gate would be
    measuring a different thing;
  - report the structural tier, which is the only one allowed to decide a swap
    (`eval_tiers`).

**A run mutates this backend while it is in flight.** It changes the selected
model, and generation tasks write flashcards and summaries into the library.
That is why only one may run at a time, why the original model is restored in a
`finally`, and why the UI says so before you start one.

Progress is per task rather than per run: a comparison of four models across
five stages is twenty subprocesses over hours, and a spinner with no detail is
indistinguishable from a hang (I-10).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.paths import app_root
from app.services import llm_output_stats

logger = logging.getLogger(__name__)

REPO_ROOT = app_root()
EVALS_DIR = REPO_ROOT / "evals"
HISTORY_PATH = EVALS_DIR / "model_matrix_history.jsonl"

# Anything spread into a child's argv is validated against this. A single-value
# option consumes one token and is injection-safe, but a value that can start
# with `-` is re-parsed by the child's argparse as a flag -- an arbitrary file
# read/write primitive with no shell involved. See docs/patterns.md.
_MODEL_ID_RE = re.compile(r"^(ollama|openai|anthropic|gemini)/[A-Za-z0-9._:-]+$")
_DATASET_RE = re.compile(r"^[A-Za-z0-9_-]+$")

RunStatus = Literal["running", "complete", "failed", "cancelled"]

# A stage may legitimately run far longer than its estimate on a slow model, so
# the timeout is a wedge detector rather than a schedule.
_TIMEOUT_SLACK = 6
_MIN_TASK_TIMEOUT = 1800.0


@dataclass
class TaskSpec:
    """One workflow stage, and how to measure it.

    `argv` mirrors what the Makefile issues. The venv differs per runner --
    `--project backend` for those importing `app.*`, the evals venv otherwise --
    so the invocation is copied rather than generalised.
    """

    key: str
    label: str
    description: str
    argv: tuple[str, ...]
    cwd: Path
    # Roughly how long one model's pass takes, for the UI to set expectations
    # before someone starts a run that lasts an hour.
    typical_seconds: int
    # True when the task writes generated content into the library.
    mutates_library: bool = False


def task_catalogue(
    backend_url: str, *, qa_datasets: list[str], max_questions: int | None
) -> dict[str, TaskSpec]:
    """Every stage that can be compared, keyed by task id."""
    evals_python = ("uv", "run", "--no-sync", "python")
    backend_python = ("uv", "run", "--project", "backend", "python")

    catalogue: dict[str, TaskSpec] = {
        "intent": TaskSpec(
            key="intent",
            label="Intent routing",
            description=(
                "Adversarial phrasing with the LLM fallback — the arm with headroom. "
                "Ground truth is hand-labelled, so it gates."
            ),
            argv=(
                *backend_python,
                "evals/run_intent_eval.py",
                "--dataset", "intents_adversarial",
                "--llm-fallback",
                "--backend-url", backend_url,
            ),
            cwd=REPO_ROOT,
            typical_seconds=60,
        ),
        "flashcards": TaskSpec(
            key="flashcards",
            label="Flashcards",
            description=(
                "Structural half only: cards asked for against cards delivered, what "
                "the parser repaired, and what the deterministic gate rejected."
            ),
            argv=(
                *evals_python,
                "run_flashcard_eval.py",
                "--skip-judge",
                "--backend-url", backend_url,
            ),
            cwd=EVALS_DIR,
            typical_seconds=300,
            mutates_library=True,
        ),
        "summary": TaskSpec(
            key="summary",
            label="Summaries",
            description=(
                "Regenerated per model — a stored summary scores whichever model wrote "
                "it first. Reports grounding and coverage; contributes no structural metric."
            ),
            argv=(
                *evals_python,
                "run_summary_eval.py",
                "--mode", "executive",
                "--skip-judge",
                "--force-refresh",
                "--backend-url", backend_url,
            ),
            cwd=EVALS_DIR,
            typical_seconds=180,
            mutates_library=True,
        ),
    }

    for dataset in qa_datasets:
        argv = [
            *evals_python,
            "run_eval.py",
            "--dataset", dataset,
            "--generate",
            "--check-citations",
            # No judge: the judged tier never gates a swap, and on a one-model
            # machine it would be grading its own answers.
            "--judge-model", "",
            "--backend-url", backend_url,
        ]
        if max_questions:
            argv += ["--max-questions", str(max_questions)]
        catalogue[f"qa:{dataset}"] = TaskSpec(
            key=f"qa:{dataset}",
            label=f"Answering — {dataset}",
            description=(
                f"Answer rate, citation validity and abstention over {dataset}. "
                "The most discriminating stage in the suite."
            ),
            argv=tuple(argv),
            cwd=EVALS_DIR,
            typical_seconds=(max_questions or 40) * 32,
        )
    return catalogue


@dataclass
class TaskResult:
    task: str
    status: Literal["pending", "running", "complete", "failed"] = "pending"
    exit_code: int | None = None
    duration_s: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    # The runner's own WARNING lines, kept whether or not it failed: a stage
    # that skipped rows still reports, and the reason belongs beside the number.
    warnings: list[str] = field(default_factory=list)
    stderr_tail: list[str] = field(default_factory=list)


@dataclass
class ArmResult:
    model: str
    tasks: list[TaskResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)

    @property
    def failed_tasks(self) -> list[str]:
        return [t.task for t in self.tasks if t.status == "failed"]


@dataclass
class MatrixRun:
    id: str
    models: list[str]
    tasks: list[str]
    status: RunStatus = "running"
    started_at: str = ""
    finished_at: str | None = None
    arms: list[ArmResult] = field(default_factory=list)
    separation: dict[str, Any] | None = None
    error: str | None = None
    restored_model: str | None = None
    # Set when the original model could not be put back. Loud, because the app
    # is then serving a model the user did not choose.
    restore_error: str | None = None

    @property
    def total_units(self) -> int:
        return len(self.models) * len(self.tasks)

    @property
    def completed_units(self) -> int:
        return sum(
            1 for arm in self.arms for t in arm.tasks if t.status in ("complete", "failed")
        )


_runs: dict[str, MatrixRun] = {}
_current: str | None = None
_cancel = asyncio.Event()


class MatrixBusy(RuntimeError):
    """A run is already in flight. Only one may hold the model selection."""


def validate_models(models: list[str]) -> str | None:
    if not models:
        return "Name at least one model."
    for model in models:
        if not _MODEL_ID_RE.match(model):
            return (
                f"Invalid model id {model!r}. Expected '<provider>/<name>' "
                "(provider: ollama, openai, anthropic, gemini)."
            )
    if len(set(models)) != len(models):
        return "The same model is listed twice."
    return None


def validate_datasets(datasets: list[str]) -> str | None:
    for dataset in datasets:
        if not _DATASET_RE.match(dataset):
            return f"Invalid dataset name {dataset!r}."
        if not (EVALS_DIR / "golden" / f"{dataset}.jsonl").exists():
            return f"No golden for dataset {dataset!r}."
    return None


def current_run() -> MatrixRun | None:
    return _runs.get(_current) if _current else None


def get_run(run_id: str) -> MatrixRun | None:
    return _runs.get(run_id)


def recent_runs(limit: int = 20) -> list[MatrixRun]:
    return sorted(_runs.values(), key=lambda r: r.started_at, reverse=True)[:limit]


def request_cancel() -> bool:
    """Ask the in-flight run to stop after the task it is on.

    A completed call is the finest granularity available: an eval subprocess
    mid-generation cannot be interrupted without leaving the counters describing
    a partial pass, and a partial pass is not evidence.
    """
    if _current is None:
        return False
    _cancel.set()
    return True


def _repairs_between(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    b, a = before.get("counts", {}), after.get("counts", {})
    counts = {
        key: a.get(key, 0) - b.get(key, 0)
        for key in set(a) | set(b)
        if a.get(key, 0) - b.get(key, 0)
    }
    parses = counts.get("parses", 0)
    gated = counts.get("cards_gated", 0)
    out: dict[str, Any] = dict(counts)
    if parses:
        out["first_pass_rate"] = counts.get("parses_first_pass", 0) / parses
        out["parse_failure_rate"] = counts.get("parse_failures", 0) / parses
        out["shape_deviation_rate"] = counts.get("shape_deviations", 0) / parses
    if gated:
        out["card_reject_rate"] = counts.get("cards_rejected", 0) / gated
    return out


def _history_offset() -> int:
    return HISTORY_PATH.stat().st_size if HISTORY_PATH.exists() else 0


def _scores_path() -> Path:
    return EVALS_DIR / "scores_history.jsonl"


def _rows_since(offset: int) -> tuple[list[dict[str, Any]], int]:
    path = _scores_path()
    if not path.exists():
        return [], offset
    with path.open() as fh:
        fh.seek(offset)
        rows = [json.loads(line) for line in fh if line.strip()]
        return rows, fh.tell()


def _metrics_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for row in rows:
        for key, value in row.items():
            if key in ("timestamp", "environment", "passed", "dataset", "model", "eval_kind"):
                continue
            if value is None:
                continue
            if key == "output_repairs" and isinstance(value, dict):
                metrics |= dict(value)
                continue
            if isinstance(value, (int, float, str)):
                metrics[key] = value
    return metrics


async def _switch_model(model: str) -> str:
    """Point this backend at *model* and confirm it took.

    Never measure a model you did not switch to: a save that silently failed
    would attribute one model's numbers to another, which is the exact failure
    this whole surface exists to prevent.
    """
    from app.database import get_session_factory  # noqa: PLC0415
    from app.services import settings_service  # noqa: PLC0415

    async with get_session_factory()() as session:
        await settings_service.update_llm_settings(
            session, mode="private", local_chat_model=model
        )
    resolved = settings_service.get_local_chat_model()
    if resolved != model:
        raise RuntimeError(f"asked for {model}, backend resolved {resolved!r}")
    return resolved


async def _environment() -> dict[str, Any]:
    from app.database import get_session_factory  # noqa: PLC0415
    from app.services.eval_environment import collect_environment  # noqa: PLC0415

    async with get_session_factory()() as session:
        return await collect_environment(session)


async def _run_task(spec: TaskSpec, backend_url: str) -> TaskResult:
    """One runner subprocess, with the repair counters taken around it."""
    result = TaskResult(task=spec.key, status="running")
    offset = _scores_offset()
    before = llm_output_stats.snapshot()
    started = time.monotonic()
    # Generous, because these are batch jobs on a local model and a tight bound
    # is how a slow model comes to look like a broken one. Present at all
    # because a wedged runner would otherwise hold the model selection for ever.
    budget = max(spec.typical_seconds * _TIMEOUT_SLACK, _MIN_TASK_TIMEOUT)
    try:
        proc = await asyncio.to_thread(
            subprocess.run,  # noqa: S603 -- fixed argv, ids validated on entry
            list(spec.argv),
            cwd=str(spec.cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=budget,
        )
    except subprocess.TimeoutExpired:
        result.status = "failed"
        result.error = (
            f"exceeded {int(budget)}s. The stage is a batch job, so this means it "
            "wedged rather than that it was slow."
        )
        result.duration_s = round(time.monotonic() - started, 1)
        return result
    except OSError as exc:
        result.status = "failed"
        result.error = f"{type(exc).__name__}: {exc}"
        result.duration_s = round(time.monotonic() - started, 1)
        return result

    result.duration_s = round(time.monotonic() - started, 1)
    result.exit_code = proc.returncode
    rows, _ = _rows_since(offset)
    metrics = _metrics_from_rows(rows)
    metrics |= _repairs_between(before, llm_output_stats.snapshot())
    result.metrics = metrics

    # The runner's own warnings, whether or not it exited non-zero: a stage that
    # skipped rows still reports, and the reason belongs next to the number.
    result.warnings = [
        line.strip()
        for line in (proc.stderr or "").splitlines()
        if line.startswith(("WARNING", "QUALITY GATE FAILED"))
    ][:10]

    if proc.returncode == 0:
        result.status = "complete"
    else:
        result.status = "failed"
        tail = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
        result.error = (tail[-1] if tail else "runner exited non-zero")[:400]
        # Kept so a failure is diagnosable from the UI rather than only from a
        # terminal someone would have to have been watching.
        result.stderr_tail = tail[-8:]
        logger.warning(
            "model lab: task %s failed rc=%d: %s", spec.key, proc.returncode, result.error
        )
    return result


def _scores_offset() -> int:
    path = _scores_path()
    return path.stat().st_size if path.exists() else 0


async def _execute(run: MatrixRun, catalogue: dict[str, TaskSpec], backend_url: str) -> None:
    """Drive every (model, task) pair, then always put the model back."""
    global _current

    from app.services import settings_service  # noqa: PLC0415

    original = settings_service.get_local_chat_model()
    try:
        for model in run.models:
            if _cancel.is_set():
                run.status = "cancelled"
                break
            arm = ArmResult(model=model)
            run.arms.append(arm)
            try:
                await _switch_model(model)
            except (RuntimeError, OSError) as exc:
                arm.tasks = [
                    TaskResult(task=key, status="failed", error=str(exc)) for key in run.tasks
                ]
                logger.warning("model lab: could not switch to %s: %s", model, exc)
                continue

            for key in run.tasks:
                if _cancel.is_set():
                    run.status = "cancelled"
                    break
                task = TaskResult(task=key, status="running")
                arm.tasks.append(task)
                done = await _run_task(catalogue[key], backend_url)
                arm.tasks[-1] = done
                # A task that did not finish is not evidence: its counters
                # describe however much of the work it got through, and a
                # truncated pass compared against a whole one reads as a
                # difference between the models.
                if done.status == "complete":
                    for metric, value in done.metrics.items():
                        arm.metrics[f"{key}.{metric}"] = value
            arm.environment = await _environment()
            if run.status == "cancelled":
                break

        if run.status != "cancelled":
            run.status = "failed" if _every_task_failed(run) else "complete"
    except Exception as exc:  # noqa: BLE001 - a lab run must never take the app down
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        logger.exception("model lab run %s failed", run.id)
    finally:
        try:
            await _switch_model(original)
            run.restored_model = original
        except (RuntimeError, OSError) as exc:
            run.restore_error = str(exc)
            logger.exception("model lab: could not restore %s", original)
        if len(run.arms) >= 2:
            from app.services.eval_tiers import separation  # noqa: PLC0415

            run.separation = separation(run.arms[0].metrics, run.arms[1].metrics)
        run.finished_at = datetime.now(tz=UTC).isoformat()
        _append_history(run)
        _current = None
        _cancel.clear()


def _every_task_failed(run: MatrixRun) -> bool:
    attempted = [t for arm in run.arms for t in arm.tasks]
    return bool(attempted) and all(t.status == "failed" for t in attempted)


def _append_history(run: MatrixRun) -> None:
    """One line per finished run, beside the CLI matrix's own history."""
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_PATH.open("a") as fh:
            fh.write(json.dumps(to_dict(run)) + "\n")
    except OSError:
        logger.warning("model lab: could not append run history", exc_info=True)


def _from_dict(data: dict[str, Any]) -> MatrixRun:
    run = MatrixRun(
        id=data["id"],
        models=data.get("models", []),
        tasks=data.get("tasks", []),
        status=data.get("status", "complete"),
        started_at=data.get("started_at", ""),
        finished_at=data.get("finished_at"),
        separation=data.get("separation"),
        error=data.get("error"),
        restored_model=data.get("restored_model"),
        restore_error=data.get("restore_error"),
    )
    for arm in data.get("arms", []):
        run.arms.append(
            ArmResult(
                model=arm["model"],
                tasks=[
                    TaskResult(**{k: v for k, v in t.items() if k in _TASK_FIELDS})
                    for t in arm.get("tasks", [])
                ],
                metrics=arm.get("metrics", {}),
                environment=arm.get("environment", {}),
            )
        )
    return run


_TASK_FIELDS = set(TaskResult.__dataclass_fields__)


def load_history(limit: int = 50) -> None:
    """Re-read finished runs from disk into memory.

    Without this a comparison exists only for the life of the process, and in
    development `uvicorn --reload` restarts on every edit -- so a two-hour run
    could be lost to a one-line change. Called at startup; failures are logged
    and never fatal, because a lab with no history is still a working lab.
    """
    if not HISTORY_PATH.exists():
        return
    try:
        with HISTORY_PATH.open() as fh:
            lines = fh.readlines()[-limit:]
    except OSError:
        logger.warning("model lab: could not read run history", exc_info=True)
        return

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        # The CLI matrix writes to the same file in its own shape; skip anything
        # that is not one of ours rather than half-parsing it.
        if not isinstance(data, dict) or "id" not in data or "arms" not in data:
            continue
        try:
            run = _from_dict(data)
        except (KeyError, TypeError):
            logger.debug("model lab: skipping unreadable history row", exc_info=True)
            continue
        # A run recorded as running was interrupted by whatever stopped the
        # process. It never finished, so it is not a result.
        if run.status == "running":
            run.status = "failed"
            run.error = "the backend restarted while this run was in flight"
        _runs.setdefault(run.id, run)


def to_dict(run: MatrixRun) -> dict[str, Any]:
    data = asdict(run)
    data["total_units"] = run.total_units
    data["completed_units"] = run.completed_units
    for arm, source in zip(data["arms"], run.arms, strict=True):
        arm["failed_tasks"] = source.failed_tasks
    return data


async def start(
    models: list[str],
    tasks: list[str],
    *,
    qa_datasets: list[str],
    max_questions: int | None,
    backend_url: str,
) -> MatrixRun:
    """Begin a comparison. Raises MatrixBusy when one is already in flight."""
    global _current

    if _current is not None:
        raise MatrixBusy("a model comparison is already running")

    catalogue = task_catalogue(
        backend_url, qa_datasets=qa_datasets, max_questions=max_questions
    )
    unknown = [t for t in tasks if t not in catalogue]
    if unknown:
        raise ValueError(f"unknown task(s): {unknown}")

    run = MatrixRun(
        id=str(uuid.uuid4()),
        models=list(models),
        tasks=list(tasks),
        started_at=datetime.now(tz=UTC).isoformat(),
    )
    _runs[run.id] = run
    _current = run.id
    _cancel.clear()

    from app.services.background import fire_and_forget  # noqa: PLC0415

    fire_and_forget(_execute(run, catalogue, backend_url), _tasks_ref, label="model lab run")
    return run


_tasks_ref: set[asyncio.Task] = set()


def reset_for_tests() -> None:
    global _current
    _runs.clear()
    _current = None
    _cancel.clear()
