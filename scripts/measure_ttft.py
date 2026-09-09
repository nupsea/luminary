#!/usr/bin/env python3
"""Measure time-to-first-token for the arm this machine is currently configured for.

Rung 0.10.0's exit gate is a *pair* of numbers — local and cloud — and this takes
one of them. It reads the figure the product itself reports in each answer's
receipt rather than timing the HTTP call from outside, so the number quoted in a
release note is the same one a user sees under their answer.

    make measure-ttft                       # 5 runs, whatever mode is configured
    make measure-ttft RUNS=9 Q="..."

**It never averages across arms.** Switching mode mid-run would otherwise produce
a single mean describing no system that exists; if the engine changes between
runs, this refuses to summarise and says why. It also refuses to report a mean
over runs that produced no token at all, because a failed answer has no latency —
`ttft_seconds` is null there, and treating null as zero would report the fastest
run the product never had.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

DEFAULT_QUESTION = "What is the main idea, and which passage supports it?"


def ask(base: str, question: str, document_ids: list[str] | None, timeout: float) -> dict:
    """One /qa call. Returns the receipt plus the wall time the caller observed."""
    body = {"question": question}
    if document_ids:
        body["document_ids"] = document_ids
        body["scope"] = "single"
    req = urllib.request.Request(
        f"{base}/qa",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    first_event_at: float | None = None
    final: dict | None = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[len("data: ") :])
            if first_event_at is None and ("token" in payload or payload.get("type") == "sources"):
                first_event_at = time.monotonic() - started
            if payload.get("done"):
                final = payload
    wall = time.monotonic() - started
    if final is None:
        return {"error": "stream ended without a done event", "wall_seconds": wall}
    receipt = final.get("receipt") or {}
    return {
        "engine": receipt.get("engine"),
        "model": receipt.get("model"),
        "ttft_seconds": receipt.get("ttft_seconds"),
        "total_seconds": receipt.get("total_seconds"),
        "passages_sent": receipt.get("passages_sent"),
        "context_budget_tokens": receipt.get("context_budget_tokens"),
        "context_budget_reason": receipt.get("context_budget_reason"),
        # What the client saw before anything rendered. Retrieval-first means the
        # source chips land here, well before the first token on the local arm.
        "first_event_seconds": round(first_event_at, 2) if first_event_at else None,
        "wall_seconds": round(wall, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:7820")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--question", default=DEFAULT_QUESTION)
    ap.add_argument("--document-id", action="append", dest="document_ids")
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args()

    try:
        with urllib.request.urlopen(f"{args.base}/health", timeout=5):
            pass
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"FAIL: no backend on {args.base} ({exc})", file=sys.stderr)
        return 1

    rows = []
    for i in range(1, args.runs + 1):
        row = ask(args.base, args.question, args.document_ids, args.timeout)
        rows.append(row)
        if "error" in row:
            print(f"  run {i}: {row['error']} after {row['wall_seconds']}s")
            continue
        print(
            f"  run {i}: engine={row['engine']:<5} ttft="
            f"{row['ttft_seconds'] if row['ttft_seconds'] is not None else 'null':>6}"
            f"  total={row['total_seconds']:>6}  first_event={row['first_event_seconds']}"
            f"  passages={row['passages_sent']}"
        )

    engines = {r.get("engine") for r in rows if r.get("engine")}
    print()
    if len(engines) > 1:
        print(f"REFUSING to summarise: the engine changed mid-run ({sorted(engines)}).")
        print("A mean across arms describes no system that exists. Run each arm separately.")
        return 2

    ttfts = [r["ttft_seconds"] for r in rows if r.get("ttft_seconds") is not None]
    if not ttfts:
        print("REFUSING to summarise: no run produced a token, so there is no latency to report.")
        return 2

    engine = engines.pop() if engines else "unknown"
    model = next((r["model"] for r in rows if r.get("model")), "unknown")
    budget = next((r.get("context_budget_reason") for r in rows if r.get("context_budget_reason")), None)
    print(f"arm            {engine} ({model})")
    print(f"runs measured  {len(ttfts)} of {args.runs}")
    print(f"ttft median    {statistics.median(ttfts):.2f}s")
    print(f"ttft range     {min(ttfts):.2f}s - {max(ttfts):.2f}s")
    if budget:
        print(f"context budget {budget}")
    if len(ttfts) < args.runs:
        print(f"NOTE: {args.runs - len(ttfts)} run(s) produced no token and are excluded, not zeroed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
