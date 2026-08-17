"""Flashcard eval metrics (S217).

Atomicity is computed here, not asked of a judge. Measured 2026-08-17: with the
judge prompt naming the axes and nothing else, `phi4-mini` returned
`atomicity 1.0000` on a set where 9 of 12 answers carried bulleted multi-point
answers -- four of them three facts or more. An undefined axis is a rubber stamp,
and a rate pinned at 1.0000 cannot show a prompt change working either way.

Counting facts needs no model: an answer that lists items lists them visibly.
Factuality and clarity stay judged, because both are semantic, but the judge is
now told what each verdict means and must return the fact count it saw, so its
answer can be checked against the deterministic one instead of trusted.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from evals.lib.citation_metrics import Verdict

# A line that opens with a bullet, a dash or "1." is an enumerated item; two or
# more of them make the answer a list. Sentence splitting is deliberately crude:
# the question is whether an answer carries several independent assertions, and a
# comparison stated in one sentence with a subordinate clause is still one fact.
_ENUM_LINE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+\S")
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def answer_fact_count(answer: str) -> int:
    """How many distinct assertions an answer carries, structurally.

    Enumerated items count as one fact each. Otherwise the count is the number of
    sentences, which over-counts a two-sentence explanation of one idea -- so the
    atomicity rate below is a *floor* on how atomic the cards are, never a
    flattering estimate.
    """
    text = (answer or "").strip()
    if not text:
        return 0
    enumerated = [ln for ln in text.splitlines() if _ENUM_LINE.match(ln)]
    if enumerated:
        # The lead sentence before the list is part of the same card, so the list
        # length is what decides: one item is a lead plus detail, two is a list.
        return len(enumerated) if len(enumerated) > 1 else 1
    sentences = [s for s in _SENTENCE_END.split(text) if s.strip()]
    return max(1, len(sentences))


def is_atomic(answer: str) -> bool:
    """One assertion, the minimum information principle applied to an answer."""
    return answer_fact_count(answer) <= 1


def compute_factuality(verdicts: list[Verdict]) -> float | None:
    """Aggregate yes/partial/no factuality verdicts."""
    if not verdicts:
        return None
    score = sum(1.0 if v == "yes" else 0.5 if v == "partial" else 0.0 for v in verdicts)
    return score / len(verdicts)


def compute_atomicity(verdicts: list[bool]) -> float | None:
    """Fraction of cards carrying exactly one assertion.

    The verdicts come from `is_atomic`, not from a judge -- see the module
    docstring for what happened when they came from a judge.
    """
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
    judged_atomic: list[bool] = []
    for card in cards:
        result = judge(card, source_chunk)
        factuality.append(result.get("factuality", "no"))
        clarity.append(int(result.get("clarity", 0)))
        # Structural, so it cannot be rubber-stamped. The judge's own opinion is
        # kept only to report how far it drifts from what the text plainly says.
        atomicity.append(is_atomic(card.get("answer", "")))
        judged_atomic.append(bool(result.get("atomic", False)))
    disagreement = (
        sum(1 for a, b in zip(atomicity, judged_atomic, strict=False) if a != b) / len(cards)
        if cards
        else None
    )
    return {
        "factuality": compute_factuality(factuality),
        "atomicity": compute_atomicity(atomicity),
        "clarity_avg": compute_clarity_avg(clarity),
        "judge_atomicity_disagreement": disagreement,
    }


def judge_flashcard(card: dict, source_chunk: str, judge_model: str) -> dict:
    """Judge one flashcard using LiteLLM strict JSON output."""
    import litellm  # noqa: PLC0415

    # Every axis is defined. Naming them and nothing else produced
    # `atomicity 1.0000` on a set that was visibly two thirds multi-point answers:
    # an undefined axis is answered with whatever is agreeable.
    prompt = (
        "Grade one flashcard against the passage it was written from.\n\n"
        "factuality:\n"
        "  yes     -- every claim in the answer is stated in the passage or follows "
        "directly from it\n"
        "  partial -- part of the answer is supported and part is not\n"
        "  no      -- the answer contradicts the passage, reverses who did what, or "
        "adds facts the passage does not contain\n"
        "atomic:\n"
        "  true  -- the answer asserts exactly ONE fact\n"
        "  false -- the answer asserts two or more distinct facts, in bullets, "
        "numbered items or separate sentences, however well written\n"
        "clarity: 1-5, how unambiguous the question is with the passage taken away\n\n"
        "Count the distinct facts in the answer first and report that count, so the "
        "atomic verdict can be checked against it.\n"
        "Return only JSON with keys factuality, atomic, clarity, facts_counted.\n\n"
        f"Passage:\n{source_chunk}\n\n"
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
        "facts_counted": parsed.get("facts_counted"),
    }
