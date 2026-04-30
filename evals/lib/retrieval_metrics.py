"""Pure retrieval metrics: HR@5 and MRR over golden samples.

Both functions honour the S226 multi-hint schema: ``context_hint`` may be a
string (legacy) or a list of strings (alternates). A sample counts as a hit
if ANY alternate substring is found in any retrieved chunk.
"""

import re


def _norm(s: str) -> str:
    """Collapse whitespace and normalise typographic quotes for substring matching."""
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


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
    return [_norm(h)[:80] for h in candidates if h.strip()]


def compute_hit_rate_5(samples: list[dict]) -> float:
    """HR@5: fraction of questions where ANY hint substring is in top-5 chunks."""
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


def compute_mrr(samples: list[dict]) -> float:
    """MRR: mean reciprocal rank of the FIRST chunk matching ANY hint."""
    if not samples:
        return 0.0
    reciprocal_ranks = []
    for s in samples:
        hint_norms = _extract_hint_norms(s)
        chunks = s.get("contexts", [])
        rank = None
        if hint_norms:
            for i, ctx in enumerate(chunks, start=1):
                ctx_norm = _norm(ctx)
                if any(h in ctx_norm for h in hint_norms):
                    rank = i
                    break
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
    return sum(reciprocal_ranks) / len(reciprocal_ranks)
