"""Follow-up retrieval eval (#322): does a follow-up question retrieve the passage it is about?

A follow-up leans on the turns before it ("why can't we compute the second one?"), so
its own wording can point at the wrong passage. Each row carries the user turns before
it and a hand-written standalone rewrite. Every arm is scoped to the row's document:

  raw         the follow-up as typed -- what search_node sees when no rewrite fires
  concat      the previous user turn prepended -- the naive fix
  standalone  the hand rewrite -- the ceiling a query rewriter can reach
  chat        (--chat) the shipped /qa path with the conversation replayed live; scores
              whether the hint reached the generator's context, not where it ranked

`standalone - raw` is the headroom a rewriter can claim on this set. Baseline only: no
floor until a change has been measured against it.

Usage:
    cd evals
    uv run python run_followup_eval.py --backend-url http://localhost:7820 \
        [--chat --model ollama/qwen3.5:4b]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.environment import capture as capture_environment  # noqa: E402
from evals.lib.loader import load_golden  # noqa: E402
from evals.lib.manifest import (  # noqa: E402
    ensure_ingested,
    load_manifest,
    require_backend,
    resolve_backend_base,
)
from evals.lib.retrieval_metrics import (  # noqa: E402
    _extract_hint_norms,
    _norm,
    arm_metrics,
    compute_hit_rate_5,
)
from evals.lib.scoring_history import append_history  # noqa: E402
from evals.run_eval import QA_REQUEST_TIMEOUT, SearchFailedError, search_chunks  # noqa: E402

DATASET = "followups"
SEARCH_ARMS = ("raw", "concat", "standalone")


def query_for(row: dict, arm: str) -> str:
    if arm == "raw":
        return row["question"]
    if arm == "concat":
        return f"{row['history'][-1]} {row['question']}"
    return row["standalone"]


def score_arm(rows: list[dict], contexts: list[list[str]], failed: list[bool]) -> dict:
    samples = [
        {**row, "contexts": ctx, "search_failed": bad}
        for row, ctx, bad in zip(rows, contexts, failed, strict=True)
    ]
    metrics = arm_metrics(samples)
    if metrics["hit_rate_5"] is not None:
        by_dep: dict[str, list[dict]] = {}
        for s in samples:
            by_dep.setdefault(s["dependency"], []).append(s)
        metrics["per_dependency"] = {
            dep: {"n": len(group), "hit_rate_5": compute_hit_rate_5(group)}
            for dep, group in sorted(by_dep.items())
        }
    return metrics


def post_qa(
    backend_url: str, question: str, doc_id: str, model: str, messages: list[dict]
) -> dict:
    """The final SSE event of one /qa turn, or {} when the call failed."""
    payload = {
        "question": question,
        "document_ids": [doc_id],
        "scope": "single",
        "model": model,
        "messages": messages,
        "include_context": True,
    }
    try:
        resp = httpx.post(f"{backend_url}/qa", json=payload, timeout=QA_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  WARNING: /qa failed: {exc}", file=sys.stderr)
        return {}
    final: dict = {}
    for line in resp.text.splitlines():
        raw = line.removeprefix("data:").strip()
        if not line.startswith("data:") or not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("done"):
            final = event
    return final


class Conversation:
    """Replays each prior user turn through /qa once, so a follow-up carries the
    answers the product actually gave rather than text the harness wrote."""

    def __init__(self, backend_url: str, model: str) -> None:
        self.backend_url = backend_url
        self.model = model
        self._answers: dict[tuple, str | None] = {}

    def messages_for(self, history: list[str], doc_id: str) -> list[dict] | None:
        messages: list[dict] = []
        for i, turn in enumerate(history):
            key = (doc_id, tuple(history[: i + 1]))
            if key not in self._answers:
                resp = post_qa(self.backend_url, turn, doc_id, self.model, messages)
                self._answers[key] = resp.get("answer") or None
            answer = self._answers[key]
            if answer is None:
                return None
            messages += [
                {"role": "user", "content": turn},
                {"role": "assistant", "content": answer},
            ]
        return messages


def run_chat_arm(backend_url: str, rows: list[dict], doc_ids: dict, model: str) -> dict:
    conversation = Conversation(backend_url, model)
    in_context = failures = 0
    for i, row in enumerate(rows, 1):
        doc_id = doc_ids[row["source_file"]]
        messages = conversation.messages_for(row["history"], doc_id)
        resp = (
            post_qa(backend_url, row["question"], doc_id, model, messages)
            if messages
            else {}
        )
        chunks = resp.get("context_chunks")
        if not resp or chunks is None:
            failures += 1
            print(f"  [{i}/{len(rows)}] FAILED   {row['id']}")
            continue
        hints = _extract_hint_norms(row)
        hit = any(h in _norm(c) for c in chunks for h in hints)
        in_context += hit
        print(f"  [{i}/{len(rows)}] {'hit ' if hit else 'miss'}     {row['id']}")
    return {
        "gold_in_context": None if failures else in_context / len(rows),
        "failures": failures,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Follow-up retrieval eval (#322).")
    ap.add_argument("--backend-url", default="http://localhost:7820")
    ap.add_argument(
        "--no-rerank", action="store_true", help="search arms without the cross-encoder"
    )
    ap.add_argument(
        "--chat", action="store_true", help="also replay conversations through /qa"
    )
    ap.add_argument(
        "--model", default=None, help="answering model for --chat; required with it"
    )
    args = ap.parse_args()
    if args.chat and not args.model:
        # An unpinned /qa outside the app resolves to the router default, not the
        # model chosen in Settings, so the arm would measure a model nobody uses.
        sys.exit("--chat needs --model")

    require_backend(args.backend_url)
    backend_url = resolve_backend_base(args.backend_url)
    rows = load_golden(DATASET)
    manifest = load_manifest()
    doc_ids = {
        src: ensure_ingested(backend_url, src, manifest)
        for src in {r["source_file"] for r in rows}
    }
    missing = [src for src, doc_id in doc_ids.items() if not doc_id]
    if missing:
        sys.exit(f"not ingested: {missing}")

    rerank = not args.no_rerank
    metrics: dict = {"arms": {}}
    for arm in SEARCH_ARMS:
        contexts, failed = [], []
        for row in rows:
            try:
                ctx = search_chunks(
                    backend_url,
                    query_for(row, arm),
                    doc_ids[row["source_file"]],
                    rerank=rerank,
                )
                contexts.append(ctx)
                failed.append(False)
            except SearchFailedError as exc:
                print(f"  WARNING: {row['id']} {arm}: {exc}", file=sys.stderr)
                contexts.append([])
                failed.append(True)
        metrics["arms"][arm] = score_arm(rows, contexts, failed)
    if args.chat:
        metrics["arms"]["chat"] = run_chat_arm(backend_url, rows, doc_ids, args.model)

    raw, ceiling = (
        metrics["arms"]["raw"]["hit_rate_5"],
        metrics["arms"]["standalone"]["hit_rate_5"],
    )
    metrics["headroom_hr5"] = None if raw is None or ceiling is None else ceiling - raw

    print("\n" + "=" * 64)
    print(f"  Follow-up eval -- {len(rows)} rows, rerank={'on' if rerank else 'off'}")
    for arm, m in metrics["arms"].items():
        if arm == "chat":
            print(
                f"  {arm:11} gold_in_context {m['gold_in_context']}  failures {m['failures']}"
            )
            continue
        print(
            f"  {arm:11} HR@5 {m['hit_rate_5']}  MRR {m['mrr']}  failures {m['search_failures']}"
        )
        for dep, d in (m.get("per_dependency") or {}).items():
            print(f"      {dep:20} n={d['n']:2}  HR@5 {d['hit_rate_5']:.4f}")
    print(f"  headroom (standalone - raw HR@5) {metrics['headroom_hr5']}")
    print("=" * 64)

    failures = sum(
        m.get("search_failures") or m.get("failures") or 0
        for m in metrics["arms"].values()
    )
    append_history(
        DATASET,
        args.model or "retrieval-only",
        metrics,
        passed=failures == 0,
        eval_kind="followup",
        environment=capture_environment(
            backend_url,
            dataset=DATASET,
            rerank=rerank,
            chat=args.chat,
            model=args.model,
        ),
    )
    if failures:
        sys.exit(f"FAIL: {failures} call(s) failed; the arms they touch are uncomputed")


if __name__ == "__main__":
    main()
