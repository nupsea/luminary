#!/usr/bin/env python3
"""Compare two GLiNER models on this corpus before changing `NER_MODEL`.

The entity model cannot simply be swapped for a smaller one, because
`graph_expand` in `retriever_strategies` skips query expansion whenever the
model is not resident -- so the choice is not "large model or no model", it is
which model is small enough to stay loaded. That only pays off if a smaller
model extracts comparable entities.

What this measures, and what it does not:

- Load time and resident cost, per model, measured one at a time.
- Entity yield and type distribution.
- **Agreement**, not accuracy. Neither model is ground truth. A disagreement is
  a prompt to read the samples printed at the end, not a score.

The gate that actually decides the swap is downstream and lives elsewhere: run
`make eval` under each `NER_MODEL` and compare hit_rate/MRR. Entities exist here
to serve retrieval, so retrieval is what must not regress.

Usage::

    make ner-compare
    uv run python ../scripts/ner_compare.py --candidate urchade/gliner_small-v2.1
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

MB = 1024 * 1024
DEFAULT_BACKEND = "http://127.0.0.1:7820"


def _fetch_chunks(backend: str, limit: int) -> tuple[list[dict], bool]:
    """Chunks from the live library, with the technical flag of their document."""
    with httpx.Client(timeout=30.0) as client:
        docs = client.get(f"{backend}/documents", params={"page_size": 20})
        docs.raise_for_status()
        items = docs.json().get("items", [])
        if not items:
            raise SystemExit("no documents in the library -- ingest something first")

        collected: list[dict] = []
        technical = False
        for doc in items:
            if len(collected) >= limit:
                break
            resp = client.get(
                f"{backend}/documents/{doc['id']}/chunks", params={"limit": limit}
            )
            if resp.status_code != 200:
                continue
            for c in resp.json():
                text = c.get("text") or ""
                if len(text) < 200:
                    continue
                collected.append(
                    {"id": c.get("id", ""), "document_id": doc["id"], "text": text}
                )
                if len(collected) >= limit:
                    break
            technical = technical or bool(doc.get("is_technical"))
    return collected, technical


def _measure_in_process(
    model_id: str, chunks: list[dict], data_dir: str, is_technical: bool
) -> dict:
    """Measure one model in a process that has loaded nothing else.

    Run via ``--single``, one subprocess per model. Measuring both in one
    process cannot work: the first load also imports torch and transformers,
    charging ~1.5GB of shared runtime to whichever model happens to go first,
    and CPython does not return freed arenas to the OS, so the second model
    appears to cost whatever the first one failed to give back. Measured that
    way a 336MB model reads as larger than a 1126MB one.
    """
    from app.services.ner import EntityExtractor  # noqa: PLC0415

    proc = psutil.Process()
    gc.collect()
    rss_before = proc.memory_info().rss

    extractor = EntityExtractor(data_dir, model_id=model_id)
    t0 = time.monotonic()
    extractor._load_model()
    load_s = time.monotonic() - t0
    rss_loaded = proc.memory_info().rss

    t1 = time.monotonic()
    entities = extractor.extract(chunks, "book", is_technical=is_technical)
    extract_s = time.monotonic() - t1

    return {
        "model": model_id,
        "load_s": round(load_s, 2),
        "extract_s": round(extract_s, 2),
        # Not weights alone: the first `from gliner import GLiNER` also drags in
        # torch and transformers, and that import is charged here. Compare the
        # two models on `peak_rss_mb`, which is what the app actually pays.
        "load_delta_mb": round((rss_loaded - rss_before) / MB, 1),
        "peak_rss_mb": round(proc.memory_info().rss / MB, 1),
        "entities": len(entities),
        "pairs": sorted([e["name"], e["type"]] for e in entities),
    }


def _run_one(
    model_id: str, chunks: list[dict], data_dir: str, is_technical: bool
) -> dict:
    """Measure one model in its own subprocess, then rehydrate the result."""
    payload = json.dumps({"chunks": chunks, "is_technical": is_technical})
    out = subprocess.run(  # noqa: S603
        [sys.executable, str(Path(__file__).resolve()), "--single", model_id,
         "--data-dir", data_dir],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise SystemExit(f"measuring {model_id} failed:\n{out.stderr[-2000:]}")
    try:
        result = json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise SystemExit(
            f"measuring {model_id} produced no result:\n{out.stdout[-2000:]}"
        ) from None

    pairs = {(name, typ) for name, typ in result.pop("pairs")}
    result["pairs"] = pairs
    result["unique"] = len(pairs)
    result["types"] = Counter(typ for _, typ in pairs)
    return result


def _report(base: dict, cand: dict, samples: int) -> None:
    both = base["pairs"] & cand["pairs"]
    only_base = base["pairs"] - cand["pairs"]
    only_cand = cand["pairs"] - base["pairs"]
    union = base["pairs"] | cand["pairs"]
    agreement = len(both) / len(union) if union else 0.0

    print()
    print(f"  {'':<22} {'baseline':>14} {'candidate':>14}")
    print(f"  {'model':<22} {base['model'].split('/')[-1]:>14} {cand['model'].split('/')[-1]:>14}")
    print(
        f"  {'process peak (MB)':<22} "
        f"{base['peak_rss_mb']:>14,.1f} {cand['peak_rss_mb']:>14,.1f}"
    )
    print(
        f"  {'load delta (MB)':<22} "
        f"{base['load_delta_mb']:>14,.1f} {cand['load_delta_mb']:>14,.1f}"
    )
    print(f"  {'load (s)':<22} {base['load_s']:>14.2f} {cand['load_s']:>14.2f}")
    print(f"  {'extract (s)':<22} {base['extract_s']:>14.2f} {cand['extract_s']:>14.2f}")
    print(f"  {'entities':<22} {base['entities']:>14,} {cand['entities']:>14,}")
    print(f"  {'unique (name,type)':<22} {base['unique']:>14,} {cand['unique']:>14,}")
    print()
    print(f"  agreement (Jaccard)    {agreement:>14.3f}")
    print(f"  shared                 {len(both):>14,}")
    print(f"  baseline only          {len(only_base):>14,}")
    print(f"  candidate only         {len(only_cand):>14,}")

    print()
    print("  unique (name,type) per type")
    for t in sorted(set(base["types"]) | set(cand["types"])):
        print(f"    {t:<20} {base['types'].get(t, 0):>14,} {cand['types'].get(t, 0):>14,}")

    # Neither set is ground truth, so the only honest output is the disagreement
    # itself: whether the candidate drops real entities or drops noise is a
    # judgement a reader makes here.
    print()
    print(f"  baseline found, candidate missed (first {samples})")
    for name, typ in sorted(only_base)[:samples]:
        print(f"    {typ:<20} {name}")
    print()
    print(f"  candidate found, baseline missed (first {samples})")
    for name, typ in sorted(only_cand)[:samples]:
        print(f"    {typ:<20} {name}")

    print()
    print("  Agreement is not accuracy. Decide with `make eval` under each")
    print("  NER_MODEL: entities serve retrieval, so retrieval is the gate.")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", default=DEFAULT_BACKEND)
    ap.add_argument("--baseline", default="urchade/gliner_multi_pii-v1")
    ap.add_argument("--candidate", default="urchade/gliner_small-v2.1")
    ap.add_argument("--chunks", type=int, default=120)
    ap.add_argument("--samples", type=int, default=15, help="disagreements to print")
    ap.add_argument("--data-dir", default=os.environ.get("DATA_DIR", ".luminary"))
    ap.add_argument("--single", help=argparse.SUPPRESS)  # internal: one model, one process
    args = ap.parse_args()

    if args.single:
        job = json.loads(sys.stdin.read())
        result = _measure_in_process(
            args.single, job["chunks"], args.data_dir, job["is_technical"]
        )
        print(json.dumps(result))
        return 0

    backend = args.backend.rstrip("/")
    try:
        chunks, is_technical = _fetch_chunks(backend, args.chunks)
    except httpx.HTTPError as exc:
        print(f"backend not reachable at {backend}: {exc}")
        return 1

    print(f"comparing on {len(chunks)} chunks (is_technical={is_technical})")
    base = _run_one(args.baseline, chunks, args.data_dir, is_technical)
    cand = _run_one(args.candidate, chunks, args.data_dir, is_technical)
    _report(base, cand, args.samples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
