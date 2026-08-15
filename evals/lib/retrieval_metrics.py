"""Pure retrieval metrics: HR@5, MRR@5 and nDCG@10 over golden samples.

All functions honour the S226 multi-hint schema: ``context_hint`` may be a
string (legacy) or a list of strings (alternates). A sample counts as a hit
if ANY alternate substring is found in any retrieved chunk.

nDCG@10 additionally honours the graded ``relevance`` schema: a list of
``{"hint": str | list[str], "grade": int}`` items, each naming ONE distinct
relevant passage (hint alternates allowed within an item). Samples without
``relevance`` fall back to ``context_hint`` as a single grade-1 item, which
makes nDCG@10 a log-discounted single-hit metric — comparable, just less
informative than with graded goldens.
"""

import html
import math
import re


def _norm(s: str) -> str:
    """One normalisation for hints, chunks and source text.

    Used by the runtime metrics AND by tests/test_golden_integrity.py, which
    checks the same hints against the corpus offline. The two drifted once: the
    offline check unescaped HTML entities and folded non-breaking spaces while
    this did not, so a hint could pass the integrity gate and be unmatchable at
    runtime on exactly the scraped content that carries `&amp;` and `\xa0`.
    """
    s = html.unescape(s).replace("\xa0", " ")
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


# Hints are matched on this normalised prefix length. It defines what counts
# as a hit for EVERY retrieval metric AND for generation-time verbatim/dedup
# checks — always compare hints through _hint_key so the definitions can't
# drift apart.
HINT_NORM_LEN = 80


def _hint_key(s: str) -> str:
    return _norm(s)[:HINT_NORM_LEN]


def _extract_hint_norms(sample: dict) -> list[str]:
    """Return the list of normalised, length-80 hint prefixes for a sample."""
    raw = sample.get("context_hint", "")
    if isinstance(raw, list):
        candidates = [h for h in raw if isinstance(h, str) and h.strip()]
    else:
        candidates = [raw] if isinstance(raw, str) and raw.strip() else []
    if not candidates:
        gt = sample.get("ground_truths", [""])
        if gt and isinstance(gt[0], str) and gt[0].strip():
            candidates = [gt[0][:50]]
    return [_hint_key(h) for h in candidates if h.strip()]


def compute_hit_rate_5(samples: list[dict]) -> float:
    """HR@5: fraction of questions where ANY hint substring is in top-5 chunks.

    Strict: the hint must sit inside ONE chunk. `count_boundary_misses` reports
    how many of the remaining misses are chunk-boundary artifacts rather than
    retrieval failures. This definition is unchanged and the committed baselines
    are measured against it -- widening it would move every recorded number
    without any change in retrieval.
    """
    if not samples:
        return 0.0
    hits = 0
    for s in samples:
        hint_norms = _extract_hint_norms(s)
        if not hint_norms:
            continue
        chunks = s.get("contexts", [])[:5]
        if any(any(h in _norm(ctx) for h in hint_norms) for ctx in chunks):
            hits += 1
    return hits / len(samples)


def count_boundary_misses(samples: list[dict], k: int = 5) -> int:
    """Misses whose hint spans two retrieved chunks instead of being absent.

    A hint is matched on an 80-character normalised prefix, so ingestion
    splitting text inside that window scores a miss even when both halves come
    back at ranks 1 and 2. That is a chunking property, not a retrieval failure,
    and it makes HR@5 move when chunk size changes for reasons unrelated to what
    retrieval found. Counted here rather than folded into the hit rate: the
    number is the evidence that a chunking change, not the funnel, moved a score.
    """
    misses = 0
    for s in samples:
        hint_norms = _extract_hint_norms(s)
        if not hint_norms:
            continue
        chunks = [_norm(c) for c in s.get("contexts", [])[:k]]
        if any(any(h in c for h in hint_norms) for c in chunks):
            continue
        # Joined in rank order, both ways. A chunker that breaks at whitespace
        # reassembles with a space; the character-splitter fallback cuts
        # mid-word, where only a seamless join puts the hint back together.
        # Trying one alone under-reports whichever split the corpus produced.
        spaced = " ".join(chunks)
        seamless = "".join(chunks)
        if any(h in spaced or h in seamless for h in hint_norms):
            misses += 1
    return misses


