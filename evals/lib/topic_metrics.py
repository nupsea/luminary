"""Topic-generation eval metrics (document-agnostic).

Measures how well a document's generated study topics match a curated golden
list: precision / recall / F1 under fuzzy title matching, plus junk_rate (the
fraction of generated topics that are boilerplate / non-topics — the failure
mode where index/TOC/sample-data leak in as "topics").
"""

from __future__ import annotations

import re
from collections.abc import Callable

_TOPIC_STOPWORDS = frozenset(
    "a an the of for to and or in on with into from as is are how introduction".split()
)


def _tokens(title: str) -> set[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()
    return {w for w in words if w not in _TOPIC_STOPWORDS and len(w) > 1}


def titles_match(a: str, b: str) -> bool:
    """Fuzzy topic-title match: exact, strong token overlap, or containment."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return a.strip().lower() == b.strip().lower()
    if ta == tb:
        return True
    inter = len(ta & tb)
    union = len(ta | tb)
    if union and inter / union >= 0.6:
        return True
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(smaller) >= 2 and smaller <= larger


def compute_topic_metrics(
    predicted: list[str],
    golden: list[str],
    *,
    junk_predicate: Callable[[str], bool] | None = None,
) -> dict[str, float | int]:
    """Greedy 1:1 matching of predicted topics to golden topics."""
    remaining = list(golden)
    matched_predicted = 0
    for p in predicted:
        for i, g in enumerate(remaining):
            if titles_match(p, g):
                matched_predicted += 1
                remaining.pop(i)
                break

    matched_golden = len(golden) - len(remaining)
    n_pred = len(predicted)
    n_gold = len(golden)
    precision = matched_predicted / n_pred if n_pred else 0.0
    recall = matched_golden / n_gold if n_gold else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    junk = sum(1 for p in predicted if junk_predicate(p)) if junk_predicate else 0
    return {
        "topic_precision": precision,
        "topic_recall": recall,
        "topic_f1": f1,
        "junk_rate": junk / n_pred if n_pred else 0.0,
        "n_predicted": n_pred,
        "n_golden": n_gold,
        "n_matched": matched_predicted,
    }
