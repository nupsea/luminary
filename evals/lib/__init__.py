"""Shared evaluation library for Luminary golden datasets.

Public API used by run_eval.py and future eval runners (S214-S218).
"""

from evals.lib.loader import load_golden
from evals.lib.citation_metrics import (
    compute_citation_support_rate,
    judge_citation,
    parse_claims_with_citations,
)
from evals.lib.flashcard_metrics import (
    compute_atomicity,
    compute_clarity_avg,
    compute_factuality,
    judge_flashcard,
    score_flashcards,
)
from evals.lib.intent_metrics import (
    compute_per_route_precision_recall,
    compute_routing_accuracy,
    normalize_route,
)
from evals.lib.retrieval_metrics import compute_hit_rate_5, compute_mrr
from evals.lib.runners import ClassifierEval, GenerationEval, RetrievalEval
from evals.lib.schemas import (
    FlashcardGoldenEntry,
    GoldenEntry,
    IntentGoldenEntry,
    RetrievalGoldenEntry,
    SummaryGoldenEntry,
)
from evals.lib.scoring_history import append_history
from evals.lib.store import store_results
from evals.lib.summary_metrics import (
    compute_conciseness_pct,
    compute_no_hallucination,
    compute_theme_coverage,
    judge_hallucination_counts,
)

__all__ = [
    "ClassifierEval",
    "FlashcardGoldenEntry",
    "GenerationEval",
    "GoldenEntry",
    "IntentGoldenEntry",
    "RetrievalEval",
    "RetrievalGoldenEntry",
    "SummaryGoldenEntry",
    "append_history",
    "compute_citation_support_rate",
    "compute_atomicity",
    "compute_clarity_avg",
    "compute_factuality",
    "compute_per_route_precision_recall",
    "compute_routing_accuracy",
    "compute_hit_rate_5",
    "compute_mrr",
    "compute_conciseness_pct",
    "compute_no_hallucination",
    "compute_theme_coverage",
    "judge_citation",
    "judge_flashcard",
    "judge_hallucination_counts",
    "load_golden",
    "normalize_route",
    "parse_claims_with_citations",
    "score_flashcards",
    "store_results",
]
