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
from evals.lib.environment import capture as capture_environment  # noqa: E402
from evals.lib.environment import self_judging  # noqa: E402
from evals.lib.loader import load_golden  # noqa: E402
from evals.lib.manifest import ensure_ingested, load_manifest  # noqa: E402
from evals.lib.runners import NliFaithfulnessEval, _split_claims  # noqa: E402
from evals.lib.schemas import SummaryGoldenEntry  # noqa: E402
from evals.lib.scoring_history import append_history  # noqa: E402
from evals.lib.store import store_results  # noqa: E402
from evals.lib.summary_metrics import (  # noqa: E402
    compute_conciseness_pct,
    compute_no_hallucination,
    compute_theme_coverage,
    judge_hallucination_counts,
)
from evals.run_eval import search_chunks  # noqa: E402

THRESHOLDS = {
    "theme_coverage": 0.70,
    "no_hallucination": 0.85,
}


# Grounding is retrieved per claim rather than read off the front of the file.
# The previous version passed `read_text()[:8000]` -- about 1,500 words -- so
# every claim a summary drew from later in a book was judged against text the
# judge could not see, and a PDF arrived as `%PDF-1.5 /FlateDecode` because raw
# bytes are not what ingestion reads. Both made `no_hallucination` a number
# about the harness rather than the product.
_CHUNKS_PER_CLAIM = 3
_MAX_GROUNDING_CHARS = 12000


def _grounding_for(backend_url: str, doc_id: str, summary: str) -> list[str]:
    """Chunks from this document that bear on this summary's claims.

    Scales to any document: a 43MB manual indexes 135k chunks, so the only
    workable premise is the passages retrieval finds for each claim.
    """
    seen: dict[str, None] = {}
    for claim in _split_claims(summary) or [summary]:
        for text in search_chunks(
            backend_url, claim, doc_id, limit=_CHUNKS_PER_CLAIM, expand_context=False
        ):
            if text and text.strip():
                seen.setdefault(text.strip(), None)
    chunks: list[str] = []
    budget = _MAX_GROUNDING_CHARS
    for text in seen:
        if budget <= 0:
            break
        chunks.append(text[:budget])
        budget -= len(text)
    return chunks


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


# `--force-refresh` regenerates through map-reduce, which is one LLM call per
# batch over a whole document -- minutes on a local model, and longer on a slow
# one. The previous 120s crashed the runner on the first slow document, losing
# every metric for that model while a faster model reported normally.
SUMMARY_REQUEST_TIMEOUT = 900.0


