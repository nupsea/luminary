"""Flashcard eval metrics (S217)."""

from __future__ import annotations

import json
from collections.abc import Callable

from evals.lib.citation_metrics import Verdict


def compute_factuality(verdicts: list[Verdict]) -> float | None:
    """Aggregate yes/partial/no factuality verdicts."""
    if not verdicts:
        return None
    score = sum(1.0 if v == "yes" else 0.5 if v == "partial" else 0.0 for v in verdicts)
    return score / len(verdicts)


def compute_atomicity(verdicts: list[bool]) -> float | None:
    """Fraction of cards judged to test one atomic fact."""
    if not verdicts:
        return None
    return sum(1 for v in verdicts if v) / len(verdicts)


def compute_clarity_avg(scores: list[int]) -> float | None:
    """Average 1-5 clarity score."""
    if not scores:
        return None
    return sum(scores) / len(scores)


def score_flashcards(
    cards: list[dict],
    source_chunk: str,
    judge: Callable[[dict, str], dict],
) -> dict[str, float | None]:
    """Score generated flashcards with an injected judge function."""
    factuality: list[Verdict] = []
    atomicity: list[bool] = []
    clarity: list[int] = []
    for card in cards:
        result = judge(card, source_chunk)
        factuality.append(result.get("factuality", "no"))
        atomicity.append(bool(result.get("atomic", False)))
        clarity.append(int(result.get("clarity", 0)))
    return {
        "factuality": compute_factuality(factuality),
        "atomicity": compute_atomicity(atomicity),
        "clarity_avg": compute_clarity_avg(clarity),
    }


def judge_flashcard(card: dict, source_chunk: str, judge_model: str) -> dict:
    """Judge one flashcard using LiteLLM strict JSON output."""
    import litellm  # noqa: PLC0415

    prompt = (
        "Evaluate this flashcard against the source chunk. Return only JSON with "
        "keys factuality (yes|partial|no), atomic (true|false), clarity (1-5).\n\n"
        f"Source chunk:\n{source_chunk}\n\n"
        f"Question:\n{card.get('question', '')}\n\nAnswer:\n{card.get('answer', '')}"
    )
    response = litellm.completion(
        model=judge_model,
        messages=[
            {"role": "system", "content": "You are a strict flashcard quality judge."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    parsed = json.loads(response.choices[0].message.content or "{}")
    factuality = str(parsed.get("factuality", "no")).lower()
    if factuality not in {"yes", "partial", "no"}:
        factuality = "no"
    clarity = max(1, min(5, int(parsed.get("clarity", 1))))
    return {
        "factuality": factuality,
        "atomic": bool(parsed.get("atomic", False)),
        "clarity": clarity,
    }
