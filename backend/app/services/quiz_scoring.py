"""Scoring an answer and choosing the next level: pure, so both are tested without a model."""

from __future__ import annotations

import random
from collections.abc import Sequence

from app.types import QUIZ_LEVELS, QuizKind, QuizLevel, QuizOutcome

ADAPTIVE_START: QuizLevel = "medium"
# Two right in a row earns a harder question, one miss an easier one: a transformed staircase that
# settles where p^2 = 1/2, about 71% correct (Levitt 1971). Three in a row would settle near 79%.
_UP_AFTER = 2


def score_answer(
    kind: QuizKind, right_ids: Sequence[str], selected_ids: Sequence[str]
) -> tuple[QuizOutcome, float]:
    """Single: right or wrong. Multi: (hits - false picks) / right options, floored at 0;
    correct only for the exact set."""
    right, picked = set(right_ids), set(selected_ids)
    if kind == "single":
        return ("correct", 1.0) if picked == right else ("wrong", 0.0)
    hits, false_picks = len(right & picked), len(picked - right)
    score = max(0.0, (hits - false_picks) / len(right)) if right else 0.0
    if picked == right:
        return "correct", 1.0
    return ("partial" if score > 0 else "wrong"), score


def next_level(current: QuizLevel, outcomes: Sequence[QuizOutcome]) -> QuizLevel:
    """The level of the next question, from the outcomes so far at *current*, newest last."""
    i = QUIZ_LEVELS.index(current)
    if outcomes and outcomes[-1] != "correct":
        return QUIZ_LEVELS[max(0, i - 1)]
    streak = 0
    for outcome in reversed(outcomes):
        if outcome != "correct":
            break
        streak += 1
    if streak and streak % _UP_AFTER == 0:
        return QUIZ_LEVELS[min(len(QUIZ_LEVELS) - 1, i + 1)]
    return current


def shuffled(option_ids: Sequence[str], rng: random.Random | None = None) -> list[str]:
    """The order a quiz shows an item's options. Code, never the model, decides it."""
    order = list(option_ids)
    (rng or random).shuffle(order)
    return order
