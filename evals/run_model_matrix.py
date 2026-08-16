#!/usr/bin/env python3
"""Run the model-sensitive evals across candidate models, on one instrument.

The last model comparison could not see the models it compared: prompts were
written for the weakest one, two tolerant parsers repaired whatever came back,
and every metric on the board had no generation-model term in it. So a swap
moved nothing and the decision was made on hope.

This drives the runners that *do* move with the model -- intent routing,
flashcard generation, summary, and the answering path -- switching the backend's
model between candidates and taking the repair counters around every run. It
reports three tiers (see `evals/lib/matrix.py`): structural gates a swap, quality
is reported and never gates, retrieval metrics are excluded outright.

Two arms the previous attempt lacked, both restart-level backend settings so a
run cannot straddle them:

  PROMPT_ARM=bare                 the scaffolding-tax arm. A model that scores
                                  HIGHER without the accommodations is telling
                                  you the accommodation set is its ceiling.
  PROMPT_DROP_ACCOMMODATIONS=id   the necessity check, one at a time. What
                                  survives is what `accommodations_needed` on
                                  the registry entry should say.

The arm is read from the backend and recorded; this script refuses to run when
the backend is not in the arm that was asked for, because a matrix that mixes
arms is worse than no matrix.

Acceptance criterion for the instrument itself: `--assert-separation` fails
unless the structural tier tells two models of different size apart. If it
cannot, do not choose a model on it -- add metrics until it can.

Usage::

    python evals/run_model_matrix.py --models ollama/llama3.2,ollama/qwen3.5:4b
    python evals/run_model_matrix.py --models a,b --tasks intent,flashcards \\
        --assert-separation
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.lib.matrix import (  # noqa: E402
    LIBRARY_STATE_DEPENDENT,
    metric_name,
    separation,
    structural_metrics,
    tier,
)
from evals.lib.scoring_history import SCORES_HISTORY_PATH  # noqa: E402

EVALS_DIR = REPO_ROOT / "evals"
MATRIX_HISTORY = EVALS_DIR / "model_matrix_history.jsonl"
_MODEL_ID_RE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-/")


@dataclass(frozen=True)
class Task:
    """One runner invocation, exactly as the Makefile issues it.

    The venv differs per runner (`--project backend` versus the evals venv), so
    the argv is copied rather than generalised: a matrix that ran a runner
    differently from `make` would measure a different thing from the gate.
    """

    name: str
    cwd: Path
    argv: tuple[str, ...]
    note: str


def _tasks(backend_url: str) -> dict[str, Task]:
    return {
        "intent": Task(
            name="intent",
            cwd=REPO_ROOT,
            argv=(
                "uv", "run", "--project", "backend", "python",
                "evals/run_intent_eval.py",
                "--dataset", "intents_adversarial",
                "--llm-fallback",
                "--backend-url", backend_url,
            ),
            note="adversarial phrasing with the LLM fallback -- where the headroom is",
        ),
        "flashcards": Task(
            name="flashcards",
            cwd=EVALS_DIR,
            argv=(
                "uv", "run", "--no-sync", "python",
                "run_flashcard_eval.py",
                "--skip-judge",
                "--backend-url", backend_url,
            ),
            note="structural half only: a one-model machine judges its own cards",
        ),
        "summary": Task(
            name="summary",
            cwd=EVALS_DIR,
            argv=(
                "uv", "run", "--no-sync", "python",
                "run_summary_eval.py",
                "--mode", "executive",
                "--skip-judge",
                "--force-refresh",
                "--backend-url", backend_url,
            ),
            note="deterministic half, regenerated: a stored summary scores the model that wrote it",
        ),
        "qa": Task(
            name="qa",
            cwd=EVALS_DIR,
            argv=(
                "uv", "run", "--no-sync", "python",
                "run_eval.py",
                "--dataset", "book",
                "--generate",
                "--check-citations",
                "--judge-model", "",
                "--backend-url", backend_url,
            ),
            note="answering path: answer rate and citation validity, no judge",
        ),
    }


def _valid_model_id(model: str) -> bool:
    """Reject anything that could be re-parsed as a flag by a child argparse."""
    return bool(model) and not model.startswith("-") and set(model) <= _MODEL_ID_RE_CHARS


def _environment(backend_url: str) -> dict[str, Any]:
    resp = httpx.get(f"{backend_url.rstrip('/')}/evals/environment", timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _output_stats(backend_url: str) -> dict[str, Any]:
    resp = httpx.get(f"{backend_url.rstrip('/')}/evals/output-stats", timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _repairs_between(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What this run's completions needed before they could be used.

    Taken by the matrix around every task rather than left to each runner, so a
    task whose runner does not record repairs still contributes to the
    structural tier.
    """
    b, a = before.get("counts", {}), after.get("counts", {})
    counts = {
        key: a.get(key, 0) - b.get(key, 0)
        for key in set(a) | set(b)
        if a.get(key, 0) - b.get(key, 0)
    }
    parses = counts.get("parses", 0)
    gated = counts.get("cards_gated", 0)
    out: dict[str, Any] = {"counts": counts}
    if parses:
        out["first_pass_rate"] = counts.get("parses_first_pass", 0) / parses
        out["parse_failure_rate"] = counts.get("parse_failures", 0) / parses
        out["shape_deviation_rate"] = counts.get("shape_deviations", 0) / parses
    if gated:
        out["card_reject_rate"] = counts.get("cards_rejected", 0) / gated
    return out


