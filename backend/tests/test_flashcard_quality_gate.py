from __future__ import annotations

import pytest

from app.services.flashcard_parsers import card_rejection_reason


def test_good_card_passes() -> None:
    assert (
        card_rejection_reason(
            "Why does leader-based replication need a replication log?",
            "So followers can apply the same writes in the same order and stay "
            "consistent with the leader.",
        )
        is None
    )


def test_two_word_answer_passes() -> None:
    # a concise definitional answer is legitimate; only 1-word answers are cut
    assert card_rejection_reason("What partitions a Kafka topic?", "Consumer groups") is None


@pytest.mark.parametrize("field", ["", "   "])
def test_empty_fields_rejected(field: str) -> None:
    assert card_rejection_reason(field, "an answer") is not None
    assert card_rejection_reason("a question?", field) is not None


def test_one_word_answer_rejected() -> None:
    # the reported failure: bloated leading question, one-word answer
    reason = card_rejection_reason(
        "When analytic teams need to fine-tune operational performance, what type of "
        "customer-provided input is essential for closing the loop and making "
        "continuous improvements?",
        "Feedback",
    )
    assert reason is not None
    assert "too short" in reason


def test_bloated_question_with_trivial_answer_rejected() -> None:
    reason = card_rejection_reason(
        "When a distributed system needs to coordinate agreement across many nodes "
        "despite failures and network partitions, what fundamental problem must the "
        "underlying protocol reliably solve for correctness?",
        "The consensus problem",
    )
    assert reason is not None
    assert "bloated" in reason


@pytest.mark.parametrize(
    "phrase",
    ["in this passage", "according to the text", "the author", "this scenario"],
)
def test_leading_deictic_question_rejected(phrase: str) -> None:
    reason = card_rejection_reason(
        f"What does {phrase} say about quorum reads and write consistency guarantees?",
        "A quorum read overlaps with a quorum write so at least one node has the latest value.",
    )
    assert reason is not None
    assert "leading" in reason


def test_bare_yes_no_answer_rejected_as_too_short() -> None:
    reason = card_rejection_reason("Is Kafka a message broker?", "Yes")
    assert reason is not None
    assert "too short" in reason


def test_reasoned_answer_to_polar_question_passes() -> None:
    # a yes/no-framed question is fine when the answer actually explains
    assert (
        card_rejection_reason(
            "Is eventual consistency ever preferable to strong consistency, and why?",
            "Yes, when availability and low latency matter more than reading the "
            "very latest write, such as in a shopping cart.",
        )
        is None
    )
