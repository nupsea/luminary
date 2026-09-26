#!/usr/bin/env python3
"""Time the flows a reader waits on, against a running Luminary, for cross-host parity.

Runs scripts/time_flows.plan.json against an EMPTY library: each document is
ingested (a file, or a URL for the web article), then Ask, flashcard generation
and a teach-back evaluation are timed once its background model work has settled.
Timing during that backlog measures where each call lands against it, not the
host. A document marked `ask_previous_while_ingesting` also times the previous
document's questions while it ingests, which is the one place contention is the
point.

Every host must serve the same model: an answer served by any other model than
--expect-model fails the run instead of being timed.

    python3 scripts/time_flows.py --base http://127.0.0.1:7820 --label m3-pro \\
        --data-dir <library> --out m3-pro.json
    python3 scripts/time_flows.py compare m3-pro.json g6-linux.json

Standard library only, so it runs on a machine with just the installed app.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPO / "scripts/time_flows.plan.json"
# The parity bar for 0.13.2: every timing within this factor of the Apple Silicon baseline.
PARITY = 1.5


class RunFailed(Exception):
    pass


def _request(
    base: str,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 900,
):
    # --base is refused unless http(s) in main().
    req = urllib.request.Request(
        base + path, data=body, method=method, headers=headers or {}
    )  # noqa: S310
    try:
        return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310
    except urllib.error.HTTPError as e:
        raise RunFailed(f"{method} {path}: HTTP {e.code} {e.read()[:300]!r}") from e


def _json(
    base: str,
    method: str,
    path: str,
    payload: object | None = None,
    timeout: float = 900,
):
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"} if body else {}
    with _request(base, method, path, body, headers, timeout) as resp:
        return json.loads(resp.read())


def _multipart(book: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{book.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
    ).encode()
    return head + book.read_bytes() + f"\r\n--{boundary}--\r\n".encode(), boundary


def check_engine(base: str, expect_model: str) -> None:
    # Cards and teach-back carry no receipt, so the settings are their only witness.
    llm = _json(base, "GET", "/settings/llm")
    chat = llm["local_chat_model"].removeprefix("ollama/")
    if llm["mode"] != "private" or chat != expect_model.removeprefix("ollama/"):
        raise RunFailed(
            f"engine is {llm['mode']} / {llm['local_chat_model']!r}; set Local (private) and "
            f"{expect_model} in Settings first"
        )


def start_ingest(base: str, doc: dict) -> str:
    if "url" in doc:
        started = _json(base, "POST", "/documents/ingest-url", {"url": doc["url"]})
    else:
        path = REPO / doc["path"]
        if not path.exists():
            raise RunFailed(
                f"{path} is missing; the plan needs every document on this host"
            )
        body, boundary = _multipart(path)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        with _request(base, "POST", "/documents/ingest", body, headers) as resp:
            started = json.loads(resp.read())
    if started["status"] == "duplicate":
        # A deduplicated upload returns at once and would time as a 0s ingest.
        raise RunFailed(
            f"the library already holds {doc['key']}; run against an empty library"
        )
    return started["document_id"]


def stage(base: str, doc_id: str) -> dict:
    status = _json(base, "GET", f"/documents/{doc_id}/status")
    if status["stage"] == "error":
        raise RunFailed(f"ingest failed: {status['error_message']}")
    return status


def wait_complete(
    base: str, doc_id: str, t0: float, limit_s: float, stages: dict
) -> None:
    while True:
        status = stage(base, doc_id)
        elapsed = time.monotonic() - t0
        stages.setdefault(status["stage"], round(elapsed, 1))
        if status["done"]:
            return
        if elapsed > limit_s:
            raise RunFailed(
                f"ingest not complete after {limit_s:.0f}s; stages {stages}"
            )
        time.sleep(2)


def admission(base: str) -> dict:
    return _json(base, "GET", "/monitoring/metrics")["llm_admission"]


def settle(base: str, t0: float, quiet_s: float, limit_s: float) -> float:
    """Seconds from upload until no background model call has run or waited for quiet_s.

    "complete" is not idle: section summaries and tagging run for minutes after it.
    """
    quiet_since = None
    while True:
        now = time.monotonic()
        state = admission(base)
        if state["background_inflight"] or state["background_waiting"]:
            quiet_since = None
        elif quiet_since is None:
            quiet_since = now
        elif now - quiet_since >= quiet_s:
            return round(quiet_since - t0, 1)
        if now - t0 > limit_s:
            raise RunFailed(
                f"background work still running {limit_s:.0f}s after upload"
            )
        time.sleep(2)


def check_uncontended(before: dict, after: dict) -> None:
    forced = after["forced_admissions"] - before["forced_admissions"]
    if forced:
        # The starvation guard pushed background calls into a timed flow.
        raise RunFailed(f"{forced} background call(s) forced into the timed flows")


# The app's own single worker plus the model runner sit near 1 load unit per core
# while a timed flow runs; run 6's article measured a machine at ~17 per core, where
# every timing was the load and none was the host. Above this the report is the box,
# not the app, so compare() refuses it rather than passing it as a result.
CONTENDED_LOAD_PER_CORE = 4.0


def load_per_core() -> float | None:
    """1-minute load average over CPU count, or None where the OS has no load average."""
    try:
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except (OSError, AttributeError):
        return None


def ask(base: str, doc_id: str, question: str, expect_model: str) -> dict:
    payload = {"question": question, "document_ids": [doc_id], "scope": "single"}
    t0 = time.monotonic()
    first_token = None
    final = None
    with _request(
        base,
        "POST",
        "/qa",
        json.dumps(payload).encode(),
        {"Content-Type": "application/json"},
    ) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event.get("type") == "error" or (
                "error" in event and "token" not in event
            ):
                raise RunFailed(f"/qa error for {question!r}: {event}")
            if "token" in event and first_token is None:
                first_token = time.monotonic() - t0
            if event.get("done"):
                final = event
    total = time.monotonic() - t0
    receipt = (final or {}).get("receipt") or {}
    served = receipt.get("model")
    if served != expect_model:
        raise RunFailed(f"answer served by {served!r}, not {expect_model!r}")
    if first_token is None:
        raise RunFailed(f"/qa streamed no answer for {question!r}")
    return {
        "question": question,
        "ttft_s": round(first_token, 2),
        "total_s": round(total, 2),
        "not_found": bool(final.get("not_found")),
    }


def flashcards(
    base: str, doc_id: str, count: int, runs: int
) -> tuple[list[dict], list[dict]]:
    """Time generation `runs` times. Bimodal by ~2x: a rejected card triggers one refill
    call, so a single timing is not a host number. Every run is kept, none averaged."""
    samples: list[dict] = []
    first: list[dict] = []
    for _ in range(runs):
        t0 = time.monotonic()
        cards = _json(
            base,
            "POST",
            "/flashcards/generate",
            {"document_id": doc_id, "count": count},
        )
        if not cards:
            # Zero cards is a failed generation, not a fast one.
            raise RunFailed("flashcard generation returned no cards")
        samples.append(
            {"seconds": round(time.monotonic() - t0, 2), "delivered": len(cards)}
        )
        first = first or cards
    return first, samples


def teachback(base: str, card: dict) -> float:
    # Timed only: the explanation is the card's own answer, so the score means nothing.
    t0 = time.monotonic()
    _json(
        base,
        "POST",
        "/study/teachback",
        {"flashcard_id": card["id"], "user_explanation": card["answer"]},
    )
    return round(time.monotonic() - t0, 2)


def store_sizes(data_dir: Path | None) -> dict[str, float] | None:
    if data_dir is None:
        return None

    def mb(*patterns: str) -> float:
        files = [p for pat in patterns for p in data_dir.glob(pat) if p.is_file()]
        return round(sum(f.stat().st_size for f in files) / 1_048_576, 1)

    return {
        "sqlite_mb": mb("luminary.db*"),
        "vectors_mb": mb("vectors/**/*"),
        "graph_mb": mb("graph.kuzu*", "graph.kuzu/**/*"),
        "raw_mb": mb("raw/**/*"),
        "images_mb": mb("images/**/*"),
    }


def median_of(asks: list[dict], key: str) -> float:
    return statistics.median(a[key] for a in asks)


def run_plan(args: argparse.Namespace, plan: dict, report: dict) -> None:
    check_engine(args.base, args.expect_model)
    previous: tuple[str, dict] | None = None
    for doc in plan["documents"]:
        entry: dict = {}
        report["documents"][doc["key"]] = entry
        t0 = time.monotonic()
        doc_id = start_ingest(args.base, doc)
        stages: dict[str, float] = {}
        if doc.get("ask_previous_while_ingesting") and previous:
            prev_id, prev_doc = previous
            during = []
            for q in prev_doc["questions"]:
                at = stage(args.base, doc_id)["stage"]
                result = ask(args.base, prev_id, q, args.expect_model)
                result["ingest_stage_at_ask"] = at
                during.append(result)
            # A question asked after the ingest finished measured nothing about contention.
            entry["ask_previous_while_ingesting"] = during
            if all(a["ingest_stage_at_ask"] == "complete" for a in during):
                raise RunFailed(
                    f"{doc['key']} finished ingesting before any question was asked"
                )
        wait_complete(args.base, doc_id, t0, args.ingest_limit, stages)
        entry["ingest_stages_s"] = stages
        entry["settled_s"] = settle(args.base, t0, args.quiet, args.ingest_limit)
        entry["stores_after"] = store_sizes(args.data_dir)

        before = admission(args.base)
        loads = [load_per_core()]
        entry["ask"] = [
            ask(args.base, doc_id, q, args.expect_model) for q in doc["questions"]
        ]
        if doc.get("cards"):
            cards, entry["flashcards"] = flashcards(
                args.base, doc_id, args.cards, args.card_runs
            )
            entry["teachback_s"] = teachback(args.base, cards[0])
        loads.append(load_per_core())
        entry["load_per_core"] = [round(x, 2) for x in loads if x is not None] or None
        check_uncontended(before, admission(args.base))
        previous = (doc_id, doc)


def metrics(report: dict) -> dict[str, float]:
    """The comparable numbers of one report, flattened: `<doc>.<metric>` -> seconds."""
    out: dict[str, float] = {}
    for key, entry in report["documents"].items():
        out[f"{key}.ingest_complete_s"] = entry["ingest_stages_s"]["complete"]
        out[f"{key}.settled_s"] = entry["settled_s"]
        out[f"{key}.ask_ttft_median_s"] = median_of(entry["ask"], "ttft_s")
        out[f"{key}.ask_total_median_s"] = median_of(entry["ask"], "total_s")
        if "ask_previous_while_ingesting" in entry:
            during = entry["ask_previous_while_ingesting"]
            out[f"{key}.ask_during_ingest_ttft_median_s"] = median_of(during, "ttft_s")
            out[f"{key}.ask_during_ingest_total_median_s"] = median_of(
                during, "total_s"
            )
        if "flashcards" in entry:
            # Both modes, never their mean: the fast/slow split is a real per-call fork.
            secs = [s["seconds"] for s in entry["flashcards"]]
            out[f"{key}.flashcards_fast_s"] = min(secs)
            out[f"{key}.flashcards_slow_s"] = max(secs)
        if "teachback_s" in entry:
            out[f"{key}.teachback_s"] = entry["teachback_s"]
        stores = entry.get("stores_after") or {}
        for name in ("sqlite_mb", "vectors_mb"):
            # Same model and same documents should build near-identical stores; the
            # small ones (graph, raw, images) round to noise and would divide by zero.
            if stores.get(name):
                out[f"{key}.{name}"] = stores[name]
    return out


def contended(report: dict) -> float | None:
    """The worst per-core load seen during any timed section, if the OS reported it."""
    seen = [
        x for e in report["documents"].values() for x in (e.get("load_per_core") or [])
    ]
    return max(seen) if seen else None


def compare(base_path: Path, host_path: Path) -> int:
    base = json.loads(base_path.read_text())
    host = json.loads(host_path.read_text())
    if base.get("failed") or host.get("failed"):
        print("a report failed; nothing to compare", file=sys.stderr)
        return 1
    for report in (base, host):
        load = contended(report)
        if load is not None and load >= CONTENDED_LOAD_PER_CORE:
            print(
                f"{report['label']} ran at {load:.1f} load/core "
                f"(>= {CONTENDED_LOAD_PER_CORE}); it measured the machine, not the app. "
                "Rerun it on a quiet host.",
                file=sys.stderr,
            )
            return 1
    b, h = metrics(base), metrics(host)
    worst = 0.0
    print(f"{'metric':45} {base['label']:>12} {host['label']:>12}  ratio")
    for name in b:
        if name not in h:
            print(f"{name:45} {b[name]:>12} {'missing':>12}")
            worst = float("inf")
            continue
        ratio = h[name] / b[name] if b[name] else float("inf")
        worst = max(worst, ratio)
        flag = "" if ratio <= PARITY else "  OVER"
        print(f"{name:45} {b[name]:>12} {h[name]:>12}  {ratio:5.2f}{flag}")
    print(f"worst ratio {worst:.2f} against a bar of {PARITY}")
    return 0 if worst <= PARITY else 2


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "compare":
        return compare(Path(sys.argv[2]), Path(sys.argv[3]))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:7820")
    ap.add_argument(
        "--label", required=True, help="host name for the report, e.g. m3-pro"
    )
    ap.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    ap.add_argument(
        "--data-dir", type=Path, help="the library directory, for store sizes"
    )
    ap.add_argument("--expect-model", default="ollama/qwen3.5:4b")
    ap.add_argument("--cards", type=int, default=5)
    ap.add_argument(
        "--card-runs", type=int, default=3, help="flashcard timings per doc (bimodal)"
    )
    ap.add_argument(
        "--ingest-limit", type=float, default=3600, help="upload to settled, seconds"
    )
    ap.add_argument(
        "--quiet", type=float, default=30, help="idle seconds that count as settled"
    )
    ap.add_argument("--out", type=Path, help="write the report as JSON")
    args = ap.parse_args()
    if not args.base.startswith(("http://", "https://")):
        ap.error("--base must be an http(s) URL")

    report: dict = {
        "label": args.label,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "model": args.expect_model,
        "documents": {},
    }
    try:
        run_plan(args, json.loads(args.plan.read_text()), report)
    except RunFailed as e:
        report["failed"] = str(e)
        print(f"FAILED: {e}", file=sys.stderr)
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 1 if "failed" in report else 0


if __name__ == "__main__":
    sys.exit(main())