def _switch_model(backend_url: str, model: str) -> str:
    """Point the backend at *model* and confirm it took. Returns the resolved id.

    Never measure a model you did not switch to: a PATCH that silently failed
    would attribute one model's numbers to another, which is the exact failure
    this whole stage exists to prevent.
    """
    resp = httpx.patch(
        f"{backend_url.rstrip('/')}/settings/llm",
        json={"mode": "private", "local_chat_model": model},
        timeout=60.0,
    )
    resp.raise_for_status()
    env = _environment(backend_url)
    resolved = env.get("chat_model", "")
    if resolved != model:
        raise RuntimeError(
            f"asked for {model}, backend resolved {resolved!r} -- refusing to measure"
        )
    return resolved


def _installed_models(backend_url: str) -> list[str]:
    resp = httpx.get(f"{backend_url.rstrip('/')}/settings/llm", timeout=30.0)
    resp.raise_for_status()
    return list(resp.json().get("available_local_models") or [])


def _history_rows_since(offset: int) -> tuple[list[dict[str, Any]], int]:
    """Rows appended to scores_history.jsonl since *offset*, and the new offset.

    Every runner already records its metrics and its environment there, so the
    matrix reads what the gate reads instead of parsing printed tables.
    """
    if not SCORES_HISTORY_PATH.exists():
        return [], offset
    with SCORES_HISTORY_PATH.open() as fh:
        fh.seek(offset)
        rows = [json.loads(line) for line in fh if line.strip()]
        return rows, fh.tell()


def _history_offset() -> int:
    return SCORES_HISTORY_PATH.stat().st_size if SCORES_HISTORY_PATH.exists() else 0


def _metrics_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten a runner's history rows into the metrics the matrix reports."""
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


def run_task(task: Task, backend_url: str) -> dict[str, Any]:
    """Run one runner and collect everything the matrix reports about it."""
    offset = _history_offset()
    before = _output_stats(backend_url)
    started = time.monotonic()
    proc = subprocess.run(  # noqa: S603 -- fixed argv, model ids validated
        list(task.argv),
        cwd=task.cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "UV_CACHE_DIR": str(REPO_ROOT / ".uv-cache")},
    )
    duration = time.monotonic() - started
    rows, _ = _history_rows_since(offset)
    repairs = _repairs_between(before, _output_stats(backend_url))

    metrics = _metrics_from_rows(rows)
    metrics |= repairs["counts"]
    for key in (
        "first_pass_rate",
        "parse_failure_rate",
        "shape_deviation_rate",
        "card_reject_rate",
    ):
        if key in repairs:
            metrics[key] = repairs[key]

    return {
        "task": task.name,
        "exit_code": proc.returncode,
        "duration_s": round(duration, 1),
        "rows_recorded": len(rows),
        "metrics": metrics,
        "stderr_tail": proc.stderr.strip().splitlines()[-3:] if proc.returncode else [],
    }


def run_model(model: str, tasks: list[Task], backend_url: str) -> dict[str, Any]:
    resolved = _switch_model(backend_url, model)
    results = [run_task(task, backend_url) for task in tasks]
    merged: dict[str, Any] = {}
    for result in results:
        for key, value in result["metrics"].items():
            merged[f"{result['task']}.{key}"] = value
    return {
        "model": resolved,
        "tasks": results,
        "metrics": merged,
        "environment": _environment(backend_url),
    }


def _print_report(arms: list[dict[str, Any]], tasks: list[Task]) -> None:
    print(f"\n{'=' * 78}")
    print("  Model matrix")
    print(f"{'=' * 78}")
    for task in tasks:
        print(f"  {task.name:<12} {task.note}")
    print()

    models = [arm["model"] for arm in arms]
    for label, keep in (
        ("structural -- gates a swap", "structural"),
        ("quality -- report only, never gates", "quality"),
    ):
        keys = sorted(
            {
                key
                for arm in arms
                for key in arm["metrics"]
                if tier(key) == keep
            }
        )
        if not keys:
            continue
        print(f"  {label}")
        header = "  " + f"{'metric':<34}" + "".join(f"{m[-22:]:>24}" for m in models)
        print(header)
        for key in keys:
            cells = []
            for arm in arms:
                value = arm["metrics"].get(key)
                if value is None:
                    cells.append(f"{'-':>24}")
                elif isinstance(value, float):
                    cells.append(f"{value:>24.4f}")
                else:
                    cells.append(f"{value:>24}")
            marker = " *" if metric_name(key) in LIBRARY_STATE_DEPENDENT else ""
            print("  " + f"{key + marker:<34}" + "".join(cells))
        print()

    print("  * library-state dependent: reported, never allowed to decide a separation")
    failures = [
        (arm["model"], result["task"], result["stderr_tail"])
        for arm in arms
        for result in arm["tasks"]
        if result["exit_code"] != 0
    ]
    for model, task, tail in failures:
        print(f"  NOTE: {model} {task} exited non-zero: {' | '.join(tail) or 'no stderr'}")
    print()


