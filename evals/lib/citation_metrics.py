"""Citation grounding metrics for eval runs (S215)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Literal

Verdict = Literal["yes", "no", "partial"]

_CITATION_RE = re.compile(r"\[(\d+)\]")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def parse_claims_with_citations(answer_text: str) -> list[tuple[str, int]]:
    """Extract ``(claim_text, citation_index)`` pairs from prose.

    Citation indexes are returned as zero-based integers so they can address
    the API's ``citations`` list directly. A sentence with multiple citation
    markers produces one pair per marker.
    """
    pairs: list[tuple[str, int]] = []
    for sentence in _SENTENCE_RE.split(answer_text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        matches = list(_CITATION_RE.finditer(sentence))
        if not matches:
            continue
        claim = _CITATION_RE.sub("", sentence).strip()
        claim = re.sub(r"\s+", " ", claim)
        claim = re.sub(r"\s+([.!?,;:])", r"\1", claim)
        if not claim:
            continue
        for match in matches:
            citation_num = int(match.group(1))
            if citation_num > 0:
                pairs.append((claim, citation_num - 1))
    return pairs


def judge_citation(claim: str, chunk: str, judge_model: str) -> Verdict:
    """Judge whether *chunk* supports *claim* using LiteLLM strict JSON output."""
    import litellm  # noqa: PLC0415

    prompt = (
        "Decide whether the citation text supports the claim. "
        "Return only JSON with this exact shape: {\"verdict\":\"yes|no|partial\"}.\n\n"
        f"Claim:\n{claim}\n\nCitation text:\n{chunk}"
    )
    response = litellm.completion(
        model=judge_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict citation-grounding judge. Use yes only when "
                    "the citation fully supports the claim, partial when it supports "
                    "some but not all of it, and no when it does not support it."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    content = response.choices[0].message.content or "{}"
    verdict = str(json.loads(content).get("verdict", "")).lower()
    if verdict not in {"yes", "no", "partial"}:
        return "no"
    return verdict  # type: ignore[return-value]


def compute_citation_support_rate(
    pairs: list[tuple[str, str]],
    *,
    judge: Callable[[str, str], Verdict],
) -> float | None:
    """Return ``(yes + 0.5 * partial) / total`` for claim/chunk pairs."""
    if not pairs:
        return None
    score = 0.0
    for claim, chunk in pairs:
        verdict = judge(claim, chunk)
        if verdict == "yes":
            score += 1.0
        elif verdict == "partial":
            score += 0.5
    return score / len(pairs)
