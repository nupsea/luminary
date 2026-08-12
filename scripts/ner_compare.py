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
import os
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


def _run_one(
    model_id: str, chunks: list[dict], data_dir: str, is_technical: bool
) -> dict:
    """Load one model, extract, and release it before the next is measured."""
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

    pairs = {(e["name"], e["type"]) for e in entities}
    types = Counter(e["type"] for e in entities)

    extractor._model = None
    del extractor
    gc.collect()

    return {
        "model": model_id,
        "load_s": round(load_s, 2),
        "extract_s": round(extract_s, 2),
        "resident_mb": round((rss_loaded - rss_before) / MB, 1),
        "entities": len(entities),
        "unique": len(pairs),
        "types": types,
        "pairs": pairs,
    }


def _report(base: dict, cand: dict, samples: int) -> None:
    both = base["pairs"] & cand["pairs"]
    only_base = base["pairs"] - cand["pairs"]
    only_cand = cand["pairs"] - base["pairs"]
    union = base["pairs"] | cand["pairs"]
    agreement = len(both) / len(union) if union else 0.0

    print()
    print(f"  {'':<22} {'baseline':>14} {'candidate':>14}")
    print(f"  {'model':<22} {base['model'].split('/')[-1]:>14} {cand['model'].split('/')[-1]:>14}")
    print(f"  {'resident (MB)':<22} {base['resident_mb']:>14,.1f} {cand['resident_mb']:>14,.1f}")
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
    print("  type distribution")
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
    args = ap.parse_args()

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
