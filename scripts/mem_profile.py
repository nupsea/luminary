#!/usr/bin/env python3
"""Footprint and interactive-latency baseline for one ingest.

Answers two questions that nothing in the repo currently measures:

  1. What is resident, per ingestion stage, and what is the peak.
  2. How long does an Ask take to produce its first token while that ingest runs.

Both are sampled per stage rather than at steady state, because the peak and the
stall are stage-local: the vision runner loads during enrichment, and deferred
section summaries only start once the document reports `complete`.

Resident memory is reported two ways on purpose. `rss` is what the kernel says
each process holds; `ollama_reported` is what Ollama says its loaded models
weigh. On unified memory these disagree -- weights mapped by the runner are not
always charged to its RSS -- and a number that only appears one way is a
measurement artifact, not a finding.

Usage::

    make mem-profile FILE=/path/to/big.pdf
    uv run python ../scripts/mem_profile.py --ingest /path/to/big.pdf
    uv run python ../scripts/mem_profile.py --idle 60     # boot baseline, no ingest
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psutil

MB = 1024 * 1024

DEFAULT_BACKEND = "http://127.0.0.1:7820"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"

# Ollama's port is ephemeral under the bundled app, so the URL is asked for
# rather than assumed; this is only the dev default.

_PROC_ROLES = {
    "backend": lambda name, cmd: "uvicorn" in cmd or "app.main" in cmd,
    "ollama": lambda name, cmd: name == "ollama" or "ollama" in name,
    "desktop": lambda name, cmd: "luminary" in name,
}


def _classify(proc: psutil.Process) -> str | None:
    try:
        name = (proc.name() or "").lower()
        cmd = " ".join(proc.cmdline()).lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    for role, match in _PROC_ROLES.items():
        if match(name, cmd):
            return role
    return None


def _find_procs() -> dict[str, list[psutil.Process]]:
    found: dict[str, list[psutil.Process]] = {"backend": [], "ollama": [], "desktop": []}
    for proc in psutil.process_iter(["pid", "name"]):
        role = _classify(proc)
        if role:
            found[role].append(proc)
    return found


def _rss(procs: list[psutil.Process]) -> int:
    total = 0
    for p in procs:
        try:
            total += p.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


async def _ollama_models(client: httpx.AsyncClient, ollama_url: str) -> list[dict[str, Any]]:
    """Loaded models and their reported sizes, or [] when Ollama is unreachable."""
    try:
        resp = await client.get(f"{ollama_url}/api/ps", timeout=5.0)
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.InvalidURL):
        return []
    return [
        {"name": m.get("name", "?"), "size": m.get("size", 0), "size_vram": m.get("size_vram", 0)}
        for m in resp.json().get("models", [])
    ]


async def _stage(client: httpx.AsyncClient, backend: str, doc_id: str | None) -> str | None:
    if doc_id is None:
        return None
    try:
        resp = await client.get(f"{backend}/documents/{doc_id}/status", timeout=10.0)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return resp.json().get("stage")


async def _sample(
    client: httpx.AsyncClient,
    backend: str,
    ollama_url: str,
    procs: dict[str, list[psutil.Process]],
    doc_id: str | None,
    t0: float,
) -> dict[str, Any]:
    models = await _ollama_models(client, ollama_url)
    vm = psutil.virtual_memory()
    return {
        "t": round(time.monotonic() - t0, 2),
        "stage": await _stage(client, backend, doc_id),
        "rss": {role: _rss(ps) for role, ps in procs.items()},
        "ollama_reported": sum(m["size"] for m in models),
        "ollama_models": [m["name"] for m in models],
        "loaded_count": len(models),
        "available": vm.available,
        "used": vm.total - vm.available,
    }


async def _probe_ttft(
    client: httpx.AsyncClient, backend: str, question: str, t0: float
) -> dict[str, Any]:
    """Time an Ask to its first token, as a user experiences it.

    Time-to-first-byte and time-to-first-token are both recorded: an early
    non-token event (a notice, a transparency payload) would otherwise be
    mistaken for the answer starting.
    """
    started = time.monotonic()
    ttfb: float | None = None
    ttft: float | None = None
    error: str | None = None
    try:
        async with client.stream(
            "POST",
            f"{backend}/qa",
            json={"question": question, "scope": "library"},
            timeout=180.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if ttfb is None:
                    ttfb = time.monotonic() - started
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if payload.get("token"):
                    ttft = time.monotonic() - started
                    break
                if payload.get("done"):
                    break
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        error = f"{type(exc).__name__}: {exc}"

    return {
        "at": round(started - t0, 2),
        "ttfb_s": round(ttfb, 3) if ttfb is not None else None,
        "ttft_s": round(ttft, 3) if ttft is not None else None,
        "error": error,
    }


async def _ingest(client: httpx.AsyncClient, backend: str, path: Path) -> str:
    with path.open("rb") as fh:
        resp = await client.post(
            f"{backend}/documents/ingest",
            files={"file": (path.name, fh, "application/octet-stream")},
            data={"content_type": "technical"},
            timeout=600.0,
        )
    resp.raise_for_status()
    body = resp.json()
    doc_id = body.get("document_id") or body.get("id")
    if not doc_id:
        raise SystemExit(f"ingest returned no document id: {body}")
    return str(doc_id)


def _summarise(samples: list[dict], probes: list[dict], meta: dict) -> dict:
    """Peak per stage, and the worst interactive latency observed."""
    by_stage: dict[str, int] = {}
    for s in samples:
        stage = s["stage"] or "unknown"
        total = sum(s["rss"].values())
        by_stage[stage] = max(by_stage.get(stage, 0), total)

    peak = max((sum(s["rss"].values()) for s in samples), default=0)
    peak_reported = max((s["ollama_reported"] for s in samples), default=0)
    max_loaded = max((s["loaded_count"] for s in samples), default=0)
    ttfts = [p["ttft_s"] for p in probes if p["ttft_s"] is not None]

    return {
        **meta,
        "peak_rss_mb": round(peak / MB, 1),
        "peak_ollama_reported_mb": round(peak_reported / MB, 1),
        "max_models_loaded": max_loaded,
        "peak_by_stage_mb": {k: round(v / MB, 1) for k, v in by_stage.items()},
        "ttft_worst_s": max(ttfts) if ttfts else None,
        "ttft_best_s": min(ttfts) if ttfts else None,
        "probe_failures": sum(1 for p in probes if p["error"]),
        "samples": len(samples),
    }


def _print_report(summary: dict, samples: list[dict]) -> None:
    print()
    print(f"  peak resident (RSS)      {summary['peak_rss_mb']:>10,.1f} MB")
    print(f"  peak Ollama reported     {summary['peak_ollama_reported_mb']:>10,.1f} MB")
    print(f"  max models loaded        {summary['max_models_loaded']:>10}")
    if summary["ttft_worst_s"] is not None:
        print(f"  Ask time-to-first-token  {summary['ttft_best_s']:>10.2f} s best")
        print(f"                           {summary['ttft_worst_s']:>10.2f} s worst")
    if summary["probe_failures"]:
        print(f"  probe failures           {summary['probe_failures']:>10}")
    print()
    print("  peak by stage")
    for stage, mb in summary["peak_by_stage_mb"].items():
        print(f"    {stage:<24} {mb:>10,.1f} MB")
    if samples:
        last = samples[-1]
        print()
        print("  final breakdown")
        for role, rss in last["rss"].items():
            if rss:
                print(f"    {role:<24} {rss / MB:>10,.1f} MB")
        if last["ollama_models"]:
            print(f"    loaded: {', '.join(last['ollama_models'])}")
    print()


async def run(args: argparse.Namespace) -> int:
    backend = args.backend.rstrip("/")
    ollama_url = args.ollama.rstrip("/")

    async with httpx.AsyncClient() as client:
        try:
            (await client.get(f"{backend}/health", timeout=5.0)).raise_for_status()
        except httpx.HTTPError as exc:
            print(f"backend not reachable at {backend}: {exc}")
            return 1

        procs = _find_procs()
        if not procs["backend"]:
            print("warning: no backend process matched; RSS will under-report")

        t0 = time.monotonic()
        samples: list[dict] = []
        probes: list[dict] = []
        doc_id: str | None = None
        ingest_task: asyncio.Task | None = None

        if args.ingest:
            path = Path(args.ingest).expanduser()
            if not path.is_file():
                print(f"no such file: {path}")
                return 1
            print(f"ingesting {path.name} ...")
            ingest_task = asyncio.create_task(_ingest(client, backend, path))

        probe_offsets = sorted(args.probe_at)
        deadline = t0 + args.idle if args.idle else None
        settle_until: float | None = None

        while True:
            now = time.monotonic()

            if ingest_task is not None and ingest_task.done() and doc_id is None:
                doc_id = ingest_task.result()
                print(f"document {doc_id}")

            samples.append(await _sample(client, backend, ollama_url, procs, doc_id, t0))

            while probe_offsets and (now - t0) >= probe_offsets[0]:
                probe_offsets.pop(0)
                probe = await _probe_ttft(client, backend, args.question, t0)
                probes.append(probe)
                shown = probe["ttft_s"] if probe["ttft_s"] is not None else probe["error"]
                print(f"  probe at {probe['at']:>6.1f}s -> first token {shown}")

            stage = samples[-1]["stage"]
            if stage == "complete" and settle_until is None:
                # Deferred summaries and enrichment start here, so the interesting
                # window is after `complete`, not before it.
                settle_until = now + args.settle
                print(f"stage complete at {samples[-1]['t']}s; sampling {args.settle}s more")
            if stage == "error":
                print("ingestion reported an error; stopping")
                break
            if settle_until is not None and now >= settle_until and not probe_offsets:
                break
            if deadline is not None and now >= deadline:
                break
            if ingest_task is None and deadline is None and not probe_offsets:
                break
            if (now - t0) >= args.max_duration:
                # An ingest that never reaches `complete` must not leave the
                # profiler sampling forever; the partial run is still usable.
                print(f"max duration {args.max_duration}s reached; stopping")
                break

            await asyncio.sleep(args.interval)

        if ingest_task is not None and not ingest_task.done():
            ingest_task.cancel()

    meta = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "host": platform.node(),
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "total_ram_mb": round(psutil.virtual_memory().total / MB, 1),
        "source": Path(args.ingest).name if args.ingest else None,
    }
    summary = _summarise(samples, probes, meta)

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for s in samples:
            fh.write(json.dumps({"kind": "sample", **s}) + "\n")
        for p in probes:
            fh.write(json.dumps({"kind": "probe", **p}) + "\n")
        fh.write(json.dumps({"kind": "summary", **summary}) + "\n")

    _print_report(summary, samples)
    print(f"  raw samples -> {out}")

    if args.summary:
        summary_path = Path(args.summary).expanduser()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("a") as fh:
            fh.write(json.dumps(summary) + "\n")
        print(f"  summary appended -> {summary_path}")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", default=DEFAULT_BACKEND)
    ap.add_argument("--ollama", default=DEFAULT_OLLAMA, help="ephemeral under the bundled app")
    ap.add_argument("--ingest", help="file to ingest while sampling")
    ap.add_argument("--idle", type=float, default=0.0, help="sample N seconds with no ingest")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument(
        "--settle",
        type=float,
        default=120.0,
        help="seconds to keep sampling after stage=complete; deferred work runs here",
    )
    ap.add_argument(
        "--probe-at",
        type=lambda v: [float(x) for x in v.split(",") if x.strip()],
        default=[15.0, 45.0, 90.0, 180.0],
        help="seconds after start to time an Ask (comma-separated)",
    )
    ap.add_argument("--question", default="What is this document about?")
    ap.add_argument("--max-duration", type=float, default=3600.0)
    ap.add_argument("--out", default=".luminary/mem_profile/latest.jsonl")
    ap.add_argument("--summary", help="append the one-line summary to this file")
    args = ap.parse_args()

    if not args.ingest and not args.idle:
        args.idle = 30.0
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
