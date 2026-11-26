"""Scoring, the adaptive staircase and the option shuffle."""

import random
from collections import Counter

import pytest

from app.services.quiz_scoring import next_level, score_answer, shuffled
from app.services.quiz_service import kind_for


def test_single_is_right_or_wrong():
    assert score_answer("single", ["a"], ["a"]) == ("correct", 1.0)
    assert score_answer("single", ["a"], ["b"]) == ("wrong", 0.0)
    assert score_answer("single", ["a"], ["a", "b"]) == ("wrong", 0.0)


@pytest.mark.parametrize(
    ("picked", "expected"),
    [
        (["a", "b", "c"], ("correct", 1.0)),
        (["a", "b"], ("partial", 2 / 3)),
        (["a", "b", "x"], ("partial", 1 / 3)),
        (["a", "x"], ("wrong", 0.0)),
        (["x", "y"], ("wrong", 0.0)),
        (["a", "b", "c", "x"], ("partial", 2 / 3)),
    ],
)
def test_multi_counts_hits_less_false_picks(picked, expected):
    assert score_answer("multi", ["a", "b", "c"], picked) == pytest.approx(expected)


def test_two_right_in_a_row_go_up_and_one_miss_goes_down():
    assert next_level("medium", []) == "medium"
    assert next_level("medium", ["correct"]) == "medium"
    assert next_level("medium", ["correct", "correct"]) == "hard"
    assert next_level("hard", ["correct", "correct", "correct"]) == "hard"
    assert next_level("hard", ["correct", "correct", "wrong"]) == "medium"
    assert next_level("medium", ["wrong", "partial"]) == "easy"
    assert next_level("easy", ["wrong"]) == "easy"


def test_a_partial_answer_counts_as_a_miss():
    assert next_level("medium", ["correct", "partial"]) == "easy"


def test_the_right_answer_lands_in_every_position_evenly():
    rng = random.Random(7)
    positions = Counter(
        shuffled(["right", "w1", "w2", "w3"], rng).index("right") for _ in range(8000)
    )
    # 2000 expected per slot; 5 standard deviations of a binomial(8000, 1/4) is about 194.
    assert all(abs(n - 2000) < 194 for n in positions.values()), positions


def test_mixed_quizzes_ask_every_third_question_with_several_answers():
    assert [kind_for("mixed", p) for p in range(6)] == [
        "single",
        "multi",
        "single",
        "single",
        "multi",
        "single",
    ]
    assert kind_for("multi", 0) == "multi"
