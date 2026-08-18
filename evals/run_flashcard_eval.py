"""Flashcard correctness eval runner (S217)."""

from __future__ import annotations

import argparse
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
from evals.lib.environment import output_stats, self_judging, stats_delta  # noqa: E402
from evals.lib.flashcard_metrics import (  # noqa: E402
    judge_flashcard,
    score_flashcards,
    score_structural,
)
from evals.lib.loader import load_golden  # noqa: E402
from evals.lib.manifest import ensure_ingested, load_manifest  # noqa: E402
from evals.lib.schemas import FlashcardGoldenEntry  # noqa: E402
from evals.lib.scoring_history import append_history  # noqa: E402
from evals.lib.store import store_results  # noqa: E402

THRESHOLDS = {"factuality": 0.85, "atomicity": 0.80, "clarity_avg": 3.5}


# One request generates several cards, and a slow local model re-prompts to
# backfill the ones its first pass did not deliver -- so this is minutes, not
# seconds, and it is a background batch job. The previous 120s crashed the whole
# runner on the first slow row: every metric for that model was lost while a
# faster model on the same hardware reported normally, which reads as "the model
# produced nothing" rather than "the harness gave up". Matches
# `run_eval.QA_REQUEST_TIMEOUT` deliberately.
GENERATE_REQUEST_TIMEOUT = 600.0


