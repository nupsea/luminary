from __future__ import annotations

import pytest

from app.services.flashcard_parsers import card_rejection_reason, strip_source_ref


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


def test_strip_source_ref_removes_trailing_citation() -> None:
    a = (
        "Random hardware faults are independent while software errors are correlated, "
        "so they need different defences. In Part I. Foundations of Data Systems."
    )
    out = strip_source_ref(a)
    assert "In Part I" not in out
    assert "Foundations of Data Systems" not in out
    assert out.endswith("different defences.")


def test_strip_source_ref_handles_chapter_forms() -> None:
    assert strip_source_ref("The log keeps replicas in sync. In Chapter 3.").endswith(
        "in sync."
    )
    out = strip_source_ref("Quorums overlap reads and writes. See Section 5.2")
    assert "See Section" not in out


def test_strip_source_ref_leaves_clean_answers_untouched() -> None:
    a = "A write-ahead log records changes before applying them, enabling crash recovery."
    assert strip_source_ref(a) == a


def test_strip_source_ref_never_empties_a_short_answer() -> None:
    # if stripping would leave nothing meaningful, keep the original
    assert strip_source_ref("In Chapter 1.") == "In Chapter 1."


def test_the_gate_verdict_is_counted_by_kind():
    """The gate computed a verdict per card and threw it away. It is the one
    signal on this path that needs no judge and measures whether the model
    followed the contract -- deictic questions, one-word answers and empty
    fields are all things the prompt forbids."""
    from app.services import llm_output_stats as stats
    from app.services.flashcard_generators import _gate_cards

    before = dict(stats.snapshot()["counts"])
    kept = _gate_cards(
        [
            {"question": "What partitions a Kafka topic?", "answer": "Consumer groups read them"},
            {"question": "In this passage, what does X claim?", "answer": "Several things"},
            {"question": "Is Kafka a broker?", "answer": "Yes"},
            {"question": "", "answer": "orphan"},
        ]
    )
    after = stats.snapshot()["counts"]
    moved = {k: after[k] - before.get(k, 0) for k in after if after[k] - before.get(k, 0)}

    assert len(kept) == 1
    assert moved["cards_gated"] == 4
    assert moved["cards_rejected"] == 3
    assert moved["card_reject_deictic"] == 1
    assert moved["card_reject_short_answer"] == 1
    assert moved["card_reject_empty_field"] == 1


def test_the_rejection_kind_survives_a_reworded_message():
    """The message carries specifics for a log line; the kind is what is counted."""
    from app.services.flashcard_parsers import REJECT_DEICTIC, card_rejection

    kind, message = card_rejection("In this passage, what is X?", "A real answer here")

    assert kind == REJECT_DEICTIC
    assert "in this passage" in message


def test_an_answer_that_lists_facts_is_rejected():
    """A list is several cards wearing one question -- the primary defect in a card.

    Rules 4, 9 and 10 of the card-writing canon say split it. The prompt used to ask
    for bulleted answers and the measured atomicity floor was 0.7778, with 9 of 12
    sampled cards carrying bullets, so the deterministic backstop matters even after
    the prompt stopped encouraging them.
    """
    from app.services.flashcard_parsers import REJECT_ENUMERATED, card_rejection

    verdict = card_rejection(
        "What institutions support the council?",
        "A council of state helps.\n- a chamber of accounts\n- five admiralty colleges",
    )

    assert verdict is not None
    kind, message = verdict
    assert kind == REJECT_ENUMERATED
    assert "2 items" in message


def test_a_lead_sentence_with_one_detail_line_is_still_one_card():
    """One item is a lead plus its detail; two is a list. The boundary is deliberate."""
    assert (
        card_rejection_reason(
            "What supports the council?",
            "A council of state helps.\n- together with a chamber of accounts",
        )
        is None
    )
