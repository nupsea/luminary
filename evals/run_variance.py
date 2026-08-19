"""Repeat a generation eval and report the distribution, not a point.

`run_eval.py` measures once. One generation run cannot resolve a change smaller
than ~0.10 on `book` or ~0.05 on `paper`, so a single-run A/B is how a noise-sized
delta gets published as a result -- it has happened twice in this repo.

This driver runs the same command N times against one library state, aggregates
mean and sd from the rows the runs themselves wrote, and gates on the mean. Each
run is a separate process, which is how the committed variance figures were
taken.

Usage::

    # Establish a baseline distribution
    uv run python run_variance.py --dataset book --runs 4 \\
        --judge-model ollama/qwen2.5:14b-instruct --check-citations

    # Compare a change against it
    uv run python run_variance.py --dataset book --runs 4 --compare-to <group> \\
        --judge-model ollama/qwen2.5:14b-instruct --check-citations
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.environment import same_conditions  # noqa: E402
from evals.lib.scoring_history import SCORES_HISTORY_PATH, append_history  # noqa: E402
from evals.lib.variance import aggregate, compare  # noqa: E402
from evals.run_eval import thresholds_for_dataset  # noqa: E402

RUN_EVAL = Path(__file__).resolve().parent / "run_eval.py"


def _is_series_row(row: dict) -> bool:
    """The aggregate this driver writes, not a run it aggregated.

    It carries the same run_group as its members -- that is how it is found
    again -- so without this it counts itself and pulls the mean toward itself.
    """
    return row.get("runs") is not None or str(row.get("eval_kind", "")).endswith("-series")


def _history_rows(run_group: str) -> list[dict]:
    if not SCORES_HISTORY_PATH.exists():
        return []
    rows = []
    for line in SCORES_HISTORY_PATH.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (row.get("environment") or {}).get("run_group") == run_group and not _is_series_row(row):
            rows.append(row)
    return rows


def _execute_series(run_group: str, runs: int, passthrough: list[str]) -> list[int]:
    """Run the eval N times, each in its own process. Returns exit codes."""
    codes = []
    for index in range(1, runs + 1):
        env = os.environ | {
            "LUMINARY_RUN_GROUP": run_group,
            "LUMINARY_RUN_INDEX": str(index),
        }
        print(f"\n=== run {index}/{runs} (group {run_group}) ===", flush=True)
        proc = subprocess.run(  # noqa: S603 -- argv is this script's own flags
            [sys.executable, str(RUN_EVAL), *passthrough],
            cwd=RUN_EVAL.parent,
            env=env,
            check=False,
        )
        codes.append(proc.returncode)
    return codes


def _environment_agrees(rows: list[dict]) -> tuple[bool, list[str]]:
    """Every run in a series must have measured the same system."""
    envs = [r.get("environment") or {} for r in rows]
    differing: set[str] = set()
    for env in envs[1:]:
        _, fields = same_conditions(envs[0], env)
        differing.update(fields)
    return not differing, sorted(differing)


def _print_report(dataset: str, agg: dict, thresholds: dict[str, float]) -> list[str]:
    print(f"\n{'=' * 72}")
    print(f"  Variance -- dataset={dataset}  runs={agg['n']}")
    print(f"{'=' * 72}")
    print(f"  {'metric':<24} {'mean':>9} {'sd':>9} {'min':>9} {'max':>9}  floor")
    violations: list[str] = []
    for key, stats in agg["metrics"].items():
        sd = stats["sd"]
        floor = thresholds.get(key)
        mark = ""
        if floor is not None and stats["mean"] < floor:
            mark = "  FAIL"
            violations.append(f"{key} mean {stats['mean']:.4f} < floor {floor}")
        print(
            f"  {key:<24} {stats['mean']:>9.4f} "
            f"{'n/a' if sd is None else f'{sd:>9.4f}'} "
            f"{stats['min']:>9.4f} {stats['max']:>9.4f}"
            f"  {'' if floor is None else f'{floor:.2f}'}{mark}"
        )
    if agg["unstable_deterministic"]:
        print()
        print(
            "  WARNING: these are bit-reproducible on a fixed corpus and moved anyway: "
            + ", ".join(agg["unstable_deterministic"])
        )
        print("  The corpus or the retrieval funnel changed mid-series; do not average it.")
    print(f"{'=' * 72}\n")
    return violations


def _print_comparison(before: dict, after: dict) -> None:
    print(f"{'=' * 72}")
    print(f"  Comparison -- {before['n']} runs before, {after['n']} runs after")
    print(f"{'=' * 72}")
    print(f"  {'metric':<24} {'before':>9} {'after':>9} {'delta':>9} {'sd':>9}  verdict")
    for key, cmp in compare(before, after).items():
        sd = cmp["sd"]
        verdict = "resolved" if cmp["resolved"] else "inside noise"
        print(
            f"  {key:<24} {cmp['before']:>9.4f} {cmp['after']:>9.4f} "
            f"{cmp['delta']:>+9.4f} {'n/a' if sd is None else f'{sd:>9.4f}'}  {verdict}"
        )
    print(f"{'=' * 72}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--compare-to", dest="compare_to", help="run_group of an earlier series")
    ap.add_argument("--assert-thresholds", action="store_true", dest="assert_thresholds")
    args, passthrough = ap.parse_known_args()

    if args.runs < 2:
        print("--runs must be at least 2; one run is not a distribution", file=sys.stderr)
        return 2

    run_group = uuid.uuid4().hex[:8]
    # Each run gates itself, which keeps I-32's requested-but-uncomputed rule
    # where it is implemented. This driver gates the mean on top of that.
    forwarded = ["--dataset", args.dataset, "--assert-thresholds", *passthrough]
    codes = _execute_series(run_group, args.runs, forwarded)

    rows = _history_rows(run_group)
    if len(rows) != args.runs:
        print(
            f"\nFAILED: {len(rows)} of {args.runs} runs recorded a result "
            f"(exit codes {codes}). A series with a missing run is not a distribution.",
            file=sys.stderr,
        )
        return 1

    agrees, differing = _environment_agrees(rows)
    if not agrees:
        print(
            "\nFAILED: the runs did not measure the same system -- "
            f"{', '.join(differing)} changed mid-series. Aggregating them would "
            "report a system change as variance.",
            file=sys.stderr,
        )
        return 1

    agg = aggregate(rows)
    thresholds = thresholds_for_dataset(args.dataset)
    violations = _print_report(args.dataset, agg, thresholds)

    if args.compare_to:
        earlier = _history_rows(args.compare_to)
        if not earlier:
            print(f"no runs found for group {args.compare_to}", file=sys.stderr)
            return 1
        ok, fields = same_conditions(
            (earlier[0].get("environment") or {}), (rows[0].get("environment") or {})
        )
        if not ok:
            print(
                f"\nNOT COMPARABLE: {', '.join(fields)} differ between the series. "
                "Re-run the baseline arm in this state instead of comparing across it.",
                file=sys.stderr,
            )
            return 1
        _print_comparison(aggregate(earlier), agg)

    append_history(
        args.dataset,
        rows[-1].get("model", "no-llm"),
        {
            "runs": agg["n"],
            "run_group": run_group,
            "variance": agg["metrics"],
            **{k: v["mean"] for k, v in agg["metrics"].items()},
        },
        not violations,
        eval_kind=f"{rows[-1].get('eval_kind', 'retrieval')}-series",
        environment=(rows[0].get("environment") or {}) | {"aggregated_at": _now()},
    )
    print(f"  series recorded as run_group {run_group}")

    failed_runs = [i + 1 for i, c in enumerate(codes) if c not in (0, 1)]
    if failed_runs:
        print(f"\nFAILED: runs {failed_runs} did not complete", file=sys.stderr)
        return 1
    if violations and args.assert_thresholds:
        print("\nQUALITY GATE FAILED (on the mean, not a single run):", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    return 0


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