def _print_separation(verdict: dict[str, Any], a: str, b: str) -> None:
    print(f"  separation  {a}  vs  {b}")
    for row in verdict["deltas"]:
        mark = "yes" if row["significant"] else " no"
        print(
            f"    [{mark}] {row['metric']:<40} {row['a']:>12.4f} -> {row['b']:>12.4f}"
            f"  ({row['delta']:+.4f})"
        )
    for task in verdict["unmeasured_tasks"]:
        print(
            f"  WARNING: every {task} metric is identical on both models. Two models do not\n"
            f"  score the same to full precision on work that depends on them -- {task}\n"
            "  measured something other than the model, and its numbers say nothing here.\n"
        )
    if verdict["separated"]:
        print(f"  SEPARATED on {', '.join(verdict['separating_metrics'])}\n")
    else:
        print(
            "  NOT SEPARATED: the structural tier cannot tell these two models apart.\n"
            "  That is a finding about the instrument, not the models. Add metrics\n"
            "  until it can, and do not choose a model on it in the meantime.\n"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", required=True, help="comma-separated model ids, in order")
    ap.add_argument("--backend-url", default="http://localhost:7820")
    ap.add_argument("--tasks", default="intent,flashcards,summary")
    ap.add_argument(
        "--arm",
        choices=["shipped", "bare"],
        default="shipped",
        help="the arm the backend must already be in; a mixed matrix is refused",
    )
    ap.add_argument(
        "--assert-separation",
        action="store_true",
        help="fail unless the structural tier tells the first two models apart",
    )
    ap.add_argument("--out", default=str(MATRIX_HISTORY))
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    invalid = [m for m in models if not _valid_model_id(m)]
    if invalid:
        print(f"ERROR: refusing model id(s) {invalid}", file=sys.stderr)
        return 1
    if args.assert_separation and len(models) < 2:
        print("ERROR: --assert-separation needs at least two models", file=sys.stderr)
        return 1

    available = _tasks(args.backend_url)
    unknown = [t for t in args.tasks.split(",") if t.strip() and t.strip() not in available]
    if unknown:
        print(f"ERROR: unknown task(s) {unknown}; known: {sorted(available)}", file=sys.stderr)
        return 1
    tasks = [available[t.strip()] for t in args.tasks.split(",") if t.strip()]

    start_env = _environment(args.backend_url)
    backend_arm = start_env.get("prompt_arm", "shipped")
    if backend_arm != args.arm:
        print(
            f"ERROR: backend is in the {backend_arm!r} prompt arm, --arm asked for "
            f"{args.arm!r}. Restart the backend with PROMPT_ARM={args.arm} "
            "-- the arm is read at import, and a matrix that mixes arms is worse "
            "than no matrix.",
            file=sys.stderr,
        )
        return 1

    installed = _installed_models(args.backend_url)
    missing = [m for m in models if installed and m not in installed]
    if missing:
        print(f"ERROR: not installed on this host: {missing}", file=sys.stderr)
        return 1

    original = start_env.get("local_chat_model") or start_env.get("chat_model") or ""
    arms: list[dict[str, Any]] = []
    try:
        for model in models:
            print(f"\n>>> {model}")
            arms.append(run_model(model, tasks, args.backend_url))
    finally:
        if original:
            try:
                _switch_model(args.backend_url, original)
                print(f"\n  restored {original}")
            except (httpx.HTTPError, RuntimeError) as exc:
                print(f"\n  WARNING: could not restore {original}: {exc}", file=sys.stderr)

    _print_report(arms, tasks)

    verdict = None
    if len(arms) >= 2:
        verdict = separation(arms[0]["metrics"], arms[1]["metrics"])
        _print_separation(verdict, arms[0]["model"], arms[1]["model"])

    record = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "arm": args.arm,
        "tasks": [t.name for t in tasks],
        "models": [arm["model"] for arm in arms],
        "results": [
            {
                "model": arm["model"],
                "metrics": arm["metrics"],
                "structural": structural_metrics(arm["metrics"]),
                "environment": arm["environment"],
                "tasks": [
                    {k: v for k, v in result.items() if k != "metrics"} for result in arm["tasks"]
                ],
            }
            for arm in arms
        ],
        "separation": verdict,
    }
    with Path(args.out).open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    print(f"  recorded to {args.out}")

    if args.assert_separation and (verdict is None or not verdict["separated"]):
        print(
            "MATRIX GATE FAILED: the structural tier did not separate "
            f"{arms[0]['model']} from {arms[1]['model']}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
