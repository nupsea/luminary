"""RAGAS evaluation runner for Luminary golden datasets.

Usage::
    # Standard eval (uses /search for retrieval quality, no LLM required)
    uv run python run_eval.py --dataset book
    uv run python run_eval.py --dataset paper --backend-url http://localhost:8000

    # With LLM-based RAGAS scoring
    uv run python run_eval.py --dataset book --model ollama/mistral

Documents are auto-ingested on first run and their IDs cached in
evals/golden/manifest.json.  Re-runs skip ingestion.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

GOLDEN_DIR = Path(__file__).parent / "golden"
MANIFEST_PATH = GOLDEN_DIR / "manifest.json"
VALID_DATASETS = ["book", "paper", "conversation", "notes", "code"]

# Path to the repo root (two levels up from evals/)
REPO_ROOT = Path(__file__).parent.parent


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
                f"{backend_url}/ingest",
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
    """Run GET /search and return a list of chunk texts (up to top 5)."""
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


def compute_hit_rate_5(samples: list[dict]) -> float:
    """HR@5: fraction of questions where context_hint substring is in top-5 retrieved chunks."""
    if not samples:
        return 0.0
    hits = 0
    for s in samples:
        context_hint = s.get("context_hint", "").lower().strip()
        if not context_hint:
            # Fall back to ground truth prefix if no context_hint
            context_hint = s.get("ground_truths", [""])[0].lower()[:50]
        chunks = s.get("contexts", [])[:5]
        if any(context_hint[:80] in ctx.lower() for ctx in chunks):
            hits += 1
    return hits / len(samples)


def compute_mrr(samples: list[dict]) -> float:
    """MRR: mean reciprocal rank of first chunk containing context_hint."""
    if not samples:
        return 0.0
    reciprocal_ranks = []
    for s in samples:
        context_hint = s.get("context_hint", "").lower().strip()
        if not context_hint:
            context_hint = s.get("ground_truths", [""])[0].lower()[:50]
        chunks = s.get("contexts", [])
        rank = None
        for i, ctx in enumerate(chunks, start=1):
            if context_hint[:80] in ctx.lower():
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
        choices=VALID_DATASETS,
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

    print_table(args.dataset, args.model or "no-llm", metrics)
    store_results(args.backend_url, args.dataset, args.model or "no-llm", metrics)


if __name__ == "__main__":
    main()
