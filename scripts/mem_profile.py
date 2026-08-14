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
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import psutil

MB = 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parent.parent


def _repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


DEFAULT_BACKEND = "http://127.0.0.1:7820"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"

# Ollama's port is ephemeral under the bundled app, so the URL is asked for
# rather than assumed; this is only the dev default.


def _pid_on_port(url: str) -> int | None:
    """PID listening on this URL's port."""
    port = urlparse(url).port
    if port is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603 -- fixed argv, port comes from urlparse
            ["/usr/sbin/lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    pids = [int(p) for p in out.stdout.split() if p.strip().isdigit()]
    return pids[0] if pids else None


def _tree(pid: int | None) -> list[psutil.Process]:
    if pid is None:
        return []
    try:
        proc = psutil.Process(pid)
        return [proc, *proc.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def _find_procs(backend: str, ollama_url: str) -> dict[str, list[psutil.Process]]:
    """Resolve each role from the port it serves, then take its whole tree.

    Matching on process name is wrong on any machine that runs more than one
    Luminary, which is the normal state during development: the bundled app and
    a dev backend both answer to `uvicorn`, and both Ollamas answer to `ollama`,
    so a name match sums two installs into one figure. It also misses what
    holds the memory -- uvicorn's `--reload` parent binds the socket while its
    child imports torch, and Ollama's weights live in `ollama runner` children,
    not in `ollama serve`. The listening PID plus its descendants is the only
    grouping that is both unambiguous and complete.
    """
    found = {
        "backend": _tree(_pid_on_port(backend)),
        "ollama": _tree(_pid_on_port(ollama_url)),
        "desktop": [],
    }
    backend_pids = {p.pid for p in found["backend"]}
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.name() or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "luminary" in name and proc.pid not in backend_pids:
            found["desktop"].append(proc)
    return found


def _rss(procs: list[psutil.Process]) -> int:
    """Resident bytes for these processes and any children they have spawned.

    Re-walked on every sample, never cached: Ollama's runner is a child created
    when a model loads, so a tree resolved at startup contains none of the
    weights and reports a server holding ~70MB while `/api/ps` reports ~10GB.
    """
    seen: set[int] = set()
    total = 0
    for proc in procs:
        try:
            for p in [proc, *proc.children(recursive=True)]:
                if p.pid in seen:
                    continue
                seen.add(p.pid)
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
    client: httpx.AsyncClient, backend: str, question: str, t0: float, doc_id: str | None
) -> dict[str, Any]:
    """Time an Ask to its first token, as a user experiences it.

    Time-to-first-byte and time-to-first-token are both recorded: an early
    non-token event (a notice, a transparency payload) would otherwise be
    mistaken for the answer starting.

    `not_found` is recorded because that path never reaches generation. Its
    decline is still streamed as tokens, so it produces a fast, real-looking
    TTFT that measures retrieval alone -- the one number this probe must not
    report as latency under load.

    Scope defaults to the whole library, which is what a user asks while an
    upload runs. Scoping to the document being ingested measures something
    else: until embedding finishes it answers `no_context` immediately without
    calling the model at all, so it reports readiness rather than latency.
    """
    payload_body: dict[str, Any] = {"question": question}
    if doc_id:
        payload_body |= {"scope": "single", "document_ids": [doc_id]}
    else:
        payload_body["scope"] = "all"

    started = time.monotonic()
    ttfb: float | None = None
    ttft: float | None = None
    declined = False
    no_context = False
    saw_done = False
    last_event: list[str] = []
    error: str | None = None
    try:
        async with client.stream("POST", f"{backend}/qa", json=payload_body, timeout=180.0) as resp:
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
                if payload.get("not_found"):
                    declined = True
                if payload.get("error") == "no_context":
                    no_context = True
                if payload.get("token") and ttft is None:
                    ttft = time.monotonic() - started
                if not payload.get("token"):
                    last_event = sorted(payload)
                if payload.get("done"):
                    saw_done = True
                    break
                if ttft is not None and not declined:
                    break
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        error = f"{type(exc).__name__}: {exc}"

    if error is None and ttft is None:
        # `no_context` is not a slow answer, it is no answer: retrieval had
        # nothing, so the LLM was never called and there is no latency to
        # report. A document mid-ingest answers this way to every question
        # scoped to it, which is a readiness measurement, not a TTFT one.
        if no_context:
            error = "no_context: nothing retrievable yet"
        elif not saw_done:
            # The stream closed with neither an answer nor a done event: the
            # user gets an empty response and no error. Recorded as its own
            # outcome so it cannot be read as a slow answer.
            error = f"stream ended without done, last event {last_event or 'none'}"
        else:
            error = "no token emitted"

    return {
        "at": round(started - t0, 2),
        "ttfb_s": round(ttfb, 3) if ttfb is not None else None,
        "ttft_s": round(ttft, 3) if ttft is not None else None,
        "declined": declined,
        "no_context": no_context,
        "saw_done": saw_done,
        "last_event": last_event,
        "scope": "single" if doc_id else "all",
        "error": error,
    }


async def _ingest(client: httpx.AsyncClient, backend: str, path: Path) -> tuple[str, bool]:
    """Start an ingest. Returns (document_id, dedup_hit).

    `/documents/ingest` deduplicates on file hash and answers `status:
    processing` either way, so a re-run on an already-ingested file starts
    nothing and profiles an idle backend under an ingest's name. A fresh
    ingest cannot be `complete` within milliseconds of the POST, so the stage
    read immediately after it is what separates the two.
    """
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
    return str(doc_id), await _stage(client, backend, str(doc_id)) == "complete"


async def _library(client: httpx.AsyncClient, backend: str) -> dict[str, int | None]:
    """Documents and chunks currently indexed.

    A footprint or latency number taken in one library state is not comparable
    to one taken in another, and the corpus grows by running this tool.
    """
    docs = 0
    chunks = 0
    page = 1
    try:
        while True:
            resp = await client.get(
                f"{backend}/documents", params={"page": page, "page_size": 100}, timeout=15.0
            )
            resp.raise_for_status()
            body = resp.json()
            items = body.get("items", [])
            chunks += sum(i.get("chunk_count") or 0 for i in items)
            docs = body.get("total") or docs + len(items)
            if len(items) < 100 or page * 100 >= docs:
                break
            page += 1
    except httpx.HTTPError:
        return {"documents": None, "chunks": None}
    return {"documents": docs, "chunks": chunks}


def _ollama_cap(procs: dict[str, list[psutil.Process]]) -> str | None:
    """`OLLAMA_MAX_LOADED_MODELS` as the running server actually has it.

    The bundle sets it in `spawn_ollama`; a dev Ollama started by hand may not
    have it at all, and the two hosts are different regimes. Recording the
    value is what makes a peak from one comparable to a peak from the other.
    """
    for proc in procs.get("ollama", []):
        try:
            env = proc.environ()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
        if "OLLAMA_MAX_LOADED_MODELS" in env:
            return env["OLLAMA_MAX_LOADED_MODELS"]
    return None


def _summarise(samples: list[dict], probes: list[dict], meta: dict) -> dict:
    """Peak per stage, and the worst interactive latency observed."""

    def _under_test(sample: dict) -> int:
        """The server being profiled: the backend on --backend, plus its Ollama.

        `desktop` is excluded. On a dev machine it is usually a *different*
        install -- the bundled app running beside the repo backend -- and
        summing the two reports one system's peak as another's. Profiling the
        bundled app instead means pointing --backend at its port, which puts
        its Python in the backend role and leaves only the Tauri shell here.
        """
        return sample["rss"]["backend"] + sample["rss"]["ollama"]

    by_stage: dict[str, int] = {}
    for s in samples:
        stage = s["stage"] or "unknown"
        by_stage[stage] = max(by_stage.get(stage, 0), _under_test(s))

    peak = max((_under_test(s) for s in samples), default=0)
    peak_backend = max((s["rss"]["backend"] for s in samples), default=0)
    peak_desktop = max((s["rss"]["desktop"] for s in samples), default=0)
    peak_reported = max((s["ollama_reported"] for s in samples), default=0)
    max_loaded = max((s["loaded_count"] for s in samples), default=0)
    ttfts = [p["ttft_s"] for p in probes if p["ttft_s"] is not None and not p.get("declined")]

    return {
        # Bumped when a field changes meaning. Schema 1 summed a second
        # Luminary install into peak_rss_mb; rows without this key predate the
        # fix and are not comparable to rows carrying it.
        "schema": 2,
        **meta,
        "peak_rss_mb": round(peak / MB, 1),
        "peak_backend_mb": round(peak_backend / MB, 1),
        "peak_desktop_mb": round(peak_desktop / MB, 1),
        "peak_ollama_reported_mb": round(peak_reported / MB, 1),
        "max_models_loaded": max_loaded,
        "peak_by_stage_mb": {k: round(v / MB, 1) for k, v in by_stage.items()},
        "ttft_worst_s": max(ttfts) if ttfts else None,
        "ttft_best_s": min(ttfts) if ttfts else None,
        "probes_run": len(ttfts),
        "probes_skipped": sum(1 for p in probes if (p["error"] or "").startswith("skipped")),
        "probes_declined": sum(1 for p in probes if p.get("declined")),
        "probes_no_context": sum(1 for p in probes if p.get("no_context")),
        "probe_failures": sum(
            1 for p in probes if p["error"] and not p["error"].startswith("skipped")
        ),
        "samples": len(samples),
    }


def _print_report(summary: dict, samples: list[dict]) -> None:
    print()
    lib = summary.get("library_after") or {}
    print(f"  host                     {summary['total_ram_mb'] / 1024:>10,.1f} GB RAM")
    print(f"  OLLAMA_MAX_LOADED_MODELS {summary.get('ollama_max_loaded') or 'unset'!s:>10}")
    print(
        f"  library                  {lib.get('documents')!s:>10} docs, {lib.get('chunks')} chunks"
    )
    print(f"  peak resident (RSS)      {summary['peak_rss_mb']:>10,.1f} MB  backend + ollama")
    print(f"    of which backend       {summary['peak_backend_mb']:>10,.1f} MB")
    print(f"  other Luminary install   {summary['peak_desktop_mb']:>10,.1f} MB  not counted above")
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
            health = await client.get(f"{backend}/health", timeout=5.0)
            health.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"backend not reachable at {backend}: {exc}")
            return 1
        backend_version = health.json().get("version")

        procs = _find_procs(backend, ollama_url)
        if not procs["backend"]:
            print(f"warning: nothing is listening on {backend}'s port; RSS will under-report")
        if not procs["ollama"]:
            print(f"warning: no Ollama process found at {ollama_url}; model RSS is missing")

        library_before = await _library(client, backend)

        t0 = time.monotonic()
        samples: list[dict] = []
        probes: list[dict] = []
        # Written as they are taken: a long ingest is exactly the run worth
        # profiling and exactly the one an interruption would otherwise lose.
        raw_path = _repo_path(args.out)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw = raw_path.open("w", buffering=1)
        doc_id: str | None = None
        dedup_hit = False
        ingest_error: str | None = None
        ingest_task: asyncio.Task | None = None

        if args.ingest:
            path = Path(args.ingest).expanduser()
            if not path.is_file():
                print(f"no such file: {path}")
                return 1
            print(f"ingesting {path.name} ...")
            ingest_task = asyncio.create_task(_ingest(client, backend, path))

        probe_offsets = sorted(args.probe_at)
        probe_tasks: list[asyncio.Task] = []
        deadline = t0 + args.idle if args.idle else None
        settle_until: float | None = None

        def _harvest() -> None:
            for task in [t for t in probe_tasks if t.done()]:
                probe_tasks.remove(task)
                probe = task.result()
                probes.append(probe)
                raw.write(json.dumps({"kind": "probe", **probe}) + "\n")
                shown = probe["ttft_s"] if probe["ttft_s"] is not None else probe["error"]
                print(f"  probe at {probe['at']:>6.1f}s -> first token {shown}")

        while True:
            now = time.monotonic()

            if ingest_task is not None and ingest_task.done() and doc_id is None:
                try:
                    doc_id, dedup_hit = ingest_task.result()
                except (httpx.HTTPError, SystemExit) as exc:
                    ingest_error = f"{type(exc).__name__}: {exc}"
                    print(f"ingest failed: {ingest_error}")
                    break
                print(f"document {doc_id}{' (DEDUP HIT)' if dedup_hit else ''}")

            sample = await _sample(client, backend, ollama_url, procs, doc_id, t0)
            samples.append(sample)
            raw.write(json.dumps({"kind": "sample", **sample}) + "\n")

            # Probes run as tasks: an Ask under load takes tens of seconds, and
            # awaiting one inline stops sampling across exactly the window where
            # the LLM and the ingest are both resident. At most one is ever in
            # flight -- two overlapping probes queue behind each other in the
            # runtime's slots, and the second then measures the profiler rather
            # than the ingest.
            while probe_offsets and (now - t0) >= probe_offsets[0]:
                offset = probe_offsets.pop(0)
                if probe_tasks:
                    probes.append(
                        skipped := {
                            "at": round(offset, 2),
                            "ttfb_s": None,
                            "ttft_s": None,
                            "declined": False,
                            "no_context": False,
                            "saw_done": False,
                            "last_event": [],
                            "scope": None,
                            "error": "skipped: previous probe still in flight",
                        }
                    )
                    raw.write(json.dumps({"kind": "probe", **skipped}) + "\n")
                    print(f"  probe at {offset:>6.1f}s -> skipped, previous still running")
                    continue
                probe_tasks.append(
                    asyncio.create_task(
                        _probe_ttft(
                            client,
                            backend,
                            args.question,
                            t0,
                            doc_id if args.probe_scope == "ingesting" else None,
                        )
                    )
                )
            _harvest()

            stage = samples[-1]["stage"]
            if stage == "complete" and settle_until is None:
                # Deferred summaries and enrichment start here, so the interesting
                # window is after `complete`, not before it.
                settle_until = now + args.settle
                print(f"stage complete at {samples[-1]['t']}s; sampling {args.settle}s more")
            if stage == "error":
                print("ingestion reported an error; stopping")
                break
            pending = bool(probe_offsets or probe_tasks)
            if settle_until is not None and now >= settle_until and not pending:
                break
            if deadline is not None and now >= deadline and not pending:
                break
            if ingest_task is None and deadline is None and not pending:
                break
            if (now - t0) >= args.max_duration:
                # An ingest that never reaches `complete` must not leave the
                # profiler sampling forever; the partial run is still usable.
                print(f"max duration {args.max_duration}s reached; stopping")
                break

            await asyncio.sleep(args.interval)

        if probe_tasks:
            await asyncio.gather(*probe_tasks, return_exceptions=True)
            _harvest()
        if ingest_task is not None and not ingest_task.done():
            ingest_task.cancel()

        library_after = await _library(client, backend)
        raw.close()

    meta = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "host": platform.node(),
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "total_ram_mb": round(psutil.virtual_memory().total / MB, 1),
        "backend_version": backend_version,
        "ollama_max_loaded": _ollama_cap(procs),
        "library_before": library_before,
        "library_after": library_after,
        "source": Path(args.ingest).name if args.ingest else None,
        "dedup_hit": dedup_hit,
        "ingest_error": ingest_error,
    }
    summary = _summarise(samples, probes, meta)

    # Samples and probes are already on disk; only the summary is appended.
    out = raw_path
    with out.open("a") as fh:
        fh.write(json.dumps({"kind": "summary", **summary}) + "\n")

    _print_report(summary, samples)
    print(f"  raw samples -> {out}")

    if args.summary:
        summary_path = _repo_path(args.summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("a") as fh:
            fh.write(json.dumps(summary) + "\n")
        print(f"  summary appended -> {summary_path}")

    # A requested measurement that did not happen is a failure, not a baseline:
    # a dedup hit profiles an idle backend and reads as a very low peak.
    if args.ingest and (summary["dedup_hit"] or summary["ingest_error"]):
        reason = summary["ingest_error"] or "already ingested (file hash dedup) -- nothing ran"
        print(f"\n  FAILED: {reason}")
        return 1
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
    ap.add_argument(
        "--probe-scope",
        choices=["all", "ingesting"],
        default="all",
        help="'all' times an Ask over the library (latency under load); "
        "'ingesting' asks the document being ingested (readiness, not latency)",
    )
    ap.add_argument("--max-duration", type=float, default=3600.0)
    ap.add_argument("--out", default=".luminary/mem_profile/latest.jsonl")
    ap.add_argument("--summary", help="append the one-line summary to this file")
    args = ap.parse_args()

    if not args.ingest and not args.idle:
        args.idle = 30.0
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
