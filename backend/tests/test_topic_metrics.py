"""Unit tests for topic-generation eval metrics (evals.lib.topic_metrics)."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.topic_metrics import compute_topic_metrics, titles_match  # noqa: E402


def test_titles_match_exact_and_fuzzy():
    assert titles_match("Convolutional Neural Networks", "convolutional neural networks")
    assert titles_match("Optimization Algorithms for Training", "Optimization Algorithms")
    assert titles_match("Linear Neural Networks for Regression", "Linear Regression Networks")
    assert not titles_match("Attention Mechanisms", "Recurrent Neural Networks")
    # single significant token must NOT match a multi-token topic (avoids
    # "Networks" matching every *-Networks chapter)
    assert not titles_match("Optimization Algorithms", "Optimization")


def test_perfect_match_scores_one():
    golden = ["Introduction", "Multilayer Perceptrons", "Optimization Algorithms"]
    m = compute_topic_metrics(list(golden), golden)
    assert m["topic_precision"] == 1.0
    assert m["topic_recall"] == 1.0
    assert m["topic_f1"] == 1.0
    assert m["junk_rate"] == 0.0


def test_junk_and_missing_topics_penalised():
    golden = ["Introduction", "Multilayer Perceptrons", "Optimization Algorithms"]
    predicted = ["Introduction", "Copyright", "Index"]  # 1 hit, 2 junk, 2 missing

    def junk(t: str) -> bool:
        return t.lower() in {"copyright", "index", "table of contents"}

    m = compute_topic_metrics(predicted, golden, junk_predicate=junk)
    assert m["n_matched"] == 1
    assert abs(m["topic_precision"] - 1 / 3) < 1e-9
    assert abs(m["topic_recall"] - 1 / 3) < 1e-9
    assert abs(m["junk_rate"] - 2 / 3) < 1e-9


def test_no_double_counting_duplicate_predictions():
    golden = ["Optimization Algorithms"]
    predicted = ["Optimization Algorithms", "Optimization"]  # both could match the one golden
    m = compute_topic_metrics(predicted, golden)
    assert m["n_matched"] == 1
    assert m["topic_recall"] == 1.0
    assert m["topic_precision"] == 0.5
