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

from app.config import get_settings  # noqa: E402
from evals.lib.loader import GoldenValidationError  # noqa: E402
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
    save_manifest,
)
from evals.lib.retrieval_metrics import (  # noqa: E402
    _extract_hint_norms,
    _norm,
    compute_hit_rate_5,
    compute_mrr,
)
from evals.lib.runners import GenerationEval  # noqa: E402
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
    "book_odyssey",
    "book_frankenstein",
    "paper",
    "conversation",
    "notes",
    "code",
]

# Quality gate thresholds
THRESHOLDS = {
    "hit_rate_5": 0.50,
    "mrr": 0.35,
    "faithfulness": 0.65,
    "answer_relevance": 0.50,
}


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
) -> list[str]:
    """Run GET /search and return up to top-5 chunk texts."""
    params: dict[str, str] = {"q": question}
    if document_id:
        params["document_id"] = document_id
        params["limit"] = "20"
    if hyde:
        params["hyde"] = "true"
    if rerank:
        params["rerank"] = "true"
    try:
        request_timeout = 60.0 if (hyde or rerank) else 30.0
        resp = httpx.get(f"{backend_url}/search", params=params, timeout=request_timeout)
        resp.raise_for_status()
        body = resp.json()

        all_matches = []
        for group in body.get("results", []):
            if document_id and group.get("document_id") != document_id:
                continue
            for match in group.get("matches", []):
                all_matches.append(match)

        all_matches.sort(key=lambda m: m.get("relevance_score", 0.0), reverse=True)
        return [m.get("text", "") for m in all_matches[:5]]
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
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"  WARNING: /qa call failed: {exc}", file=sys.stderr)
        return {}


def print_table(dataset: str, model: str, metrics: dict) -> None:
    print(f"\n{'=' * 56}")
    print(f"  RAGAS evaluation -- dataset={dataset}  model={model}")
    print(f"{'=' * 56}")
    for key, val in metrics.items():
        if val is not None:
            print(f"  {key:<22}  {val:.4f}")
        else:
            print(f"  {key:<22}  n/a")
    print(f"{'=' * 56}\n")


__all__ = [
    "GOLDEN_DIR",
    "GoldenEntry",
    "MANIFEST_PATH",
    "REPO_ROOT",
    "SCORES_HISTORY_PATH",
    "THRESHOLDS",
    "VALID_DATASETS",
    "_extract_hint_norms",
    "_norm",
    "append_history",
    "compute_hit_rate_5",
    "compute_mrr",
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
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation against a golden dataset.")
    parser.add_argument("--dataset", required=True, help="Golden dataset name")
    parser.add_argument(
        "--model",
        default="",
        help="LiteLLM model string for LLM-based RAGAS scoring (optional)",
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
        "--judge-model",
        default=get_settings().LITELLM_DEFAULT_MODEL,
        dest="judge_model",
        help=(
            "LiteLLM model string for the RAGAS judge LLM. "
            "Default: get_settings().LITELLM_DEFAULT_MODEL (Ollama-local per I-16). "
            "Pass empty string to disable judge scoring entirely."
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
    args = parser.parse_args()

    rows = load_golden(args.dataset)
    if args.max_questions is not None and args.max_questions < len(rows):
        rows = random.Random(42).sample(rows, args.max_questions)
        print(
            f"Sampled {len(rows)} examples (seed=42) from {args.dataset}.jsonl"
        )
    else:
        print(f"Loaded {len(rows)} examples from {args.dataset}.jsonl")

    manifest = load_manifest()
    source_to_doc_id: dict[str, str | None] = {}
    unique_sources = {row.get("source_file", "") for row in rows if row.get("source_file")}
    for src in unique_sources:
        doc_id = ensure_ingested(args.backend_url, src, manifest)
        source_to_doc_id[src] = doc_id

    samples: list[dict] = []
    for i, row in enumerate(rows, start=1):
        question = row["question"]
        ground_truth = row["ground_truth_answer"]
        context_hint = row.get("context_hint", "")
        source_file = row.get("source_file", "")
        doc_id = source_to_doc_id.get(source_file)

        print(f"  [{i}/{len(rows)}] Searching: {question[:60]}...")
        chunks = search_chunks(
            args.backend_url, question, doc_id, hyde=args.hyde, rerank=args.rerank
        )

        answer = ""
        if args.model:
            qa_resp = post_qa(args.backend_url, question, args.model, doc_id)
            answer = qa_resp.get("answer", "")
            citations = qa_resp.get("citations", [])
            qa_chunks = [c.get("text", "") for c in citations if isinstance(c, dict)]
            seen = set(chunks)
            for c in qa_chunks:
                if c not in seen:
                    chunks.append(c)
                    seen.add(c)

        samples.append(
            {
                "question": question,
                "answer": answer or ground_truth,
                "contexts": chunks or [""],
                "ground_truths": [ground_truth],
                "context_hint": context_hint,
            }
        )

    hr5 = compute_hit_rate_5(samples)
    mrr = compute_mrr(samples)

    ragas_scores: dict[str, float | None] = {
        "faithfulness": None,
        "answer_relevance": None,
        "context_precision": None,
        "context_recall": None,
    }
    if args.judge_model:
        print(f"Running RAGAS judge with model={args.judge_model}...")
        ragas_scores = GenerationEval().run(samples, judge_model=args.judge_model)

    metrics = {
        "hit_rate_5": hr5,
        "mrr": mrr,
        **ragas_scores,
    }

    threshold_violations: list[str] = []
    if hr5 < THRESHOLDS["hit_rate_5"]:
        threshold_violations.append(f"HR@5 {hr5:.4f} < {THRESHOLDS['hit_rate_5']}")
    if mrr < THRESHOLDS["mrr"]:
        threshold_violations.append(f"MRR {mrr:.4f} < {THRESHOLDS['mrr']}")
    faith = ragas_scores.get("faithfulness")
    if faith is not None and faith < THRESHOLDS["faithfulness"]:
        threshold_violations.append(f"Faithfulness {faith:.4f} < {THRESHOLDS['faithfulness']}")
    answer_rel = ragas_scores.get("answer_relevance")
    if answer_rel is not None and answer_rel < THRESHOLDS["answer_relevance"]:
        threshold_violations.append(
            f"AnswerRelevance {answer_rel:.4f} < {THRESHOLDS['answer_relevance']}"
        )

    passed = len(threshold_violations) == 0
    violations = threshold_violations if args.assert_thresholds else []

    judge_ran = args.judge_model and any(v is not None for v in ragas_scores.values())
    eval_kind = "generation" if judge_ran else "retrieval"
    history_model = args.model or args.judge_model or "no-llm"

    _lib_append_history(args.dataset, history_model, metrics, passed, eval_kind=eval_kind)

    print_table(args.dataset, history_model, metrics)
    _lib_store_results(
        args.backend_url, args.dataset, history_model, metrics, eval_kind=eval_kind
    )

    if violations:
        print("\nQUALITY GATE FAILED:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
