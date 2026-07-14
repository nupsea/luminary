"""RAGAS evaluation runner for Luminary golden datasets.

Usage::
    # Standard eval (uses /search for retrieval quality, no LLM required)
    uv run python run_eval.py --dataset book
    uv run python run_eval.py --dataset paper --backend-url http://localhost:8000

    # With LLM-based RAGAS scoring
    uv run python run_eval.py --dataset book --model ollama/mistral

    # Assert quality gates (exits 1 if HR@5 < 0.50, MRR < 0.35, Faithfulness < 0.65)
    uv run python run_eval.py --dataset book --assert-thresholds

Documents are auto-ingested on first run and their IDs cached in
evals/golden/manifest.json.  Re-runs skip ingestion.

Most of the underlying machinery lives in ``evals.lib`` (S213). This file
keeps the CLI shape and re-exports the original symbols for backwards
compatibility with audit_golden.py and existing tests.
"""

import argparse
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

# Make `evals.lib.*` importable when this file is invoked as `python run_eval.py`
# from inside evals/ (the canonical CLI entry point).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from evals.lib.loader import GoldenValidationError  # noqa: E402
from evals.lib.citation_metrics import (  # noqa: E402
    compute_citation_support_rate,
    judge_citation,
    parse_claims_with_citations,
)
from evals.lib.loader import load_golden as _lib_load_golden  # noqa: E402
from evals.lib.manifest import (  # noqa: E402
    GOLDEN_DIR,
    MANIFEST_PATH,
    REPO_ROOT,
    ensure_ingested,
    ingest_document,
    is_document_alive,
    load_manifest,
    lookup_document_by_filename,
    resolve_backend_base,
    save_manifest,
)
from evals.lib.retrieval_metrics import (  # noqa: E402
    _extract_hint_norms,
    _norm,
    compute_hit_rate_5,
    compute_mrr,
    compute_ndcg_10,
    compute_recall_at,
)
from evals.lib.runners import GenerationEval, NliFaithfulnessEval  # noqa: E402
from evals.lib.schemas import RetrievalGoldenEntry  # noqa: E402
from evals.lib.scoring_history import SCORES_HISTORY_PATH  # noqa: E402
from evals.lib.scoring_history import append_history as _lib_append_history  # noqa: E402
from evals.lib.store import store_results as _lib_store_results  # noqa: E402

# Backwards-compat alias: tests and audit_golden.py import GoldenEntry from run_eval.
GoldenEntry = RetrievalGoldenEntry

VALID_DATASETS = [
    "book",
    "book_time_machine",
    "book_alice",
    "book_frankenstein",
    "d2l",
    "odyssey",
    "paper",
    "conversation",
    "notes",
    "code",
]

# Per-/qa timeout for generation runs. A local answering model (Ollama, CPU)
# legitimately takes 30-60s per answer and longer on a cold start; the eval is
# a background batch job, so this is generous by design. A too-tight value
# silently drops answers and understates generation metrics.
QA_REQUEST_TIMEOUT = 300.0

# Quality gate thresholds. ndcg_10 is provisional / report-only: it is shown
# against this bar in the UI but never asserted, because most goldens still
# carry single-passage relevance (nDCG degrades to a log-discounted single-hit
# metric there). Promote it to an asserted gate once graded goldens exist and
# baselines are recorded.
THRESHOLDS = {
    "hit_rate_5": 0.50,
    "mrr": 0.35,
    "ndcg_10": 0.40,
    "faithfulness": 0.65,
    "answer_relevance": 0.50,
    "citation_support_rate": 0.80,
}

DATASET_THRESHOLDS: dict[str, dict[str, float]] = {
    "paper": {"hit_rate_5": 0.45, "mrr": 0.30},
    "conversation": {"hit_rate_5": 0.55, "mrr": 0.40},
    "notes": {"hit_rate_5": 0.60, "mrr": 0.45},
    "code": {"hit_rate_5": 0.50, "mrr": 0.35},
}


def thresholds_for_dataset(dataset: str) -> dict[str, float]:
    """Return retrieval/generation thresholds for a dataset."""
    return {**THRESHOLDS, **DATASET_THRESHOLDS.get(dataset, {})}


def load_golden(dataset: str) -> list[dict]:
    """Load and validate a golden JSONL dataset.

    Wraps evals.lib.loader.load_golden with the legacy CLI behaviour: prints
    a clear error message and exits 1 on schema-validation failure.
    """
    try:
        return _lib_load_golden(dataset, RetrievalGoldenEntry)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except GoldenValidationError as exc:
        print(f"ERROR: invalid golden entry in {exc}", file=sys.stderr)
        sys.exit(1)


