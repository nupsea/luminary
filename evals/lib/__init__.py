"""Shared evaluation library for Luminary golden datasets.

Public API used by run_eval.py and future eval runners (S214-S218).
"""

from evals.lib.loader import load_golden
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
    "compute_hit_rate_5",
    "compute_mrr",
    "load_golden",
    "store_results",
]
