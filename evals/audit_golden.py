"""Golden-dataset audit tool (S212).

Diagnostic for the retrieval golden baseline. Reads each entry in a
golden .jsonl, runs the public /search endpoint, and reports any entry
whose ``context_hint`` does not appear (as a normalised substring) in
*any* of the chunks returned -- regardless of rank. This isolates eval
failures into three buckets:

  - PASS   : hint substring present in at least one returned chunk
  - MISS   : /search returned chunks but none contained the hint
  - EMPTY  : /search returned no chunks for this entry (manifest stale,
             document not ingested, or upstream search failure)

Unlike ``run_eval.py``, this is **not** a metric runner -- it does not
compute HR@5/MRR and does not append to ``scores_history.jsonl``. It is
a permanent operator tool intended for diagnosing eval regressions.

Usage::

    cd evals
    uv run python audit_golden.py --dataset book_alice
    uv run python audit_golden.py --dataset book_time_machine --limit-chunks 50
    uv run python audit_golden.py --dataset book_odyssey --backend-url http://localhost:7820
    uv run python audit_golden.py --all  # every dataset listed in run_eval.VALID_DATASETS

The shape of /search results, the manifest contract, and the hint-norm
rule are all imported from run_eval.py so the audit and the eval cannot
drift apart.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

import httpx

# Reuse shared helpers so audit and eval stay aligned. ``run_eval`` lives in
# the same package directory so a flat import works when this script is
# launched from inside ``evals/``.
from run_eval import (  # noqa: PLC0415 -- intentional: same-dir module
    GOLDEN_DIR,
    VALID_DATASETS,
    _norm,
    load_golden,
    load_manifest,
)


@dataclass
class AuditRow:
    index: int
    question: str
    source_file: str
    doc_id: str | None
    context_hint: list[str]
    status: str  # "pass" | "miss" | "empty"
    returned_chunks: int
    rank: int | None  # 1-based rank of first chunk matching ANY hint alternate
    hint_status: list[str]  # one of "pass" | "miss" per alternate, parallel to context_hint


def _hint_norm_prefix(hint: str) -> str:
    """First 80 normalised chars of hint -- mirrors run_eval.compute_hit_rate_5."""
    return _norm(hint)[:80]


def _coerce_hints(raw: object) -> list[str]:
    """Coerce a context_hint payload (str | list[str] | None) into a list of strings."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [h for h in raw if isinstance(h, str) and h.strip()]
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    return []


def _search(
    backend_url: str,
    question: str,
    limit: int,
    document_id: str | None = None,
) -> tuple[list[dict], int]:
    """Call /search. Returns (all_matches_sorted_by_score_desc, http_status).

    On network failure or non-2xx response, returns ([], status_code_or_0).
    """
    params: dict[str, object] = {"q": question, "limit": limit}
    if document_id:
        params["document_id"] = document_id
    try:
        resp = httpx.get(
            f"{backend_url}/search",
            params=params,
            timeout=30.0,
        )
        status = resp.status_code
        if status >= 400:
            return [], status
        body = resp.json()
    except Exception:
        return [], 0

    matches: list[dict] = []
    for group in body.get("results", []):
        for m in group.get("matches", []):
            m_copy = dict(m)
            m_copy["_doc_id"] = group.get("document_id")
            matches.append(m_copy)
    matches.sort(key=lambda m: m.get("relevance_score", 0.0), reverse=True)
    return matches, status