def load_golden_by_id(backend_url: str, dataset_id: str) -> list[dict]:
    """Load a DB-backed generated golden dataset from the backend API."""
    try:
        resp = httpx.get(f"{backend_url}/evals/datasets/{dataset_id}/golden", timeout=30.0)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        print(f"ERROR: could not load generated dataset {dataset_id}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(rows, list):
        print(f"ERROR: generated dataset {dataset_id} did not return a list", file=sys.stderr)
        sys.exit(1)
    return rows


def split_rows_by_document_liveness(
    rows: list[dict],
    is_alive: "callable[[str], bool]",
) -> tuple[list[dict], set[str]]:
    """Partition golden rows into (rows whose pinned document is alive, dead doc ids).

    Rows without a source_document_id pin are kept — they run unscoped. A row
    pinned to a deleted document CANNOT retrieve anything, so keeping it would
    score a guaranteed 0 that reads as a retrieval regression.
    """
    doc_ids = {r.get("source_document_id") for r in rows if r.get("source_document_id")}
    dead = {d for d in doc_ids if not is_alive(d)}
    if not dead:
        return rows, set()
    alive_rows = [r for r in rows if r.get("source_document_id") not in dead]
    return alive_rows, dead


def append_history(dataset: str, model: str, metrics: dict, passed: bool) -> None:
    """Backwards-compat wrapper -- always logs eval_kind='retrieval'."""
    _lib_append_history(dataset, model, metrics, passed, eval_kind="retrieval")


def store_results(backend_url: str, dataset: str, model: str, metrics: dict) -> None:
    """Backwards-compat wrapper -- always sends eval_kind='retrieval'."""
    _lib_store_results(backend_url, dataset, model, metrics, eval_kind="retrieval")


# ---------------------------------------------------------------------------
# Search and /qa helpers (CLI-specific; not in lib)
# ---------------------------------------------------------------------------


def search_chunks(
    backend_url: str,
    question: str,
    document_id: str | None,
    *,
    hyde: bool = False,
    rerank: bool = False,
    rerank_depth: int | None = None,
    rerank_threshold: float | None = None,
    rerank_blend: float | None = None,
    rerank_adaptive: bool = False,
    strategy: str = "rrf",
    limit: int | None = None,
    expand_context: bool = True,
) -> list[str]:
    """Run GET /search and return up to top-10 chunk texts.

    HR@5 and MRR@5 cap their own depth at 5; the extra tail exists for
    nDCG@10. An explicit *limit* widens the window past 10 -- the pool-recall
    arm needs the full ranked list to measure Recall@K.
    """
    params: dict[str, str] = {"q": question}
    if document_id:
        params["document_id"] = document_id
        params["limit"] = "20"
    if limit is not None:
        params["limit"] = str(limit)
    if not expand_context:
        params["expand_context"] = "false"
    if hyde:
        params["hyde"] = "true"
    if rerank:
        params["rerank"] = "true"
        if rerank_depth is not None:
            params["rerank_depth"] = str(rerank_depth)
        if rerank_threshold is not None:
            params["rerank_threshold"] = str(rerank_threshold)
        if rerank_blend is not None:
            params["rerank_blend"] = str(rerank_blend)
        if rerank_adaptive:
            params["rerank_adaptive"] = "true"
    if strategy != "rrf":
        params["strategy"] = strategy
    try:
        request_timeout = 60.0 if (hyde or rerank or limit) else 30.0
        resp = httpx.get(f"{backend_url}/search", params=params, timeout=request_timeout)
        resp.raise_for_status()
        body = resp.json()

        # Preserve the backend's ranking. Do NOT re-sort by relevance_score:
        # its polarity is strategy-dependent (FTS returns raw BM25 scores where
        # MORE NEGATIVE = MORE relevant), so a reverse=True sort silently inverts
        # the FTS ranking and tanks HR@5. /search already returns matches ranked
        # per document, so keep that order.
        all_matches = []
        for group in body.get("results", []):
            if document_id and group.get("document_id") != document_id:
                continue
            all_matches.extend(group.get("matches", []))
        return [m.get("text", "") for m in all_matches[: limit or 10]]
    except Exception as exc:
        print(f"  WARNING: /search failed: {exc}", file=sys.stderr)
        return []


def post_qa(backend_url: str, question: str, model: str, document_id: str | None) -> dict:
    """POST to /qa and return the response JSON (or empty dict on failure)."""
    try:
        payload: dict = {"question": question}
        if document_id:
            payload["document_ids"] = [document_id]
        if model:
            payload["model"] = model
        resp = httpx.post(
            f"{backend_url}/qa",
            json=payload,
            timeout=QA_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        if "text/event-stream" in resp.headers.get("content-type", ""):
            final: dict = {}
            for line in resp.text.splitlines():
                if not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                if not raw:
                    continue
                try:
                    payload = httpx.Response(200, content=raw).json()
                except Exception:
                    continue
                if payload.get("done"):
                    final = payload
            return final
        return resp.json()
    except Exception as exc:
        print(f"  WARNING: /qa call failed: {exc}", file=sys.stderr)
        return {}


def print_table(dataset: str, model: str, metrics: dict) -> None:
    print(f"\n{'=' * 56}")
    print(f"  RAGAS evaluation -- dataset={dataset}  model={model}")
    print(f"{'=' * 56}")
    for key, val in metrics.items():
        if val is None:
            print(f"  {key:<22}  n/a")
        elif isinstance(val, float):
            print(f"  {key:<22}  {val:.4f}")
        else:
            print(f"  {key:<22}  {val}")
    print(f"{'=' * 56}\n")


def print_ablation_table(dataset: str, model: str, ablation_metrics: dict) -> None:
    print(f"\n{'=' * 56}")
    print(f"  Retrieval ablation -- dataset={dataset}  model={model}")
    print(f"{'=' * 56}")
    print(f"  {'strategy':<12} {'HR@5':>10} {'MRR':>10} {'NDCG@10':>10}")
    for strategy, metrics in ablation_metrics.items():
        if strategy == "rrf-pool":
            continue
        print(
            f"  {strategy:<12} "
            f"{metrics.get('hit_rate_5', 0.0):>10.4f} "
            f"{metrics.get('mrr', 0.0):>10.4f} "
            f"{metrics.get('ndcg_10', 0.0):>10.4f}"
        )
    pool = ablation_metrics.get("rrf-pool")
    if pool:
        print(f"  {'-' * 52}")
        print("  L1 pool recall (raw RRF, no rerank):")
        for key in sorted(pool, key=lambda s: int(s.rsplit("_", 1)[1])):
            depth = key.rsplit("_", 1)[1]
            print(f"  {'recall@' + depth:<12} {pool[key]:>10.4f}")
    print(f"{'=' * 56}\n")


__all__ = [
    "GOLDEN_DIR",
    "GoldenEntry",
    "MANIFEST_PATH",
    "REPO_ROOT",
    "SCORES_HISTORY_PATH",
    "DATASET_THRESHOLDS",
    "THRESHOLDS",
    "VALID_DATASETS",
    "_extract_hint_norms",
    "_norm",
    "compute_recall_at",
    "append_history",
    "compute_hit_rate_5",
    "compute_mrr",
    "compute_ndcg_10",
    "ensure_ingested",
    "ingest_document",
    "is_document_alive",
    "load_golden",
    "load_manifest",
    "lookup_document_by_filename",
    "post_qa",
    "print_table",
    "save_manifest",
    "search_chunks",
    "store_results",
    "thresholds_for_dataset",
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _export_html_report(
    *,
    path: str,
    dataset: str,
    model: str,
    metrics: dict,
    samples: list[dict],
    eval_kind: str,
    passed: bool,
    violations: list[str],
) -> None:
    from datetime import datetime
    import html as _html

    status_color = "#22c55e" if passed else "#ef4444"
    status_label = "PASS" if passed else "FAIL"

    metric_rows = ""
    for k, v in metrics.items():
        if v is None:
            continue
        shown = f"{v:.4f}" if isinstance(v, float) else str(v)
        metric_rows += f"<tr><td>{_html.escape(k)}</td><td>{_html.escape(shown)}</td></tr>"

    violation_html = ""
    if violations:
        items = "".join(f"<li>{_html.escape(v)}</li>" for v in violations)
        violation_html = f"<h3 style='color:#ef4444'>Quality gate failures</h3><ul>{items}</ul>"

    sample_rows = ""
    for s in samples[:50]:
        q = _html.escape(s.get("question", ""))
        ctx_snippet = _html.escape((s.get("contexts") or [""])[0][:200])
        sample_rows += f"<tr><td style='max-width:300px'>{q}</td><td style='max-width:400px;font-size:0.8em'>{ctx_snippet}…</td></tr>"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Luminary Eval — {_html.escape(dataset)}</title>
<style>
  body{{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;color:#1a1a1a}}
  h1{{font-size:1.5rem}}h2{{font-size:1.1rem;border-bottom:1px solid #ddd;padding-bottom:4px}}
  table{{border-collapse:collapse;width:100%}}th,td{{padding:8px 12px;text-align:left;border:1px solid #e5e7eb}}
  th{{background:#f9fafb}}.badge{{display:inline-block;padding:4px 12px;border-radius:99px;font-weight:600;color:#fff;background:{status_color}}}
  tr:nth-child(even){{background:#f9fafb}}
</style></head>
<body>
<h1>Luminary Retrieval Eval — {_html.escape(dataset)}</h1>
<p>Model: <code>{_html.escape(model)}</code> &nbsp; Kind: {_html.escape(eval_kind)} &nbsp; Run: {now}</p>
<p><span class="badge">{status_label}</span></p>
{violation_html}
<h2>Metrics</h2>
<table><tr><th>Metric</th><th>Score</th></tr>{metric_rows}</table>
<h2>Sample results (first {min(len(samples),50)} of {len(samples)})</h2>
<table><tr><th>Question</th><th>Top context chunk</th></tr>{sample_rows}</table>
</body></html>"""

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_content, encoding="utf-8")
    print(f"\nHTML report written to {out.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation against a golden dataset.")
    parser.add_argument("--dataset", required=False, help="Golden dataset name")
    parser.add_argument(
        "--dataset-id",
        required=False,
        dest="dataset_id",
        help="DB-backed generated golden dataset id",
    )
    parser.add_argument(
        "--model",
        default="",
        help="LiteLLM model string for LLM-based RAGAS scoring (optional)",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate app-default QA answers so faithfulness is scored (no judge).",
    )
    parser.add_argument(
        "--backend-url",
        default="http://localhost:8000",
        dest="backend_url",
        help="Luminary backend URL",
    )
    parser.add_argument(
        "--assert-thresholds",
        action="store_true",
        dest="assert_thresholds",
        help=(
            "Exit code 1 if any metric is below threshold: "
            "HR@5 >= 0.50, MRR >= 0.35, Faithfulness >= 0.65, "
            "Answer-Relevance >= 0.50"
        ),
    )
    parser.add_argument("--hyde", action="store_true", help="Enable HyDE-style query expansion.")
    parser.add_argument(
        "--rerank", action="store_true", help="Enable cross-encoder reranking."
    )
    parser.add_argument(
        "--rerank-depth",
        type=int,
        default=None,
        dest="rerank_depth",
        help="RRF candidate pool fed to the cross-encoder (backend default: 50).",
    )
    parser.add_argument(
        "--rerank-threshold",
        type=float,
        default=None,
        dest="rerank_threshold",
        help="Drop reranked candidates below this cross-encoder logit (default: no cut).",
    )
    parser.add_argument(
        "--rerank-depths",
        default="",
        dest="rerank_depths",
        metavar="N,N,...",
        help=(
            "Ablation-only depth sweep: adds one rrf+rerank@N arm per value "
            "(e.g. 25,50,100,200). Requires --ablation."
        ),
    )
    parser.add_argument(
        "--recall-depths",
        default="50,100,200",
        dest="recall_depths",
        metavar="N,N,...",
        help=(
            "Ablation-only L1 pool recall: measures Recall@K of the raw RRF pool "
            "(no rerank) at each depth (max 200). Pass an empty string to skip."
        ),
    )
    parser.add_argument(
        "--judge-model",
        default="",
        dest="judge_model",
        help=(
            "LiteLLM model string for the RAGAS judge LLM (Ollama-local per I-16). "
            "Opt-in: empty (default) skips generation metrics. When set, answers are "
            "generated live via POST /qa (the app's default model unless --model is "
            "given) and the judge scores those generated answers -- never the golden "
            "ground-truth answers."
        ),
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=None,
        dest="max_questions",
        help=(
            "Sample N entries deterministically (random.Random(42).sample) "
            "for fast runs. Default: all entries."
        ),
    )
    parser.add_argument(
        "--check-citations",
        action="store_true",
        dest="check_citations",
        help=(
            "Judge whether answer citations support their claims and compute "
            "citation_support_rate. Uses --judge-model."
        ),
    )
    parser.add_argument(
        "--ablation",
        action="store_true",
        help="Run retrieval ablation across vector, fts, graph, and rrf strategies.",
    )
    parser.add_argument(
        "--export-html",
        default="",
        dest="export_html",
        metavar="PATH",
        help="Write a self-contained HTML report to PATH after the run.",
    )
    args = parser.parse_args()

    if bool(args.dataset) == bool(args.dataset_id):
        print("ERROR: pass exactly one of --dataset or --dataset-id", file=sys.stderr)
        sys.exit(1)

    if args.rerank_depths and not args.ablation:
        print("ERROR: --rerank-depths requires --ablation", file=sys.stderr)
        sys.exit(1)

    # Auto-detect /api prefix so the harness works against prod backends too.
    args.backend_url = resolve_backend_base(args.backend_url)

    dataset_label = args.dataset or args.dataset_id
    if args.dataset_id:
        rows = load_golden_by_id(args.backend_url, args.dataset_id)
        # File goldens re-resolve documents via the manifest (ensure_ingested);
        # DB goldens pin source_document_id per question, which goes stale when
        # the document is deleted and re-ingested under a new id. Scoring those
        # rows would produce silent all-zero metrics.
        rows, dead_docs = split_rows_by_document_liveness(
            rows, lambda d: is_document_alive(args.backend_url, d)
        )
        if dead_docs and not rows:
            print(
                f"ERROR: every question in dataset {args.dataset_id} points at a "
                f"deleted document ({', '.join(sorted(dead_docs))}). Re-link the "
                "dataset to the re-ingested document (Quality > dataset row > "
                "Re-link) or regenerate it.",
                file=sys.stderr,
            )
            sys.exit(1)
        if dead_docs:
            print(
                f"NOTE: skipping questions pinned to deleted documents "
                f"({', '.join(sorted(dead_docs))}); {len(rows)} of the dataset's "
                "questions remain evaluable. Re-link the dataset to restore the rest.",
                file=sys.stderr,
            )
    else:
        rows = load_golden(args.dataset)
    if args.max_questions is not None and args.max_questions < len(rows):
        rows = random.Random(42).sample(rows, args.max_questions)
        print(
            f"Sampled {len(rows)} examples (seed=42) from {dataset_label}"
        )
    else:
        print(f"Loaded {len(rows)} examples from {dataset_label}")

    manifest = load_manifest()
    source_to_doc_id: dict[str, str | None] = {}
    unique_sources = {row.get("source_file", "") for row in rows if row.get("source_file")}
    for src in unique_sources:
        doc_id = ensure_ingested(args.backend_url, src, manifest)
        source_to_doc_id[src] = doc_id

    if args.ablation:
        # (label, search-strategy, rerank, rerank-depth, rerank-blend).
        # "rrf+rerank" is the shipped pipeline (blend=None -> server default
        # RERANK_BLEND_ALPHA). "rrf+rerank-ce" pins blend=0 to isolate the pure
        # cross-encoder, so the run always records what the RRF/CE blend buys
        # over CE alone -- the L2 analogue of the rrf-pool recall arm.
        strategy_specs = [
            ("vector", "vector", False, None, None),
            ("fts", "fts", False, None, None),
            ("graph", "graph", False, None, None),
            ("rrf", "rrf", False, None, None),
            ("rrf+rerank-ce", "rrf", True, args.rerank_depth, 0.0),
            ("rrf+rerank", "rrf", True, args.rerank_depth, None),
        ]
        # Depth sweep arms measure the L2 recall ceiling directly: reranked
        # HR@5 is bounded by HR@depth of the RRF pool, so if HR@5 climbs with
        # depth the gap is L1-reachable; if it plateaus the missing documents
        # were never in ANY leg's candidates and no L2 tuning can recover them.
        for depth_str in (s.strip() for s in args.rerank_depths.split(",") if s.strip()):
            depth = int(depth_str)
            strategy_specs.append((f"rrf+rerank@{depth}", "rrf", True, depth, None))
        ablation_metrics: dict[str, dict[str, float]] = {}
        for label, search_strategy, do_rerank, depth, blend in strategy_specs:
            samples: list[dict] = []
            for i, row in enumerate(rows, start=1):
                question = row["question"]
                ground_truth = row["ground_truth_answer"]
                context_hint = row.get("context_hint", "")
                source_file = row.get("source_file", "")
                doc_id = row.get("source_document_id") or source_to_doc_id.get(source_file)

                print(
                    f"  [{label} {i}/{len(rows)}] Searching: {question[:60]}..."
                )
                chunks = search_chunks(
                    args.backend_url,
                    question,
                    doc_id,
                    hyde=args.hyde,
                    rerank=do_rerank or args.rerank,
                    rerank_depth=depth,
                    rerank_threshold=args.rerank_threshold,
                    rerank_blend=blend,
                    strategy=search_strategy,
                )
                samples.append(
                    {
                        "question": question,
                        "answer": ground_truth,
                        "contexts": chunks or [""],
                        "ground_truths": [ground_truth],
                        "context_hint": context_hint,
                        "relevance": row.get("relevance") or [],
                    }
                )
            ablation_metrics[label] = {
                "hit_rate_5": compute_hit_rate_5(samples),
                "mrr": compute_mrr(samples),
                "ndcg_10": compute_ndcg_10(samples),
            }

        # L1 pool recall: Recall@K over the raw RRF pool (no rerank, no fixed-k
        # cut). This is the funnel's recall ceiling stated directly -- a flat
        # reranked HR@5 is ambiguous (gold missing from the pool vs. the
        # cross-encoder failing to lift it); Recall@K separates the two.
        recall_depths = sorted(
            {min(int(d), 200) for d in (s.strip() for s in args.recall_depths.split(",")) if d}
        )
        if recall_depths:
            pool_limit = max(recall_depths)
            pool_samples: list[dict] = []
            for i, row in enumerate(rows, start=1):
                question = row["question"]
                source_file = row.get("source_file", "")
                doc_id = row.get("source_document_id") or source_to_doc_id.get(source_file)
                print(f"  [rrf-pool@{pool_limit} {i}/{len(rows)}] Searching: {question[:60]}...")
                chunks = search_chunks(
                    args.backend_url,
                    question,
                    doc_id,
                    hyde=args.hyde,
                    limit=pool_limit,
                    expand_context=False,
                )
                pool_samples.append(
                    {
                        "question": question,
                        "contexts": chunks or [""],
                        "context_hint": row.get("context_hint", ""),
                        "relevance": row.get("relevance") or [],
                    }
                )
            ablation_metrics["rrf-pool"] = {
                f"recall_{d}": compute_recall_at(pool_samples, d) for d in recall_depths
            }

        metrics = {"ablation_metrics": ablation_metrics}
        # Gate the shipped arm (rrf+rerank, falling back to rrf) -- an ablation
        # run is a measurement of the live pipeline too, not automatically green.
        shipped = ablation_metrics.get("rrf+rerank") or ablation_metrics.get("rrf") or {}
        gate = thresholds_for_dataset(dataset_label)
        passed = (
            shipped.get("hit_rate_5", 0.0) >= gate["hit_rate_5"]
            and shipped.get("mrr", 0.0) >= gate["mrr"]
        )
        history_model = args.model or args.judge_model or "no-llm"
        _lib_append_history(dataset_label, history_model, metrics, passed, eval_kind="ablation")
        print_ablation_table(dataset_label, history_model, ablation_metrics)
        _lib_store_results(
            args.backend_url,
            dataset_label,
            history_model,
            metrics,
            eval_kind="ablation",
        )
        return

    # Parallel /search (+ optional /qa) per row. Backend FastAPI handlers are
    # async-safe; cap concurrency so we don't overwhelm a local Ollama judge.
    # A judge always implies real /qa answers: judging the golden ground truth
    # against retrieved context would self-grade the dataset, not the product.
    needs_qa = bool(args.model or args.check_citations or args.judge_model or args.generate)

    def _process_row(idx_row: tuple[int, dict]) -> dict:
        i, row = idx_row
        question = row["question"]
        ground_truth = row["ground_truth_answer"]
        context_hint = row.get("context_hint", "")
        source_file = row.get("source_file", "")
        doc_id = row.get("source_document_id") or source_to_doc_id.get(source_file)

        print(f"  [{i}/{len(rows)}] Searching: {question[:60]}...")
        chunks = search_chunks(
            args.backend_url,
            question,
            doc_id,
            hyde=args.hyde,
            rerank=args.rerank,
            rerank_depth=args.rerank_depth,
            rerank_threshold=args.rerank_threshold,
        )

        answer = ""
        qa_resp: dict = {}
        # Judged contexts include the chunks /qa actually cited; retrieval
        # metrics stay on the raw search result so HR@5 and MRR measure the
        # same thing in every eval kind. The judge keeps seeing top-5 — the
        # 6-10 tail exists only for nDCG@10, and doubling judge input would
        # change generation scores and cost for no judging benefit.
        ragas_contexts = list(chunks[:5])
        if needs_qa:
            qa_resp = post_qa(args.backend_url, question, args.model, doc_id)
            answer = qa_resp.get("answer", "")
            citations = qa_resp.get("citations", [])
            qa_chunks = [c.get("text", "") for c in citations if isinstance(c, dict)]
            seen = set(ragas_contexts)
            for c in qa_chunks:
                if c and c not in seen:
                    ragas_contexts.append(c)
                    seen.add(c)
        # Distinguish the pipeline DECLINING (not_found: a real product answer,
        # "I don't know") from the harness failing to get any response at all
        # (timeout / error / no done event). Both yield an empty answer and are
        # excluded from generation metrics, but they mean opposite things.
        not_found = bool(qa_resp.get("not_found")) if needs_qa else False
        return {
            "question": question,
            "answer": answer,
            "contexts": chunks or [""],
            "ragas_contexts": ragas_contexts or [""],
            "ground_truths": [ground_truth],
            "context_hint": context_hint,
            "relevance": row.get("relevance") or [],
            "qa_response": qa_resp,
            "qa_not_found": not_found,
        }

    # /search alone parallelises fine. /qa does NOT: a local Ollama serves one
    # generation at a time, so concurrent /qa requests queue and the waiting one
    # blows past its timeout (empty answer). Concurrency here buys no throughput,
    # only dropped answers — run generation rows sequentially. (A hosted
    # answering model could parallelise, but the app default is local; correctness
    # over speed for a background batch job.)
    max_workers = 1 if needs_qa else 6
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        samples = list(pool.map(_process_row, enumerate(rows, start=1)))

    hr5 = compute_hit_rate_5(samples)
    mrr = compute_mrr(samples)
    ndcg10 = compute_ndcg_10(samples)

    # An empty answer is either a decline (not_found — a real product outcome)
    # or a genuine failure (timeout/error). Count them apart so the UI never
    # reports an honest "I don't know" as harness breakage.
    qa_empty = [s for s in samples if not s["answer"].strip()] if needs_qa else []
    qa_not_found = sum(1 for s in qa_empty if s.get("qa_not_found"))
    qa_failed = len(qa_empty) - qa_not_found
    if needs_qa and (qa_failed or qa_not_found):
        print(
            f"NOTE: of {len(samples)} questions, the QA pipeline answered "
            f"{len(samples) - len(qa_empty)}, declined (not_found) {qa_not_found}, "
            f"and failed (timeout/error) {qa_failed}. Only answered questions are "
            "judged.",
            file=sys.stderr,
        )

    ragas_scores: dict[str, float | None] = {
        "faithfulness": None,
        "answer_relevance": None,
        "context_precision": None,
        "context_recall": None,
    }
    faithfulness_model: str | None = None

    answered = [
        {**s, "contexts": s["ragas_contexts"]} for s in samples if s["answer"].strip()
    ]

    # NLI faithfulness runs on any generated answer, judge or not.
    if answered:
        print(f"Scoring NLI faithfulness over {len(answered)} generated answers...")
        nli_scores = NliFaithfulnessEval().run(answered)
        ragas_scores["faithfulness"] = nli_scores.get("faithfulness")
        faithfulness_model = nli_scores.get("faithfulness_model")

    judge_attempted = False
    if args.judge_model:
        if not answered:
            print(
                "WARNING: judge skipped -- /qa returned no answers to score.",
                file=sys.stderr,
            )
        else:
            judge_attempted = True
            print(
                f"Running RAGAS judge with model={args.judge_model} "
                f"over {len(answered)} generated answers (answer relevance)..."
            )
            judged_scores = GenerationEval().run(answered, judge_model=args.judge_model)
            # NLI owns faithfulness; take answer_relevance/context_* from the judge.
            judged_scores.pop("faithfulness", None)
            ragas_scores.update(judged_scores)

    citation_support_rate: float | None = None
    if args.check_citations and not args.judge_model:
        print(
            "WARNING: --check-citations requires --judge-model; skipping "
            "citation_support_rate.",
            file=sys.stderr,
        )
        args.check_citations = False
    if args.check_citations:
        citation_pairs: list[tuple[str, str]] = []
        for sample in samples:
            qa_resp = sample.get("qa_response") or {}
            answer_text = qa_resp.get("answer") or sample.get("answer", "")
            citations = qa_resp.get("citations") or []
            for claim, citation_idx in parse_claims_with_citations(answer_text):
                if 0 <= citation_idx < len(citations):
                    citation = citations[citation_idx]
                    if isinstance(citation, dict):
                        chunk = citation.get("text") or citation.get("excerpt") or ""
                        if chunk:
                            citation_pairs.append((claim, chunk))
        citation_support_rate = compute_citation_support_rate(
            citation_pairs,
            judge=lambda claim, chunk: judge_citation(claim, chunk, args.judge_model),
        )

    metrics = {
        "hit_rate_5": hr5,
        "mrr": mrr,
        "ndcg_10": ndcg10,
        **ragas_scores,
        "citation_support_rate": citation_support_rate,
        "rerank": args.rerank,
    }
    if args.rerank and args.rerank_depth is not None:
        metrics["rerank_depth"] = args.rerank_depth
    if args.rerank and args.rerank_threshold is not None:
        metrics["rerank_threshold"] = args.rerank_threshold
    if needs_qa:
        # Provenance: which model authored the judged answers. "app-default"
        # means the product's own /qa pipeline default -- the shipped path.
        metrics["answer_model"] = args.model or "app-default"
        metrics["qa_failed_calls"] = qa_failed
        metrics["qa_not_found_calls"] = qa_not_found
        metrics["qa_answered_calls"] = len(samples) - len(qa_empty)
        metrics["qa_total_calls"] = len(samples)
    if faithfulness_model:
        metrics["faithfulness_model"] = faithfulness_model

    threshold_violations: list[str] = []
    thresholds = thresholds_for_dataset(dataset_label)
    if hr5 < thresholds["hit_rate_5"]:
        threshold_violations.append(f"HR@5 {hr5:.4f} < {thresholds['hit_rate_5']}")
    if mrr < thresholds["mrr"]:
        threshold_violations.append(f"MRR {mrr:.4f} < {thresholds['mrr']}")
    # Faithfulness is report-only pending HHEM re-baseline (distribution differs from RAGAS).
    answer_rel = ragas_scores.get("answer_relevance")
    if answer_rel is not None and answer_rel < thresholds["answer_relevance"]:
        threshold_violations.append(
            f"AnswerRelevance {answer_rel:.4f} < {thresholds['answer_relevance']}"
        )
    if (
        citation_support_rate is not None
        and citation_support_rate < thresholds["citation_support_rate"]
    ):
        threshold_violations.append(
            "CitationSupport "
            f"{citation_support_rate:.4f} < {thresholds['citation_support_rate']}"
        )

    passed = len(threshold_violations) == 0
    violations = threshold_violations if args.assert_thresholds else []

    has_generation_metric = judge_attempted or ragas_scores.get("faithfulness") is not None
    eval_kind = (
        "citation" if args.check_citations
        else "generation" if has_generation_metric
        else "retrieval"
    )
    history_model = args.model or args.judge_model or "no-llm"

    _lib_append_history(dataset_label, history_model, metrics, passed, eval_kind=eval_kind)

    print_table(dataset_label, history_model, metrics)

    if args.export_html:
        _export_html_report(
            path=args.export_html,
            dataset=dataset_label,
            model=history_model,
            metrics=metrics,
            samples=samples,
            eval_kind=eval_kind,
            passed=passed,
            violations=threshold_violations,
        )

    n_questions = len(samples)
    # context_precision / context_recall are intentionally skipped now (they
    # duplicate HR@5/MRR signal). Don't surface a warning for them.
    if answered and metrics.get("faithfulness") is None:
        print(
            "\nWARNING: generated answers existed but faithfulness is null -- "
            "the NLI model failed to load or score. Scroll up for the reason.",
            file=sys.stderr,
        )
    if args.judge_model and metrics.get("answer_relevance") is None:
        print(
            "\nWARNING: judge_model was set but answer_relevance is null. Scroll "
            "up for per-metric WARNING/NOTE lines explaining why.",
            file=sys.stderr,
        )
    if args.check_citations and metrics.get("citation_support_rate") is None:
        print(
            "WARNING: --check-citations was set but citation_support_rate is "
            "null. Most common cause: the QA endpoint did not emit [N]-style "
            "citation markers in answers.",
            file=sys.stderr,
        )
    print(f"\nEvaluated {n_questions} questions.", file=sys.stderr)

    _lib_store_results(
        args.backend_url, dataset_label, history_model, metrics, eval_kind=eval_kind
    )

    if violations:
        print("\nQUALITY GATE FAILED:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
