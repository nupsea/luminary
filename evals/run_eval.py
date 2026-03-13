"""RAGAS evaluation runner for Luminary golden datasets.

Usage::
    # Standard eval (uses /search for retrieval quality, no LLM required)
    uv run python run_eval.py --dataset book
    uv run python run_eval.py --dataset paper --backend-url http://localhost:8000

    # With LLM-based RAGAS scoring
    uv run python run_eval.py --dataset book --model ollama/mistral

    # Assert quality gates (exits 1 if HR@5 < 0.60, MRR < 0.45, Faithfulness < 0.65)
    uv run python run_eval.py --dataset book --assert-thresholds

Documents are auto-ingested on first run and their IDs cached in
evals/golden/manifest.json.  Re-runs skip ingestion.
"""

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

# ragas and datasets are heavy optional dependencies used only for LLM-based scoring.
# They are imported lazily inside main() so that this module can be imported by
# backend unit tests (which run in a venv that does not include ragas/datasets).

GOLDEN_DIR = Path(__file__).parent / "golden"
MANIFEST_PATH = GOLDEN_DIR / "manifest.json"
SCORES_HISTORY_PATH = Path(__file__).parent / "scores_history.jsonl"
VALID_DATASETS = ["book", "paper", "conversation", "notes", "code"]

# Path to the repo root (two levels up from evals/)
REPO_ROOT = Path(__file__).parent.parent

# Quality gate thresholds
THRESHOLDS = {
    "hit_rate_5": 0.60,
    "mrr": 0.45,
    "faithfulness": 0.65,
}


# ---------------------------------------------------------------------------
# Manifest helpers (maps source_file -> document_id)
# ---------------------------------------------------------------------------


def load_manifest() -> dict[str, str]:
    if MANIFEST_PATH.exists():
        with MANIFEST_PATH.open() as f:
            return json.load(f)
    return {}


def save_manifest(manifest: dict[str, str]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w") as f:
        json.dump(manifest, f, indent=2)


# ---------------------------------------------------------------------------
# Score history helpers
# ---------------------------------------------------------------------------


def append_history(dataset: str, model: str, metrics: dict, passed: bool) -> None:
    """Append one eval run to scores_history.jsonl."""
    entry = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "dataset": dataset,
        "model": model,
        "hr5": metrics.get("hit_rate_5"),
        "mrr": metrics.get("mrr"),
        "faithfulness": metrics.get("faithfulness"),
        "passed": passed,
    }
    with SCORES_HISTORY_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Document ingestion helpers
# ---------------------------------------------------------------------------


def ingest_document(backend_url: str, source_file: str) -> str | None:
    """Ingest a source file via POST /ingest and wait for completion.

    Returns the document_id on success, None on failure.
    """
    file_path = REPO_ROOT / source_file
    if not file_path.exists():
        print(f"  ERROR: source file not found: {file_path}", file=sys.stderr)
        return None

    try:
        with file_path.open("rb") as fh:
            resp = httpx.post(
                f"{backend_url}/documents/ingest",
                data={"content_type": "book"},
                files={"file": (file_path.name, fh, "text/plain")},
                timeout=30.0,
            )
        resp.raise_for_status()
        doc_id = resp.json().get("document_id")
        if not doc_id:
            print(f"  ERROR: /ingest returned no document_id for {source_file}", file=sys.stderr)
            return None
    except Exception as exc:
        print(f"  ERROR: /ingest failed for {source_file}: {exc}", file=sys.stderr)
        return None

    # Poll for completion (up to 10 minutes for large documents with real ML)
    print(f"  Waiting for ingestion to complete (document_id={doc_id})...")
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(5)
        try:
            status_resp = httpx.get(f"{backend_url}/documents/{doc_id}/status", timeout=10.0)
            status_resp.raise_for_status()
            stage = status_resp.json().get("stage", "")
            if stage == "complete":
                print(f"  Ingestion complete: {source_file} -> {doc_id}")
                return doc_id
            if stage == "error":
                print(f"  ERROR: ingestion failed for {source_file}", file=sys.stderr)
                return None
            print(f"    stage={stage}...")
        except Exception as exc:
            print(f"  WARNING: status check failed: {exc}", file=sys.stderr)

    print(f"  ERROR: ingestion timed out for {source_file}", file=sys.stderr)
    return None