def fetch_summary(
    backend_url: str,
    document_id: str,
    mode: str,
    model: str | None,
    *,
    force_refresh: bool = False,
) -> str:
    """The summary for this document, generated now or replayed from the store.

    Without *force_refresh* the endpoint returns whatever is already stored, so
    the score belongs to the model that wrote it -- which may not be the model
    running. Measured: two different models scored bit-identically on all three
    metrics, because neither of them generated anything.
    """
    payload: dict[str, object] = {"mode": mode}
    if force_refresh:
        payload["force_refresh"] = True
    if model:
        payload["model"] = model
    resp = httpx.post(
        f"{backend_url}/summarize/{document_id}", json=payload, timeout=SUMMARY_REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    return _collect_sse_tokens(resp.text)


def print_table(dataset: str, mode: str, metrics: dict) -> None:
    print(f"\n{'=' * 58}")
    print(f"  Summary evaluation -- dataset={dataset} mode={mode}")
    print(f"{'=' * 58}")
    for key, val in metrics.items():
        if val is None:
            print(f"  {key:<22}  n/a")
        elif isinstance(val, float):
            print(f"  {key:<22}  {val:.4f}")
        else:
            print(f"  {key:<22}  {val}")
    print(f"{'=' * 58}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run summary correctness eval.")
    parser.add_argument("--dataset", default="summaries")
    parser.add_argument("--mode", choices=["one_sentence", "executive", "detailed"], required=True)
    parser.add_argument("--backend-url", default="http://localhost:7820")
    parser.add_argument("--model", default="")
    parser.add_argument("--judge-model", default=get_settings().LITELLM_DEFAULT_MODEL)
    parser.add_argument("--assert-thresholds", action="store_true")
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Skip LLM hallucination judge and report no_hallucination as n/a.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help=(
            "Regenerate each summary instead of scoring the stored one. Required "
            "whenever the number is about the model rather than about the library: "
            "without it the run scores whichever model wrote the summary first."
        ),
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
    failed_docs: list[str] = []
    graded: list[dict] = []
    judge_failures = 0
    for row in rows:
        doc_id = ensure_ingested(args.backend_url, row["source_file"], manifest)
        if not doc_id:
            continue
        try:
            summary = fetch_summary(
                args.backend_url,
                doc_id,
                args.mode,
                args.model or None,
                force_refresh=args.force_refresh,
            )
        except httpx.HTTPError as exc:
            # A hole, counted rather than swallowed: one document that timed out
            # must not discard every other document's score (I-32).
            failed_docs.append(f"{type(exc).__name__}: {str(exc)[:80]}")
            print(f"WARNING: summary failed ({type(exc).__name__}), continuing", file=sys.stderr)
            continue
        theme = compute_theme_coverage(summary, row["expected_themes"])
        concision = compute_conciseness_pct(summary, row["target_length_chars"])
        grounding = _grounding_for(args.backend_url, doc_id, summary)
        graded.append({"answer": summary, "contexts": grounding})
        if args.skip_judge:
            no_hallucination = None
        else:
            try:
                counts = judge_hallucination_counts(
                    "\n\n".join(grounding),
                    summary,
                    args.judge_model,
                )
                no_hallucination = compute_no_hallucination(
                    counts["hallucinated_count"], counts["total_claims"]
                )
            except Exception as exc:
                # A failed judge must NEVER default to a perfect score -- that
                # hides regressions behind API timeouts. Exclude the row instead.
                print(f"WARNING: hallucination judge failed: {exc}", file=sys.stderr)
                judge_failures += 1
                no_hallucination = None
        scored.append(
            {
                "theme_coverage": theme,
                "no_hallucination": no_hallucination,
                "conciseness_pct": concision,
            }
        )

    judged = [s["no_hallucination"] for s in scored if s["no_hallucination"] is not None]
    # Deterministic grounding over the same retrieved passages: no LLM, so it is
    # the one summary number a single-model machine still gets honestly, and it
    # cannot be inflated by a judge scoring its own writing.
    nli = NliFaithfulnessEval().run(graded)
    def _mean_over_measured(key: str) -> float | None:
        """Average the rows that produced a value, and None when none did.

        `sum(s[key] or 0.0 ...) / len(scored)` counted an unmeasurable row as a
        zero, which reports a hole in the measurement as a bad result (I-32).
        """
        vals = [s[key] for s in scored if s.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    metrics = {
        "theme_coverage": _mean_over_measured("theme_coverage"),
        "no_hallucination": sum(judged) / len(judged) if judged else None,
        "conciseness_pct": _mean_over_measured("conciseness_pct"),
        "rows_failed": len(failed_docs),
        "summary_grounding": nli.get("faithfulness"),
        "grounding_model": nli.get("faithfulness_model"),
    }
    if judge_failures:
        print(
            f"WARNING: hallucination judge failed on {judge_failures}/{len(scored)} rows; "
            "no_hallucination is averaged over the judged rows only.",
            file=sys.stderr,
        )

    violations: list[str] = []
    if failed_docs:
        violations.append(
            f"{len(failed_docs)} document(s) could not be summarised: {failed_docs[:2]}"
        )
    # A gated metric that could not be computed fails; it does not pass, and it
    # does not raise on the comparison (I-32).
    if metrics["theme_coverage"] is None:
        violations.append("theme_coverage could not be computed on any row")
    elif metrics["theme_coverage"] < THRESHOLDS["theme_coverage"]:
        violations.append("theme_coverage below threshold")
    if not args.skip_judge and metrics["no_hallucination"] is None:
        violations.append("no_hallucination judge produced no scores")
    elif (
        metrics["no_hallucination"] is not None
        and metrics["no_hallucination"] < THRESHOLDS["no_hallucination"]
    ):
        violations.append("no_hallucination below threshold")
    concision = metrics["conciseness_pct"]
    if concision is None:
        violations.append("conciseness_pct could not be computed on any row")
    elif concision < 0.5 or concision > 1.5:
        violations.append("conciseness_pct outside [0.5, 1.5]")

    passed = len(violations) == 0
    model_name = args.model or args.judge_model or "no-llm"
    environment = capture_environment(
        args.backend_url,
        mode=args.mode,
        judge_model=None if args.skip_judge else args.judge_model,
        skip_judge=bool(args.skip_judge),
        force_refresh=bool(args.force_refresh),
    )
    same_model = self_judging(environment)
    environment["self_judged"] = bool(same_model)
    if same_model:
        print(
            f"  WARNING: {same_model} both wrote and judged these summaries; "
            "no_hallucination is biased upward. summary_grounding is unaffected.",
            file=sys.stderr,
        )
    append_history(
        args.dataset, model_name, metrics, passed, eval_kind="summary", environment=environment
    )
    store_results(args.backend_url, args.dataset, model_name, metrics, eval_kind="summary")
    print_table(args.dataset, args.mode, metrics)

    if args.assert_thresholds and violations:
        for violation in violations:
            print(f"QUALITY GATE FAILED: {violation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
