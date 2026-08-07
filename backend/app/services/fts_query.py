"""Canonical FTS5 query sanitiser.

This lived in three copies (retriever_strategies, note_search, document_search)
written three different ways. The behaviour is load-bearing enough that
docs/patterns.md documents it, so the copies were three chances to drift.
"""

import re

_PUNCT_RE = re.compile(r"[^\w\s]")
_OP_RE = re.compile(r"\b(AND|OR|NOT)\b", re.IGNORECASE)


def sanitize_fts_query(query: str) -> str:
    """Make a natural-language query safe inside an FTS5 MATCH expression.

    FTS5 reads punctuation (?, *, ^, parens, quotes, +) and bare AND/OR/NOT as
    operators, so an ordinary question is a syntax error. Strip both, leaving a
    space-joined term list.

    Purely a sanitiser: the space-joined result is FTS5's implicit AND, and the
    AND-first/OR-backfill strategy belongs to the executor, not here.
    """
    cleaned = _PUNCT_RE.sub(" ", query)
    cleaned = _OP_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())