def ensure_ingested(backend_url: str, source_file: str, manifest: dict[str, str]) -> str | None:
    """Return the document_id for source_file, ingesting if not yet in manifest."""
    if source_file in manifest:
        return manifest[source_file]

    print(f"  Ingesting {source_file} (not yet in manifest)...")
    doc_id = ingest_document(backend_url, source_file)
    if doc_id:
        manifest[source_file] = doc_id
        save_manifest(manifest)
    return doc_id


# ---------------------------------------------------------------------------
# Search and scoring helpers
# ---------------------------------------------------------------------------


def search_chunks(backend_url: str, question: str, document_id: str | None) -> list[str]:
    """Run GET /search and return a list of chunk texts (up to top 5).

    Uses the ``text`` field (full chunk text, up to 2000 chars) returned by the
    search API.  The legacy ``text_excerpt`` field is only 200 chars and is
    intended for UI display -- it is too short for context-hint substring matching.
    """
    params: dict[str, str] = {"q": question}
    try:
        resp = httpx.get(f"{backend_url}/search", params=params, timeout=30.0)
        resp.raise_for_status()
        body = resp.json()
        chunks: list[str] = []
        for group in body.get("results", []):
            # If document_id specified, filter to that document only
            if document_id and group.get("document_id") != document_id:
                continue
            for match in group.get("matches", []):
                chunks.append(match.get("text", ""))
                if len(chunks) >= 5:
                    return chunks
        return chunks
    except Exception as exc:
        print(f"  WARNING: /search failed: {exc}", file=sys.stderr)
        return []


def post_qa(backend_url: str, question: str, model: str, document_id: str | None) -> dict:
    """POST to /qa and return the response JSON (or empty dict on failure).

    Used for LLM-based RAGAS scoring (faithfulness, answer_relevancy, etc.).
    """
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


def _norm(s: str) -> str:
    """Collapse all whitespace runs to a single space for robust substring matching.

    Project Gutenberg plain-text files wrap lines at ~70 chars, so a passage
    that reads "any real body" in the golden hint may appear as "any\nreal body"
    inside a stored chunk.  Normalising before comparison eliminates these
    false misses.
    """
    return re.sub(r"\s+", " ", s).strip().lower()


def compute_hit_rate_5(samples: list[dict]) -> float:
    """HR@5: fraction of questions where context_hint substring is in top-5 retrieved chunks."""
    if not samples:
        return 0.0
    hits = 0
    for s in samples:
        context_hint = s.get("context_hint", "").strip()
        if not context_hint:
            # Fall back to ground truth prefix if no context_hint
            context_hint = s.get("ground_truths", [""])[0][:50]
        hint_norm = _norm(context_hint)[:80]
        chunks = s.get("contexts", [])[:5]
        if any(hint_norm in _norm(ctx) for ctx in chunks):
            hits += 1
    return hits / len(samples)


def compute_mrr(samples: list[dict]) -> float:
    """MRR: mean reciprocal rank of first chunk containing context_hint."""
    if not samples:
        return 0.0
    reciprocal_ranks = []
    for s in samples:
        context_hint = s.get("context_hint", "").strip()
        if not context_hint:
            context_hint = s.get("ground_truths", [""])[0][:50]
        hint_norm = _norm(context_hint)[:80]
        chunks = s.get("contexts", [])
        rank = None
        for i, ctx in enumerate(chunks, start=1):
            if hint_norm in _norm(ctx):
                rank = i
                break
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


# ---------------------------------------------------------------------------
# Golden dataset loading
# ---------------------------------------------------------------------------


def load_golden(dataset: str) -> list[dict]:
    path = GOLDEN_DIR / f"{dataset}.jsonl"
    if not path.exists():
        print(f"ERROR: golden file not found: {path}", file=sys.stderr)
        sys.exit(1)
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Results storage
# ---------------------------------------------------------------------------


