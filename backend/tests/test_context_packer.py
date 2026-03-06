"""Pure unit tests for app/services/context_packer.py (S79).

All tests are pure — no DB, no mocks, no imports from repos or models.

(a) test_sections_ordered_by_relevance
(b) test_deduplication_skips_similar_chunks
(c) test_token_budget_enforced
(d) test_section_summary_emitted_once
(e) test_empty_chunks_returns_empty_string
(f) test_no_section_id_chunks_handled
(g) test_dedup_ratio_1_includes_all
"""

from app.services.context_packer import _token_estimate, pack_context

# ---------------------------------------------------------------------------
# (a) test_sections_ordered_by_relevance
# ---------------------------------------------------------------------------


def test_sections_ordered_by_relevance():
    """Section group with higher max score appears first in output."""
    chunks = [
        {
            "text": "Section A content.",
            "section_id": "sec_a",
            "section_heading": "Section A",
            "section_summary": None,
            "relevance_score": 0.3,
        },
        {
            "text": "Section B content.",
            "section_id": "sec_b",
            "section_heading": "Section B",
            "section_summary": None,
            "relevance_score": 0.9,
        },
    ]
    result = pack_context(chunks)
    idx_a = result.find("Section A")
    idx_b = result.find("Section B")
    assert idx_b < idx_a, f"Section B (higher score) should appear before A. Got: {result!r}"


# ---------------------------------------------------------------------------
# (b) test_deduplication_skips_similar_chunks
# ---------------------------------------------------------------------------


def test_deduplication_skips_similar_chunks():
    """Two chunks sharing > 80% LCS ratio — only the first is included."""
    # A and A_copy are identical, so LCS ratio = 1.0 >= 0.8
    original = "The quick brown fox jumps over the lazy dog and runs away fast."
    near_duplicate = "The quick brown fox jumps over the lazy dog and runs away fast."

    chunks = [
        {
            "text": original,
            "section_id": "sec_x",
            "section_heading": "X",
            "section_summary": None,
            "relevance_score": 0.9,
        },
        {
            "text": near_duplicate,
            "section_id": "sec_x",
            "section_heading": "X",
            "section_summary": None,
            "relevance_score": 0.8,
        },
    ]
    result = pack_context(chunks)
    # The text should appear exactly once (deduplicated)
    assert result.count(original) == 1, (
        f"Expected near-duplicate to be removed. Result: {result!r}"
    )


# ---------------------------------------------------------------------------
# (c) test_token_budget_enforced
# ---------------------------------------------------------------------------


def test_token_budget_enforced():
    """Output token estimate does not exceed token_budget * 1.1."""
    budget = 3000
    # Create many chunks that together would total ~6000 tokens
    chunk_text = " ".join(["word"] * 150)  # ~150 words ≈ 195 tokens each
    chunks = [
        {
            "text": chunk_text,
            "section_id": f"sec_{i}",
            "section_heading": f"Section {i}",
            "section_summary": None,
            "relevance_score": float(i) / 30,
        }
        for i in range(30)
    ]
    result = pack_context(chunks, token_budget=budget)
    actual_tokens = _token_estimate(result)
    tolerance = int(budget * 1.1)
    assert actual_tokens <= tolerance, (
        f"Token estimate {actual_tokens} exceeds budget {budget} * 1.1 = {tolerance}"
    )


# ---------------------------------------------------------------------------
# (d) test_section_summary_emitted_once
# ---------------------------------------------------------------------------


def test_section_summary_emitted_once():
    """Section summary appears exactly once even when section has multiple chunks."""
    section_summary = "This section covers the main plot twist."
    chunks = [
        {
            "text": f"Chunk {i} content with some unique text {i}.",
            "section_id": "sec_plot",
            "section_heading": "Plot Twist",
            "section_summary": section_summary,
            "relevance_score": 0.9 - i * 0.1,
        }
        for i in range(3)
    ]
    result = pack_context(chunks)
    count = result.count(section_summary)
    assert count == 1, (
        f"Section summary should appear exactly once, got {count} times in: {result!r}"
    )


# ---------------------------------------------------------------------------
# (e) test_empty_chunks_returns_empty_string
# ---------------------------------------------------------------------------


def test_empty_chunks_returns_empty_string():
    """pack_context([]) returns '' without error."""
    result = pack_context([])
    assert result == "", f"Expected empty string, got: {result!r}"


# ---------------------------------------------------------------------------
# (f) test_no_section_id_chunks_handled
# ---------------------------------------------------------------------------


def test_no_section_id_chunks_handled():
    """Chunks with section_id=None are handled; output is non-empty and no exception."""
    chunks = [
        {
            "text": "Orphan chunk without section.",
            "section_id": None,
            "section_heading": None,
            "section_summary": None,
            "relevance_score": 0.7,
        },
        {
            "text": "Another orphan chunk.",
            "section_id": None,
            "section_heading": None,
            "section_summary": None,
            "relevance_score": 0.5,
        },
    ]
    result = pack_context(chunks)
    assert result, f"Expected non-empty output, got: {result!r}"
    assert "Orphan chunk" in result


# ---------------------------------------------------------------------------
# (g) test_dedup_ratio_1_includes_all
# ---------------------------------------------------------------------------


def test_dedup_ratio_1_includes_all():
    """With dedup_ratio=1.0, all chunks within budget are included even if identical."""
    identical_text = "This is exactly the same text repeated twice."
    chunks = [
        {
            "text": identical_text,
            "section_id": f"sec_{i}",
            "section_heading": f"Section {i}",
            "section_summary": None,
            "relevance_score": 0.9 - i * 0.1,
        }
        for i in range(2)
    ]
    result = pack_context(chunks, dedup_ratio=1.0)
    # Both chunks should appear since dedup is disabled
    count = result.count(identical_text)
    assert count == 2, (
        f"With dedup_ratio=1.0, both identical chunks should appear. Got count={count}"
    )
