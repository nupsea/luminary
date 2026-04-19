"""Context packer for the V2 agentic chat router (S79).

pack_context() assembles retrieved chunks into a context string that:
  - Groups chunks by section_id (or section_heading when section_id absent)
  - Orders section groups by highest relevance_score descending
  - Emits the section summary once per section group (if provided)
  - Deduplicates near-duplicate chunks using LCS character similarity
  - Respects a strict token budget (exact count via litellm.token_counter)

All I/O happens in the caller (synthesize_node in chat_graph.py).
"""

import litellm

# ---------------------------------------------------------------------------
# Token count — exact via litellm.token_counter (wraps tiktoken, graceful fallback)
# ---------------------------------------------------------------------------


def _token_estimate(text: str, model: str = "gpt-3.5-turbo") -> int:
    """Return exact token count for text using litellm.token_counter.

    Falls back gracefully for unknown/Ollama models via litellm's internal
    tiktoken fallback.  Uses model='gpt-3.5-turbo' (cl100k_base) by default.
    """
    return litellm.token_counter(model=model, text=text)


# ---------------------------------------------------------------------------
# LCS-based similarity — determines whether a chunk is near-duplicate
# ---------------------------------------------------------------------------

_LCS_CHAR_LIMIT = 300  # truncate inputs for O(n²) DP performance


def _lcs_ratio(a: str, b: str) -> float:
    """Longest common substring length / max(len(a), len(b)).

    Both strings are truncated to _LCS_CHAR_LIMIT before comparison
    to keep the O(n²) DP fast even for long chunks.

    Returns 0.0 if either input is empty.
    """
    a = a[:_LCS_CHAR_LIMIT]
    b = b[:_LCS_CHAR_LIMIT]
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0

    # DP: dp[i][j] = length of longest common substring ending at a[i-1], b[j-1]
    prev = [0] * (lb + 1)
    longest = 0
    for i in range(1, la + 1):
        curr = [0] * (lb + 1)
        for j in range(1, lb + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
                longest = max(longest, curr[j])
        prev = curr

    return longest / max(la, lb)


# ---------------------------------------------------------------------------
# _cap_per_document — per-doc diversity cap
# ---------------------------------------------------------------------------


def _cap_per_document(chunks: list[dict], max_per_doc: int = 2) -> list[dict]:
    """Return at most max_per_doc chunks per document_id, preserving order.

    Pure function — no I/O.  Used by search_node when scope='all' to prevent
    a single document from dominating the context window.
    """
    counts: dict[str, int] = {}
    result: list[dict] = []
    for chunk in chunks:
        doc_id = chunk.get("document_id") or ""
        count = counts.get(doc_id, 0)
        if count < max_per_doc:
            result.append(chunk)
            counts[doc_id] = count + 1
    return result


# ---------------------------------------------------------------------------
# pack_context — main public function
# ---------------------------------------------------------------------------


def pack_context(
    chunks: list[dict],
    token_budget: int = 3000,
    dedup_ratio: float = 0.8,
    model: str = "gpt-3.5-turbo",
) -> str:
    """Assemble retrieved chunks into a context string within token_budget.

    Args:
        chunks: List of chunk dicts with keys:
            text (str)                — the chunk content (may include augmented heading)
            section_id (str | None)   — groups chunks into sections
            section_heading (str | None)
            section_summary (str | None) — emitted once as a section header if provided
            relevance_score (float)   — 'score' is also accepted as a fallback key
        token_budget: Maximum token budget for the output string.
        dedup_ratio: LCS ratio above which a chunk is considered a near-duplicate
                     and skipped.  1.0 disables deduplication.
        model: Model name passed to litellm.token_counter for exact token counting.

    Returns:
        Assembled context string.  Empty string if chunks is empty.
    """
    if not chunks:
        return ""

    # -----------------------------------------------------------------------
    # 1. Normalise chunk dicts — accept 'score' as alias for 'relevance_score'
    # -----------------------------------------------------------------------
    normalised: list[dict] = []
    for c in chunks:
        score = c.get("relevance_score") or c.get("score") or 0.0
        group_key = c.get("section_id") or c.get("section_heading") or id(c)
        normalised.append(
            {
                "text": c.get("text", ""),
                "section_id": c.get("section_id"),
                "section_heading": c.get("section_heading"),
                "section_summary": c.get("section_summary"),
                "relevance_score": float(score),
                "_group_key": group_key,
            }
        )

    # -----------------------------------------------------------------------
    # 2. Group chunks by section key; sort groups by max relevance descending
    # -----------------------------------------------------------------------
    groups: dict[object, list[dict]] = {}
    for c in normalised:
        key = c["_group_key"]
        groups.setdefault(key, []).append(c)

    # Sort groups by highest chunk score (descending)
    sorted_groups = sorted(
        groups.values(),
        key=lambda grp: max(c["relevance_score"] for c in grp),
        reverse=True,
    )

    # Within each group, sort chunks by relevance descending
    for grp in sorted_groups:
        grp.sort(key=lambda c: c["relevance_score"], reverse=True)

    # -----------------------------------------------------------------------
    # 3. Assemble output respecting token_budget and dedup_ratio
    # -----------------------------------------------------------------------
    parts: list[str] = []
    emitted_texts: list[str] = []  # track for near-duplicate detection
    total_tokens = 0
    budget_hit = False

    for grp in sorted_groups:
        if budget_hit:
            break

        # Emit section header (heading + summary) once per group
        heading = grp[0]["section_heading"]
        summary = grp[0]["section_summary"]
        header_parts: list[str] = []
        if heading:
            header_parts.append(f"### {heading}")
        if summary:
            header_parts.append(summary)
        if header_parts:
            header = "\n".join(header_parts) + "\n"
            header_tokens = _token_estimate(header, model=model)
            if total_tokens + header_tokens <= token_budget:
                parts.append(header)
                total_tokens += header_tokens

        # Emit individual chunks
        for c in grp:
            chunk_text = c["text"]
            if not chunk_text:
                continue

            # Near-duplicate check
            if dedup_ratio < 1.0 and emitted_texts:
                if any(_lcs_ratio(chunk_text, prev) >= dedup_ratio for prev in emitted_texts):
                    continue

            chunk_str = f"---\n{chunk_text}\n"
            chunk_tokens = _token_estimate(chunk_str, model=model)

            if total_tokens + chunk_tokens > token_budget:
                # Enforce at least the first chunk (truncated if needed)
                if not emitted_texts:
                    # Include this chunk even if it alone exceeds budget
                    parts.append(chunk_str)
                    total_tokens += chunk_tokens
                    emitted_texts.append(chunk_text)
                budget_hit = True
                break

            parts.append(chunk_str)
            total_tokens += chunk_tokens
            emitted_texts.append(chunk_text)

    return "".join(parts)