def audit_dataset(
    dataset: str,
    backend_url: str,
    limit_chunks: int,
    *,
    require_doc_id_match: bool,
    verbose: bool,
) -> list[AuditRow]:
    rows = load_golden(dataset)
    manifest = load_manifest()

    results: list[AuditRow] = []
    for i, row in enumerate(rows, start=1):
        question = row["question"]
        hints = _coerce_hints(row.get("context_hint"))
        if not hints:
            gt = row.get("ground_truth_answer", "")
            if gt:
                hints = [gt[:50]]
        hint_norms = [_hint_norm_prefix(h) for h in hints]
        source_file = row.get("source_file", "")
        doc_id = manifest.get(source_file)

        # Scope /search to the target document when require_doc_id_match is
        # set so the audit reflects per-document retrieval quality (S212).
        # Otherwise call /search globally to surface stale-manifest cases.
        scoped_doc_id = doc_id if (require_doc_id_match and doc_id) else None
        matches, _status = _search(
            backend_url, question, limit_chunks, document_id=scoped_doc_id
        )

        considered = matches
        if require_doc_id_match and doc_id:
            considered = [m for m in matches if m.get("_doc_id") == doc_id]

        # Per-alternate hit detection. An alternate "passes" if it appears in
        # any considered chunk; the entry "passes" if any alternate passes.
        hint_status = ["miss"] * len(hint_norms)
        rank: int | None = None
        for j, m in enumerate(considered, start=1):
            text_norm = _norm(m.get("text", ""))
            for k, hn in enumerate(hint_norms):
                if hn and hn in text_norm:
                    hint_status[k] = "pass"
                    if rank is None:
                        rank = j
            if rank is not None and all(s == "pass" for s in hint_status):
                break

        if not considered:
            status = "empty"
        elif rank is None:
            status = "miss"
        else:
            status = "pass"

        results.append(
            AuditRow(
                index=i,
                question=question,
                source_file=source_file,
                doc_id=doc_id,
                context_hint=hints,
                status=status,
                returned_chunks=len(considered),
                rank=rank,
                hint_status=hint_status,
            )
        )

        if verbose and status != "pass":
            alt_summary = ", ".join(
                f"{k}:{s}" for k, s in enumerate(hint_status)
            ) if len(hint_norms) > 1 else ""
            print(
                f"  [{i:3d}] {status.upper():5s}  "
                f"chunks={len(considered):3d}  "
                f"q={question[:60]!r}  "
                f"hints={len(hint_norms)} {alt_summary}"
            )

    return results


def summarise(dataset: str, rows: list[AuditRow]) -> dict:
    total = len(rows)
    n_pass = sum(1 for r in rows if r.status == "pass")
    n_miss = sum(1 for r in rows if r.status == "miss")
    n_empty = sum(1 for r in rows if r.status == "empty")
    return {
        "dataset": dataset,
        "total": total,
        "pass": n_pass,
        "miss": n_miss,
        "empty": n_empty,
        "pass_rate": n_pass / total if total else 0.0,
    }


def print_summary(s: dict) -> None:
    print(
        f"  {s['dataset']:24s}  total={s['total']:3d}  "
        f"pass={s['pass']:3d}  miss={s['miss']:3d}  empty={s['empty']:3d}  "
        f"pass_rate={s['pass_rate']:.2%}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit a golden dataset against /search. Reports entries "
        "whose context_hint is absent from any returned chunk (regardless of rank)."
    )
    parser.add_argument("--dataset", default="", help="Single dataset name to audit (e.g. book_alice).")
    parser.add_argument("--all", action="store_true", help="Audit every dataset in VALID_DATASETS.")
    parser.add_argument(
        "--backend-url",
        default="http://localhost:7820",
        dest="backend_url",
        help="Luminary backend URL (default: http://localhost:7820 -- the project's dev port).",
    )
    parser.add_argument(
        "--limit-chunks",
        type=int,
        default=20,
        dest="limit_chunks",
        help="Pass-through to /search?limit (default 20). Increase to widen the search window.",
    )
    parser.add_argument(
        "--require-doc-id-match",
        action="store_true",
        dest="require_doc_id_match",
        help="Only count chunks belonging to the manifest doc_id. Off by default so the audit "
        "still reports useful information when the manifest is stale.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress per-entry lines.")
    args = parser.parse_args()

    if not args.dataset and not args.all:
        parser.error("specify --dataset NAME or --all")

    targets: list[str]
    if args.all:
        targets = [
            d
            for d in VALID_DATASETS
            if (GOLDEN_DIR / f"{d}.jsonl").exists()
        ]
    else:
        if args.dataset not in VALID_DATASETS:
            print(f"WARNING: '{args.dataset}' not in VALID_DATASETS {VALID_DATASETS}", file=sys.stderr)
        targets = [args.dataset]

    overall: list[dict] = []
    for ds in targets:
        path = GOLDEN_DIR / f"{ds}.jsonl"
        if not path.exists():
            print(f"  {ds:24s}  SKIP (no golden file at {path})")
            continue
        if not args.quiet:
            print(f"\nAuditing {ds} ...")
        rows = audit_dataset(
            ds,
            backend_url=args.backend_url,
            limit_chunks=args.limit_chunks,
            require_doc_id_match=args.require_doc_id_match,
            verbose=not args.quiet,
        )
        s = summarise(ds, rows)
        overall.append(s)

    print("\nSummary:")
    for s in overall:
        print_summary(s)

    # Emit machine-readable summary on stderr's neighbour fd (stdout) for
    # consumption by smoke / CI; keep human summary separate above.
    print("\nJSON summary:")
    print(json.dumps(overall, indent=2))


if __name__ == "__main__":
    main()
