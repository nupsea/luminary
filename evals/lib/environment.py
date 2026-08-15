"""Capture what produced a run, so two numbers can be compared or refused.

Every field comes from the running backend rather than this process: the eval
venv's `app.config` would report the configured default, while a model chosen
in Settings is what the run actually used. The git sha and the run's own
arguments are the two exceptions -- the backend cannot know either.

A capture that fails records the reason instead of a blank. An environment that
could not be read is a fact about the run, and silently omitting it would leave
the row indistinguishable from one taken before this existed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _git_sha() -> str | None:
    try:
        out = subprocess.run(  # noqa: S603 -- fixed argv, no user input
            ["/usr/bin/git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha or None


def capture(backend_url: str, **run_args: Any) -> dict[str, Any]:
    """The environment block to store beside a run's metrics.

    *run_args* are the knobs the runner itself chose -- rerank on/off, scope,
    judge model, run-group -- which the backend has no way to report.
    """
    env: dict[str, Any] = {"eval_git_sha": _git_sha(), **run_args}
    try:
        resp = httpx.get(f"{backend_url.rstrip('/')}/evals/environment", timeout=15.0)
        resp.raise_for_status()
        env |= resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        env["capture_error"] = f"{type(exc).__name__}: {exc}"
    return env


def output_stats(backend_url: str) -> dict[str, Any] | None:
    """Repair counters as they stand right now, or None when unreadable.

    Snapshot before a run and again after: the difference is what this run's
    completions needed before they could be used.
    """
    try:
        resp = httpx.get(f"{backend_url.rstrip('/')}/evals/output-stats", timeout=15.0)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def stats_delta(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Counter movement between two snapshots, in the snapshot's own shape."""
    if not before or not after:
        return None
    before_counts = before.get("counts", {})
    after_counts = after.get("counts", {})
    counts = {
        key: after_counts.get(key, 0) - before_counts.get(key, 0)
        for key in set(before_counts) | set(after_counts)
        if after_counts.get(key, 0) - before_counts.get(key, 0)
    }
    parses = counts.get("parses", 0)
    return {
        "counts": counts,
        "first_pass_rate": (counts.get("parses_first_pass", 0) / parses) if parses else None,
    }


def self_judging(env: dict[str, Any]) -> str | None:
    """The model id when one model both answered and graded, else None.

    A judge scoring its own output is not a neutral rater: it agrees with its own
    phrasing, its own citation choices and its own refusals. The shipped answerer
    and the judge are different models, so this is a property of a machine's
    configuration rather than of the product -- which is exactly why it has to be
    read from the run instead of assumed.
    """
    judge = env.get("judge_model")
    if not judge:
        return None
    answering = {env.get("chat_model"), env.get("generation_model")}
    return judge if judge in answering else None


def same_conditions(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, list[str]]:
    """(comparable, differing fields) for two environment blocks.

    Retrieval is bit-reproducible only within one corpus and one funnel: an
    embedder, a reranker, or a library that grew between two runs makes the
    later number a different measurement rather than a newer one. Model ids are
    included because a generation metric moves with them; `eval_git_sha` is not,
    since a commit that touches neither pipeline nor corpus changes nothing.
    """
    keys = (
        "embedding_model",
        "embedding_dim",
        "chunk_vector_table",
        "rerank_model",
        "rerank_depth",
        "rerank_blend_alpha",
        "query_spell_correct",
        "chat_model",
        "generation_model",
        "library",
    )
    differing = [k for k in keys if a.get(k) != b.get(k)]
    return not differing, differing