def generate_cards(backend_url: str, document_id: str, row: dict) -> list[dict]:
    payload = {
        "document_id": document_id,
        "scope": "full",
        "count": row.get("expected_card_count") or 1,
        "context": row["chunk_id_or_text"],
    }
    resp = httpx.post(
        f"{backend_url}/flashcards/generate", json=payload, timeout=GENERATE_REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()


def print_table(dataset: str, metrics: dict) -> None:
    print(f"\n{'=' * 58}")
    print(f"  Flashcard evaluation -- dataset={dataset}")
    print(f"{'=' * 58}")
    for key, val in metrics.items():
        if val is None:
            print(f"  {key:<22}  n/a")
        elif isinstance(val, float):
            print(f"  {key:<22}  {val:.4f}")
        elif isinstance(val, dict):
            print(f"  {key:<22}  {', '.join(f'{k} {v}' for k, v in sorted(val.items()))}")
        else:
            print(f"  {key:<22}  {val}")
    print(f"{'=' * 58}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run flashcard correctness eval.")
    parser.add_argument("--dataset", default="flashcards")
    parser.add_argument("--backend-url", default="http://localhost:7820")
    parser.add_argument("--judge-model", default=get_settings().LITELLM_DEFAULT_MODEL)
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help=(
            "Skip the LLM judge and report the structural half only: how many "
            "cards were asked for against how many arrived, and what the "
            "parser had to repair. Those are deterministic and model-sensitive, "
            "which is what gates a model swap -- the judged scores are neither."
        ),
    )
    parser.add_argument("--assert-thresholds", action="store_true")
    args = parser.parse_args()

    rows = load_golden(args.dataset, FlashcardGoldenEntry)
    manifest = load_manifest()
    stats_before = output_stats(args.backend_url)

    per_row: list[dict] = []
    per_kind: dict[str, list[dict]] = {}
    requested = delivered = 0
    skipped: list[str] = []
    failed_rows: list[str] = []

    for row in rows:
        # Rows sampled from the live index name their document; only a row that
        # does not gets ingested from disk.
        doc_id = row.get("source_document_id") or ensure_ingested(
            args.backend_url, row["source_file"], manifest
        )
        if not doc_id:
            skipped.append(row["question"][:60])
            continue
        try:
            cards = generate_cards(args.backend_url, doc_id, row)
        except httpx.HTTPError as exc:
            # One row that timed out or errored is a hole in the measurement, not
            # a reason to throw away every other row. Counted rather than
            # swallowed: `rows_failed` is reported, and asserted runs fail on it
            # (I-32 -- requested-but-uncomputed is a failure, never a pass).
            failed_rows.append(f"{type(exc).__name__}: {str(exc)[:80]}")
            print(f"WARNING: row failed ({type(exc).__name__}), continuing", file=sys.stderr)
            continue
        requested += int(row.get("expected_card_count") or 1)
        delivered += len(cards)
        scored = {"cards": len(cards), "requested": int(row.get("expected_card_count") or 1)}
        # Computed whether or not the judge runs: it needs no model, and the matrix
        # -- which always skips the judge -- would otherwise never see it.
        scored |= score_structural(cards)
        if not args.skip_judge:
            scored |= score_flashcards(
                cards,
                row["chunk_id_or_text"],
                judge=lambda card, chunk: judge_flashcard(card, chunk, args.judge_model),
            )
        per_row.append(scored)
        per_kind.setdefault(row.get("content_type") or "?", []).append(scored)

    if not per_row:
        print("ERROR: no rows produced cards", file=sys.stderr)
        sys.exit(1)

    def _mean(key: str, rowset: list[dict]) -> float | None:
        # A judge that failed yields None, and averaging it as 0.0 would report
        # a broken judge as a bad model (I-32).
        vals = [r[key] for r in rowset if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    metrics: dict[str, object] = {
        "cards_requested": requested,
        # What the API returned. NOT a property of the model: a near-duplicate
        # filter drops candidates that resemble cards the document already has,
        # so the same passage yields fewer cards on every re-run and eventually
        # none. Proven: two identical calls after one eval run both returned 0.
        "cards_returned": delivered,
        "rows_scored": len(per_row),
        # A hole in the measurement, stated rather than averaged away.
        "rows_failed": len(failed_rows),
    }
    metrics["atomicity"] = _mean("atomicity", per_row)
    if not args.skip_judge:
        metrics |= {
            "factuality": _mean("factuality", per_row),
            "clarity_avg": _mean("clarity_avg", per_row),
        }

    moved = stats_delta(stats_before, output_stats(args.backend_url))
    if moved and moved["counts"]:
        counts = moved["counts"]
        metrics["output_repairs"] = counts
        metrics["first_pass_rate"] = moved["first_pass_rate"]
        # The model's own number: cards it produced before the library-state
        # filter saw them. This is the one that may be compared across models.
        produced = counts.get("items_delivered")
        if produced is not None and requested:
            metrics["cards_generated"] = produced
            metrics["generation_rate"] = produced / requested
        metrics["cards_deduped"] = counts.get("items_deduped", 0)
        # The deterministic gate's verdict, which the product computed and threw
        # away: every rejection is something the prompt explicitly forbids, so
        # this reads instruction-following with no judge in the loop.
        gated = counts.get("cards_gated", 0)
        if gated:
            metrics["cards_gated"] = gated
            metrics["cards_rejected"] = counts.get("cards_rejected", 0)
            metrics["card_reject_rate"] = counts.get("cards_rejected", 0) / gated
        # The product's own factuality gate, when one is configured. Reported as
        # three counts rather than a pass rate: a checker that was unreachable for
        # the whole run would otherwise be indistinguishable from one that passed
        # every card.
        checked = counts.get("factuality_checked", 0)
        if checked:
            metrics["factuality_checked"] = checked
            for state in ("supported", "unsupported", "unverifiable"):
                metrics[f"factuality_{state}"] = counts.get(f"factuality_{state}", 0)
            metrics["factuality_reject_rate"] = (
                counts.get("factuality_unsupported", 0) / checked
            )
        parses = counts.get("parses", 0)
        if parses:
            metrics["shape_deviation_rate"] = counts.get("shape_deviations", 0) / parses

    environment = capture_environment(
        args.backend_url,
        judge_model=None if args.skip_judge else args.judge_model,
        skip_judge=bool(args.skip_judge),
    )
    same_model = self_judging(environment)
    environment["self_judged"] = bool(same_model)
    if same_model:
        print(
            f"  WARNING: {same_model} both wrote and judged these cards; "
            "the judged scores are biased upward. Delivery and repair counts are not.",
            file=sys.stderr,
        )

    violations = [
        f"{key} {metrics[key]:.4f} < {threshold}"
        for key, threshold in THRESHOLDS.items()
        if isinstance(metrics.get(key), float) and metrics[key] < threshold
    ]
    # Requested-but-uncomputed is a violation, not a skip.
    if not args.skip_judge:
        violations += [
            f"{key} was requested but never computed"
            for key in THRESHOLDS
            if metrics.get(key) is None
        ]
    if skipped:
        violations.append(f"{len(skipped)} row(s) had no document: {skipped[:3]}")
    if failed_rows:
        violations.append(
            f"{len(failed_rows)} row(s) could not be generated: {failed_rows[:2]}"
        )

    passed = len(violations) == 0
    model_name = "no-judge" if args.skip_judge else args.judge_model
    append_history(
        args.dataset, model_name, metrics, passed, eval_kind="flashcard", environment=environment
    )
    store_results(args.backend_url, args.dataset, model_name, metrics, eval_kind="flashcard")
    print_table(args.dataset, metrics)

    print(f"  {'content type':<16} {'rows':>5} {'returned/requested':>20}")
    for kind in sorted(per_kind):
        rowset = per_kind[kind]
        got = sum(r["cards"] for r in rowset)
        want = sum(r["requested"] for r in rowset)
        judged = _mean("factuality", rowset)
        suffix = "" if judged is None else f"   factuality {judged:.2f}"
        print(f"  {kind:<16} {len(rowset):>5} {got:>10}/{want:<9}{suffix}")
    print()

    if args.assert_thresholds and violations:
        for violation in violations:
            print(f"QUALITY GATE FAILED: {violation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