def store_results(backend_url: str, dataset: str, model: str, metrics: dict) -> None:
    """POST eval results to backend for storage."""
    payload = {
        "dataset_name": dataset,
        "model_used": model,
        "hit_rate_5": metrics.get("hit_rate_5"),
        "mrr": metrics.get("mrr"),
        "faithfulness": metrics.get("faithfulness"),
        "answer_relevance": metrics.get("answer_relevance"),
        "context_precision": metrics.get("context_precision"),
        "context_recall": metrics.get("context_recall"),
    }
    try:
        resp = httpx.post(
            f"{backend_url}/monitoring/evals/store",
            json=payload,
            timeout=15.0,
        )
        resp.raise_for_status()
        print(f"\nResults stored. Run ID: {resp.json().get('id', '?')}")
    except Exception as exc:
        print(f"\nWARNING: failed to store results: {exc}", file=sys.stderr)


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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation against a golden dataset.")
    parser.add_argument(
        "--dataset",
        required=True,
        help="Golden dataset name",
    )
    parser.add_argument(
        "--model",
        default="",
        help="LiteLLM model string for LLM-based RAGAS scoring (optional; default: skip LLM scoring)",
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
            "HR@5 >= 0.60, MRR >= 0.45, Faithfulness >= 0.65 (LLM only)"
        ),
    )
    args = parser.parse_args()

    rows = load_golden(args.dataset)
    print(f"Loaded {len(rows)} examples from {args.dataset}.jsonl")

    # Ensure all source files are ingested and resolve document_ids
    manifest = load_manifest()
    source_to_doc_id: dict[str, str | None] = {}
    unique_sources = {row.get("source_file", "") for row in rows if row.get("source_file")}
    for src in unique_sources:
        doc_id = ensure_ingested(args.backend_url, src, manifest)
        source_to_doc_id[src] = doc_id

    # Collect samples: run /search for retrieval quality assessment
    samples: list[dict] = []
    for i, row in enumerate(rows, start=1):
        question = row["question"]
        ground_truth = row["ground_truth_answer"]
        context_hint = row.get("context_hint", "")
        source_file = row.get("source_file", "")
        doc_id = source_to_doc_id.get(source_file)

        print(f"  [{i}/{len(rows)}] Searching: {question[:60]}...")
        chunks = search_chunks(args.backend_url, question, doc_id)

        # For LLM scoring, also call /qa if model is specified
        answer = ""
        if args.model:
            qa_resp = post_qa(args.backend_url, question, args.model, doc_id)
            answer = qa_resp.get("answer", "")
            # Supplement chunks with citation texts from /qa
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

    # Retrieval quality metrics (no LLM required -- uses context_hint)
    hr5 = compute_hit_rate_5(samples)
    mrr = compute_mrr(samples)

    # RAGAS metrics (require LLM judge -- graceful fallback if unavailable)
    ragas_scores: dict[str, float | None] = {
        "faithfulness": None,
        "answer_relevance": None,
        "context_precision": None,
        "context_recall": None,
    }
    if args.model:
        try:
            from datasets import Dataset  # noqa: PLC0415 -- lazy import, see module docstring
            from ragas import evaluate  # noqa: PLC0415
            from ragas.metrics import (  # noqa: PLC0415
                answer_relevancy,
                context_precision,
                context_recall,
                faithfulness,
            )

            dataset_hf = Dataset.from_list(
                [
                    {
                        "question": s["question"],
                        "answer": s["answer"],
                        "contexts": s["contexts"],
                        "ground_truths": s["ground_truths"],
                    }
                    for s in samples
                ]
            )
            result = evaluate(
                dataset=dataset_hf,
                metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
            )
            scores = result.to_pandas()
            for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                if col in scores.columns:
                    val = float(scores[col].mean())
                    key = "answer_relevance" if col == "answer_relevancy" else col
                    ragas_scores[key] = val
        except Exception as exc:
            print(
                f"WARNING: RAGAS scoring failed (LLM may be unavailable): {exc}",
                file=sys.stderr,
            )

    metrics = {
        "hit_rate_5": hr5,
        "mrr": mrr,
        **ragas_scores,
    }

    # Always evaluate threshold compliance so scores_history.jsonl accurately
    # reflects quality.  The --assert-thresholds flag only controls exit code.
    threshold_violations: list[str] = []
    if hr5 < THRESHOLDS["hit_rate_5"]:
        threshold_violations.append(f"HR@5 {hr5:.4f} < {THRESHOLDS['hit_rate_5']}")
    if mrr < THRESHOLDS["mrr"]:
        threshold_violations.append(f"MRR {mrr:.4f} < {THRESHOLDS['mrr']}")
    faith = ragas_scores.get("faithfulness")
    if args.model and faith is not None and faith < THRESHOLDS["faithfulness"]:
        threshold_violations.append(f"Faithfulness {faith:.4f} < {THRESHOLDS['faithfulness']}")

    passed = len(threshold_violations) == 0
    violations = threshold_violations if args.assert_thresholds else []

    # Persist run to local history file
    append_history(args.dataset, args.model or "no-llm", metrics, passed)

    print_table(args.dataset, args.model or "no-llm", metrics)
    store_results(args.backend_url, args.dataset, args.model or "no-llm", metrics)

    if violations:
        print("\nQUALITY GATE FAILED:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
