"""Deterministic graded-relevance discovery for golden generation.

Builds the ``relevance`` field consumed by nDCG@10: the passage the answer was
authored from is grade 2; other source chunks that state the same answer text
verbatim contribute grade-1 secondary passages. No LLM involved, so the output
is reproducible and document-agnostic.
"""

import re

from evals.lib.retrieval_metrics import _hint_key, _norm

# Answers shorter than this (normalised) are too generic to locate secondary
# passages by text match — a one-word answer like "hedgehog" would mark every
# mention in the book as relevant, which is noise, not relevance.
_MIN_ANSWER_CHARS = 15
_SNIPPET_CHARS = 120


def _answer_pattern(answer: str) -> re.Pattern | None:
    words = [re.escape(w) for w in answer.split() if w]
    if not words:
        return None
    return re.compile(r"\s+".join(words), re.IGNORECASE)


def find_graded_relevance(
    context_hint: str,
    answer: str,
    own_chunk: str,
    chunks: list[str],
    *,
    max_secondary: int = 2,
) -> list[dict]:
    """Return graded relevance items for one golden question.

    Secondary snippets are raw substrings of the source chunks (verbatim, so
    eval-time normalised substring matching against ingested chunks works),
    starting at the answer occurrence.
    """
    items: list[dict] = [{"hint": [context_hint], "grade": 2}]
    if len(_norm(answer)) < _MIN_ANSWER_CHARS:
        return items
    pattern = _answer_pattern(answer)
    if pattern is None:
        return items
    own_norm = _norm(own_chunk)
    seen_norms = {_hint_key(context_hint)}
    for chunk in chunks:
        if len(items) - 1 >= max_secondary:
            break
        if _norm(chunk) == own_norm:
            continue
        m = pattern.search(chunk)
        if not m:
            continue
        snippet = chunk[m.start() : m.start() + _SNIPPET_CHARS].strip()
        snippet_key = _hint_key(snippet)
        if not snippet_key or snippet_key in seen_norms:
            continue
        seen_norms.add(snippet_key)
        items.append({"hint": [snippet], "grade": 1})
    return items
