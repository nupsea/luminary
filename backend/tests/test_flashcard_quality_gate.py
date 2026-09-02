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


# Grounding. Measured 2026-08-17 on 35 passages: 27% of delivered cards were
# unsupported by the passage they came from, and rewriting the prompt did not move
# that number (0.7300 -> 0.7267 factuality). A model asked for a well-shaped card
# still writes what it already believes about a famous text; quoting is the part it
# cannot do from memory.

_PASSAGE = (
    "Penelope set up a great web in her house and told the suitors she would choose "
    "a husband when it was finished, but she undid her work each night for three "
    "years, while 108 suitors waited."
)


def test_a_card_quoting_the_passage_passes():
    assert (
        card_rejection_reason(
            "How did Penelope delay the suitors?",
            "She undid her weaving each night so it was never finished.",
            "she undid her work each night for three years",
            _PASSAGE,
        )
        is None
    )


def test_a_card_whose_quote_is_not_in_the_passage_is_rejected():
    """The reported failure: a card asserting the suitors tricked Penelope.

    No span of the passage supports it, so no honest quote exists for it.
    """
    from app.services.flashcard_parsers import REJECT_UNGROUNDED, card_rejection

    verdict = card_rejection(
        "How did the suitors trick Penelope?",
        "They fooled her by having a maid show false work.",
        "the suitors tricked Penelope by having a maid show the false work",
        _PASSAGE,
    )

    assert verdict is not None
    assert verdict[0] == REJECT_UNGROUNDED


def test_a_shortened_quote_is_accepted_part_by_part():
    """Models elide long quotes with '...'; each surviving part must still be real."""
    assert (
        card_rejection_reason(
            "What did Penelope promise?",
            "To choose a husband once the web was finished.",
            "told the suitors ... when it was finished",
            _PASSAGE,
        )
        is None
    )


# A rule requiring every figure in an answer to appear in the passage was tried and
# removed: across four full-golden runs it rejected nothing, and it fails a
# legitimate answer like "a state of being both 0 and 1" whose digits are
# conceptual rather than quoted. Unmeasured value, demonstrated false positives.


def test_grounding_is_skipped_when_the_caller_has_no_passage():
    """Cards built from concepts or gaps have no single text to quote."""
    assert (
        card_rejection_reason(
            "What is spaced repetition?",
            "Reviewing material at increasing intervals.",
            "",
            None,
        )
        is None
    )


def test_the_prompts_own_example_can_never_be_a_cards_evidence():
    """A check the system can satisfy with its own material is not a check.

    Measured 2026-08-17: shown a plausible `source_excerpt` in the worked example,
    the model pasted that exact string as its evidence for two unrelated technical
    documents. It failed the gate only because the string happened not to appear in
    those passages. This asserts it fails even when it does appear -- otherwise a
    fabricated card can be grounded on text the product supplied.
    """
    from app.services.flashcard_parsers import REJECT_UNGROUNDED, card_rejection
    from app.services.flashcard_prompts import EXAMPLE_SOURCE_EXCERPT

    passage = f"In practice {EXAMPLE_SOURCE_EXCERPT}, which changes how you defend each."

    verdict = card_rejection(
        "Why do the two fault kinds differ?",
        "They fail in different ways and need different defences.",
        EXAMPLE_SOURCE_EXCERPT,
        passage,
    )

    assert verdict is not None
    assert verdict[0] == REJECT_UNGROUNDED
    assert "example" in verdict[1]

    # and a real quote from that same passage is still accepted
    assert (
        card_rejection_reason(
            "Why do the two fault kinds differ?",
            "They fail in different ways and need different defences.",
            "which changes how you defend each",
            passage,
        )
        is None
    )


def test_notes_prompt_does_not_ask_for_what_the_gate_rejects() -> None:
    """The notes contract and the gate must agree on the shape of a card.

    They did not: the prompt asked for "short markdown bullets ('- ...')" while
    `_MAX_ENUMERATED_ITEMS = 1` rejects a two-bullet answer, and its output
    template carried `"source_excerpt": ""` while the gate requires a verbatim
    quote. Notes returned empty decks until both were aligned (#108).

    Asserting the prompt text is the point: the gate was never wrong, so a test
    of the gate alone would have stayed green through the whole outage.
    """
    from app.services.flashcard_prompts import NOTES_CARD_FROM_CONCEPTS_SYSTEM

    assert "markdown bullets" not in NOTES_CARD_FROM_CONCEPTS_SYSTEM
    assert '"source_excerpt": ""' not in NOTES_CARD_FROM_CONCEPTS_SYSTEM
    assert "word for word" in NOTES_CARD_FROM_CONCEPTS_SYSTEM


def test_notes_excerpt_placeholder_is_refused() -> None:
    """The notes template shows the shape of a quote, and it clears the length
    floor -- so a model that echoes it must be refused explicitly rather than by
    the luck of it not appearing in the notes."""
    from app.services.flashcard_parsers import REJECT_UNGROUNDED, card_rejection
    from app.services.flashcard_prompts import NOTES_EXCERPT_PLACEHOLDER

    notes = f"The learner wrote: {NOTES_EXCERPT_PLACEHOLDER} appears here verbatim."

    verdict = card_rejection(
        "What does the note record?",
        "It records a placeholder rather than a measured quote.",
        NOTES_EXCERPT_PLACEHOLDER,
        notes,
    )

    assert verdict is not None
    assert verdict[0] == REJECT_UNGROUNDED


def test_markdown_emphasis_is_formatting_not_fabrication() -> None:
    """A model quoting a bolded sentence returns what a reader sees.

    A quote whose only difference from the note is its `**` markers was rejected
    as not in the text. Notes are written in markdown, so this was the most
    repeated rejection on that path (#108).

    The cases that bracket it: the same sentence minus its `**` must pass, and a
    sentence that changes what is claimed must still fail even though it opens
    with the same words.
    """
    from app.services.flashcard_parsers import excerpt_is_verbatim

    note = (
        "## TF-IDF\n"
        "**TF-IDF**, which stands for **Term Frequency-Inverse Document Frequency**, "
        "is a numerical statistic used to measure how important a word is.\n"
        "It uses `read_source_text` to decode the bytes."
    )

    assert excerpt_is_verbatim(
        "TF-IDF, which stands for Term Frequency-Inverse Document Frequency, "
        "is a numerical statistic used to measure how important a word is.",
        note,
    )
    assert not excerpt_is_verbatim(
        "TF-IDF, which stands for Term Frequency, is a ranking function that "
        "reranks dense vectors after retrieval.",
        note,
    )
    # A code span loses its backticks, but an identifier keeps its underscores:
    # collapsing those would let two different names compare equal.
    assert excerpt_is_verbatim("It uses read_source_text to decode the bytes.", note)
    assert not excerpt_is_verbatim("It uses readsourcetext to decode the bytes.", note)
