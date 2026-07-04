"""Evaluate document topic generation against a curated golden topic list.

Document-agnostic: `--dataset NAME` loads evals/golden/topics/NAME.json (the
reference topics for some ingested document), fetches the app's generated topics
via GET /topics/{document_id}, and reports precision / recall / F1 plus
junk_rate (boilerplate / non-topics that leaked in).

Usage:
    uv run python evals/run_topic_eval.py --dataset d2l --backend-url http://localhost:7820
    uv run python evals/run_topic_eval.py --dataset d2l --assert-thresholds
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.services.topic_service import is_junk_heading  # noqa: E402
from evals.lib.manifest import ensure_ingested, load_manifest, resolve_backend_base  # noqa: E402
from evals.lib.scoring_history import append_history  # noqa: E402
from evals.lib.store import store_results  # noqa: E402
from evals.lib.topic_metrics import compute_topic_metrics  # noqa: E402

GOLDEN_DIR = _REPO_ROOT / "evals" / "golden" / "topics"

# Generic gates (not tuned to any one document).
THRESHOLDS = {"topic_f1_min": 0.70, "junk_rate_max": 0.15}


def load_topic_golden(dataset: str) -> dict:
    path = GOLDEN_DIR / f"{dataset}.json"
    if not path.exists():
        print(f"ERROR: no topic golden at {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_topics(backend_url: str, document_id: str) -> list[str]:
    resp = httpx.get(f"{backend_url}/topics/{document_id}", timeout=60.0)
    resp.raise_for_status()
    return [t["title"] for t in resp.json().get("topics", []) if t.get("title")]


def main() -> None:
    ap = argparse.ArgumentParser(description="Topic-generation eval.")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--backend-url", default="http://localhost:7820", dest="backend_url")
    ap.add_argument("--assert-thresholds", action="store_true", dest="assert_thresholds")
    args = ap.parse_args()

    args.backend_url = resolve_backend_base(args.backend_url)
    golden = load_topic_golden(args.dataset)
    expected = golden["expected_topics"]
    source_file = golden["source_file"]

    manifest = load_manifest()
    doc_id = ensure_ingested(args.backend_url, source_file, manifest)
    if not doc_id:
        print(f"ERROR: could not ingest/resolve {source_file}", file=sys.stderr)
        sys.exit(1)

    predicted = fetch_topics(args.backend_url, doc_id)
    metrics = compute_topic_metrics(predicted, expected, junk_predicate=is_junk_heading)

    print(f"\n{'=' * 56}")
    print(f"  Topic eval -- dataset={args.dataset}")
    print(f"{'=' * 56}")
    for k, v in metrics.items():
        print(f"  {k:<18}  {v:.4f}" if isinstance(v, float) else f"  {k:<18}  {v}")
    print(f"  predicted topics: {predicted}")
    print(f"{'=' * 56}\n")

    violations: list[str] = []
    if metrics["topic_f1"] < THRESHOLDS["topic_f1_min"]:
        violations.append(f"topic_f1 {metrics['topic_f1']:.3f} < {THRESHOLDS['topic_f1_min']}")
    if metrics["junk_rate"] > THRESHOLDS["junk_rate_max"]:
        violations.append(f"junk_rate {metrics['junk_rate']:.3f} > {THRESHOLDS['junk_rate_max']}")

    passed = not violations
    append_history(args.dataset, "no-llm", metrics, passed, eval_kind="topic")
    store_results(args.backend_url, args.dataset, "no-llm", metrics, eval_kind="topic")

    if violations and args.assert_thresholds:
        print("QUALITY GATE FAILED:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
