"""Corpus-wide (All-documents) retrieval routing eval.

Every ablation arm in run_eval.py runs SCOPED (document_id pinned per question),
so they measure chunk ranking WITHIN the right document and never test whether
retrieval picks the right document at all. Real "All documents" chat does not
have that luxury -- a short query with one mistyped proper noun collapses to the
wrong corpus (e.g. "who is the king of Itaca?" -> Federalist/Bible). This tool
measures that regime directly, UNSCOPED, across a set of goldens:

  route@1  top-1 chunk is from the gold source document (did we route right?)
  route@5  gold source document appears in the top-5 chunks
  HR@5     the gold hint is in the top-5 chunks (answerability, corpus-wide)

With --typo it re-runs each question with a single-character deletion on its
longest word, quantifying typo-robustness of document routing.

Usage (from repo root or evals/):
    uv run --project backend python evals/run_corpus_routing.py \
        --datasets book,paper,conversation,notes,odyssey,book_frankenstein \
        --backend-url http://localhost:7820 [--typo]
Dataset tokens may be file-golden names (mapped via manifest) or DB dataset
UUIDs (source_document_id is pinned per row).
"""

import argparse
import re
import sys
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from evals.lib.retrieval_metrics import _extract_hint_norms, _norm  # noqa: E402
from evals.lib.store import store_results  # noqa: E402
from evals.run_eval import (  # noqa: E402
    load_golden,
    load_golden_by_id,
    load_manifest,
)

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-", re.I)


def inject_typo(q: str) -> str:
    words = re.findall(r"[A-Za-z]{5,}", q)
    if not words:
        return q
    w = max(words, key=len)
    i = len(w) // 2
    return q.replace(w, w[:i] + w[i + 1 :], 1)


def routing_search(client: httpx.Client, backend_url: str, q: str, limit: int = 8):
    """UNSCOPED corpus-wide search -> flat [(document_id, text)] in rank order."""
    try:
        body = client.get(
            f"{backend_url}/search",
            params={"q": q, "rerank": "true", "limit": str(limit)},
        ).json()
    except Exception as exc:
        print(f"  WARNING: /search failed: {exc}", file=sys.stderr)
        return []
    # /search groups matches by document (first-appearance order), so a plain
    # group-by-group flatten lets a top document's TAIL matches shadow another
    # document's rank-2 chunk and understates route@5/HR@5. global_rank is the
    # retriever's final ordering; sorting by score instead would invert FTS
    # (negative BM25) and undo rrf diversification.
    flat = [
        (m.get("global_rank", float("inf")), g.get("document_id"), m.get("text", ""))
        for g in body.get("results", [])
        for m in g.get("matches", [])
    ]
    flat.sort(key=lambda t: t[0])
    return [(doc, text) for _, doc, text in flat]


def resolve_rows(token: str, backend_url: str, manifest: dict):
    """Return (label, [(question, hint, gold_doc_id)]) for a dataset token."""
    if _UUID.match(token):
        rows = load_golden_by_id(backend_url, token)
        get_doc = lambda r: r.get("source_document_id")  # noqa: E731
    else:
        rows = load_golden(token)
        get_doc = lambda r: r.get("source_document_id") or manifest.get(r.get("source_file", ""))  # noqa: E731
    out = []
    for r in rows:
        doc = get_doc(r)
        if doc and r.get("context_hint"):
            out.append((r["question"], r["context_hint"], doc))
    return token, out


def eval_one(client, backend_url, rows, typo: bool):
    r1 = r5 = hr = 0
    n = len(rows)
    for q, hint, gold in rows:
        if typo:
            q = inject_typo(q)
        flat = routing_search(client, backend_url, q)
        docs = [d for d, _ in flat]
        keys = _extract_hint_norms({"context_hint": hint})
        r1 += bool(docs) and docs[0] == gold
        r5 += gold in docs[:5]
        hr += any(any(k in _norm(t) for k in keys) for _, t in flat[:5])
    return (r1 / n, r5 / n, hr / n) if n else (0.0, 0.0, 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", required=True, help="comma-separated golden names or UUIDs")
    ap.add_argument("--backend-url", default="http://localhost:7820")
    ap.add_argument("--typo", action="store_true", help="also run a single-char-typo variant")
    ap.add_argument("--no-store", action="store_true", help="don't persist runs to the backend")
    args = ap.parse_args()

    manifest = load_manifest()
    tokens = [t.strip() for t in args.datasets.split(",") if t.strip()]
    arms = ["clean", "typo"] if args.typo else ["clean"]

    hdr = "  ".join(f"{a} route@1/route@5/HR@5" for a in arms)
    print(f"{'dataset':<20} {hdr}")
    agg = {a: {"r1": [], "r5": [], "hr": []} for a in arms}
    with httpx.Client(timeout=120.0) as client:
        for token in tokens:
            label, rows = resolve_rows(token, args.backend_url, manifest)
            if not rows:
                print(f"{label:<20} (no usable rows)")
                continue
            cells = []
            scored = {}
            for arm in arms:
                r1, r5, hr = eval_one(client, args.backend_url, rows, typo=(arm == "typo"))
                scored[arm] = (r1, r5, hr)
                agg[arm]["r1"].append(r1)
                agg[arm]["r5"].append(r5)
                agg[arm]["hr"].append(hr)
                cells.append(f"{r1:.2f}/{r5:.2f}/{hr:.2f}")
            print(f"{label[:20]:<20} " + "        ".join(cells), flush=True)

            if not args.no_store:
                cr1, cr5, chr_ = scored["clean"]
                # route@1 -> routing_accuracy (known column), HR@5 -> hit_rate_5;
                # route@5 + the typo arm ride along in extra_metrics.
                metrics = {"hit_rate_5": chr_, "routing_accuracy": cr1, "route_5": cr5,
                           "n_questions": len(rows)}
                if "typo" in scored:
                    tr1, tr5, thr = scored["typo"]
                    metrics.update({"route_1_typo": tr1, "route_5_typo": tr5, "hr_5_typo": thr})
                store_results(args.backend_url, label, "no-llm", metrics,
                              eval_kind="corpus_routing")

    print()
    for arm in arms:
        d = agg[arm]

        def _m(key):
            return sum(d[key]) / len(d[key]) if d[key] else 0.0

        print(f"MEAN [{arm:5}] route@1={_m('r1'):.2f}  route@5={_m('r5'):.2f}  HR@5={_m('hr'):.2f}")


if __name__ == "__main__":
    main()
