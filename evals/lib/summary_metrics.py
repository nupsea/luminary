"""Summary eval metrics (S216)."""

from __future__ import annotations

import json
import re


def compute_theme_coverage(summary: str, expected_themes: list[str]) -> float:
    """Fraction of expected theme groups represented in the summary.

    Each expected theme is a bag of keywords separated by ``|`` or ``,``; a
    theme counts as covered when any keyword in that group appears.
    """
    if not expected_themes:
        return 1.0
    summary_lower = summary.lower()
    covered = 0
    for theme in expected_themes:
        keywords = [k.strip().lower() for k in re.split(r"[|,]", theme) if k.strip()]
        if keywords and any(k in summary_lower for k in keywords):
            covered += 1
    return covered / len(expected_themes)


def compute_conciseness_pct(summary: str, target_length_chars: int) -> float | None:
    """Return ``len(summary) / target_length_chars``; None when target is invalid."""
    if target_length_chars <= 0:
        return None
    return len(summary) / target_length_chars


def compute_no_hallucination(hallucinated_count: int, total_claims: int) -> float:
    """Return ``1 - hallucinated / max(total_claims, 1)``."""
    return 1.0 - (hallucinated_count / max(total_claims, 1))


def judge_hallucination_counts(source_excerpt: str, summary: str, judge_model: str) -> dict[str, int]:
    """Use LiteLLM to count unsupported summary claims."""
    import litellm  # noqa: PLC0415

    prompt = (
        "Given the source excerpt and summary, count summary claims not supported "
        "by the source. Return only JSON: "
        "{\"hallucinated_count\":0,\"total_claims\":0}.\n\n"
        f"Source excerpt:\n{source_excerpt}\n\nSummary:\n{summary}"
    )
    response = litellm.completion(
        model=judge_model,
        messages=[
            {"role": "system", "content": "You are a strict summary factuality judge."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    return {
        "hallucinated_count": int(parsed.get("hallucinated_count", 0)),
        "total_claims": int(parsed.get("total_claims", 0)),
    }