def compute_recall_at(samples: list[dict], k: int) -> float:
    """Recall@k: fraction of questions where ANY hint substring is in the top-k chunks.

    Order-insensitive within the window -- this measures whether L1 surfaced
    the gold passage at all, the recall ceiling no downstream layer can raise.
    """
    if not samples:
        return 0.0
    hits = 0
    for s in samples:
        hint_norms = _extract_hint_norms(s)
        if not hint_norms:
            continue
        chunks = s.get("contexts", [])[:k]
        if any(any(h in _norm(ctx) for h in hint_norms) for ctx in chunks):
            hits += 1
    return hits / len(samples)


def compute_mrr(samples: list[dict]) -> float:
    """MRR@5: mean reciprocal rank of the FIRST chunk matching ANY hint.

    Depth is pinned at 5 so scores stay comparable across history now that
    samples may carry 10 contexts (for nDCG@10).
    """
    if not samples:
        return 0.0
    reciprocal_ranks = []
    for s in samples:
        hint_norms = _extract_hint_norms(s)
        chunks = s.get("contexts", [])[:5]
        rank = None
        if hint_norms:
            for i, ctx in enumerate(chunks, start=1):
                ctx_norm = _norm(ctx)
                if any(h in ctx_norm for h in hint_norms):
                    rank = i
                    break
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def _extract_graded_items(sample: dict) -> list[tuple[list[str], int]]:
    """Return [(hint_norms, grade)] — one entry per distinct relevant passage.

    Malformed entries are skipped rather than raised: goldens are data files
    and a single bad row must not abort a whole eval run.
    """
    raw = sample.get("relevance")
    items: list[tuple[list[str], int]] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            hints = entry.get("hint")
            if isinstance(hints, str):
                hints = [hints]
            if not isinstance(hints, list):
                continue
            norms = [_hint_key(h) for h in hints if isinstance(h, str) and h.strip()]
            grade = entry.get("grade", 1)
            if norms and isinstance(grade, int) and grade > 0:
                items.append((norms, grade))
    if not items:
        hint_norms = _extract_hint_norms(sample)
        if hint_norms:
            items = [(hint_norms, 1)]
    return items


def compute_ndcg_10(samples: list[dict], k: int = 10) -> float:
    """nDCG@10: graded, position-discounted relevance over the top-k chunks.

    Each golden passage is credited at most once, at the first retrieved chunk
    that contains it; a chunk matching several unclaimed passages is credited
    with the highest-grade one. IDCG places all grades (best first) at the top
    ranks, so 1.0 means every relevant passage was retrieved in ideal order.
    Samples without any usable hint score 0.0, matching compute_mrr.
    """
    if not samples:
        return 0.0
    scores: list[float] = []
    for s in samples:
        items = _extract_graded_items(s)
        if not items:
            scores.append(0.0)
            continue
        remaining = list(items)
        dcg = 0.0
        for i, ctx in enumerate(s.get("contexts", [])[:k], start=1):
            ctx_norm = _norm(ctx)
            best_idx = -1
            best_grade = 0
            for idx, (norms, grade) in enumerate(remaining):
                if grade > best_grade and any(h in ctx_norm for h in norms):
                    best_idx, best_grade = idx, grade
            if best_idx >= 0:
                dcg += best_grade / math.log2(i + 1)
                remaining.pop(best_idx)
        ideal_grades = sorted((g for _, g in items), reverse=True)[:k]
        idcg = sum(g / math.log2(r + 1) for r, g in enumerate(ideal_grades, start=1))
        scores.append(dcg / idcg if idcg > 0 else 0.0)
    return sum(scores) / len(scores)
