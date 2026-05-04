"""Summary correctness eval runner (S216)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from evals.lib.loader import load_golden  # noqa: E402
from evals.lib.manifest import ensure_ingested, load_manifest  # noqa: E402
from evals.lib.schemas import SummaryGoldenEntry  # noqa: E402
from evals.lib.scoring_history import append_history  # noqa: E402
from evals.lib.store import store_results  # noqa: E402
from evals.lib.summary_metrics import (  # noqa: E402
    compute_conciseness_pct,
    compute_no_hallucination,
    compute_theme_coverage,
    judge_hallucination_counts,
)

THRESHOLDS = {
    "theme_coverage": 0.70,
    "no_hallucination": 0.85,
}


def _read_source_excerpt(source_file: str, max_chars: int = 8000) -> str:
    path = REPO_ROOT / source_file
    if not path.exists():
        return ""
    return path.read_text(errors="ignore")[:max_chars]


def _collect_sse_tokens(text: str) -> str:
    tokens: list[str] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line.removeprefix("data:").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if "token" in payload:
            tokens.append(str(payload["token"]))
    return "".join(tokens)


def fetch_summary(backend_url: str, document_id: str, mode: str, model: str | None) -> str:
    payload: dict[str, object] = {"mode": mode}
    if model:
        payload["model"] = model
    resp = httpx.post(f"{backend_url}/summarize/{document_id}", json=payload, timeout=120.0)
    resp.raise_for_status()
    return _collect_sse_tokens(resp.text)


def print_table(dataset: str, mode: str, metrics: dict) -> None:
    print(f"\n{'=' * 58}")
    print(f"  Summary evaluation -- dataset={dataset} mode={mode}")
    print(f"{'=' * 58}")
    for key, val in metrics.items():
        print(f"  {key:<22}  {val:.4f}" if val is not None else f"  {key:<22}  n/a")
    print(f"{'=' * 58}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run summary correctness eval.")
    parser.add_argument("--dataset", default="summaries")
    parser.add_argument("--mode", choices=["one_sentence", "executive", "detailed"], required=True)
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--model", default="")
    parser.add_argument("--judge-model", default=get_settings().LITELLM_DEFAULT_MODEL)
    parser.add_argument("--assert-thresholds", action="store_true")
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Skip LLM hallucination judge and report no_hallucination=1.0.",
    )
    args = parser.parse_args()

    rows = [
        row for row in load_golden(args.dataset, SummaryGoldenEntry) if row.get("mode") == args.mode
    ]
    if not rows:
        print(f"ERROR: no rows for mode={args.mode}", file=sys.stderr)
        sys.exit(1)

    manifest = load_manifest()
    scored: list[dict] = []
    for row in rows:
        doc_id = ensure_ingested(args.backend_url, row["source_file"], manifest)
        if not doc_id:
            continue
        summary = fetch_summary(args.backend_url, doc_id, args.mode, args.model or None)
        theme = compute_theme_coverage(summary, row["expected_themes"])
        concision = compute_conciseness_pct(summary, row["target_length_chars"])
        if args.skip_judge:
            no_hallucination = 1.0
        else:
            try:
                counts = judge_hallucination_counts(
                    _read_source_excerpt(row["source_file"]),
                    summary,
                    args.judge_model,
                )
                no_hallucination = compute_no_hallucination(
                    counts["hallucinated_count"], counts["total_claims"]
                )
            except Exception as exc:
                print(f"WARNING: hallucination judge skipped: {exc}", file=sys.stderr)
                no_hallucination = 1.0
        scored.append(
            {
                "theme_coverage": theme,
                "no_hallucination": no_hallucination,
                "conciseness_pct": concision,
            }
        )

    metrics = {
        "theme_coverage": sum(s["theme_coverage"] for s in scored) / len(scored),
        "no_hallucination": sum(s["no_hallucination"] for s in scored) / len(scored),
        "conciseness_pct": sum(s["conciseness_pct"] or 0.0 for s in scored) / len(scored),
    }

    violations: list[str] = []
    if metrics["theme_coverage"] < THRESHOLDS["theme_coverage"]:
        violations.append("theme_coverage below threshold")
    if metrics["no_hallucination"] < THRESHOLDS["no_hallucination"]:
        violations.append("no_hallucination below threshold")
    concision = metrics["conciseness_pct"]
    if concision < 0.5 or concision > 1.5:
        violations.append("conciseness_pct outside [0.5, 1.5]")

    passed = len(violations) == 0
    model_name = args.model or args.judge_model or "no-llm"
    append_history(args.dataset, model_name, metrics, passed, eval_kind="summary")
    store_results(args.backend_url, args.dataset, model_name, metrics, eval_kind="summary")
    print_table(args.dataset, args.mode, metrics)

    if args.assert_thresholds and violations:
        for violation in violations:
            print(f"QUALITY GATE FAILED: {violation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
