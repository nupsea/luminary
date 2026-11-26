"""Every structural quiz gate, fired once on purpose, with the message it gives."""

import json

import pytest

from app.services.quiz_parsers import (
    LONGEST_RIGHT_RATIO,
    REFUSE_DUPLICATE,
    REFUSE_GIVEAWAY,
    REFUSE_LONGEST_RIGHT,
    REFUSE_POINTING,
    REFUSE_SHAPE,
    REFUSE_STATED_WRONG,
    REFUSE_UNGROUNDED,
    REFUSE_UNPARSED,
    QuizRefusal,
    check_structure,
    parse_item,
)

PASSAGE = (
    "In leaderless replication, the client sends each write to several replicas in parallel. "
    "Read repair fixes stale values when a client notices them during a read. Quorum reads and "
    "writes overlap when the number of nodes written plus the number read exceeds the replica "
    "count, so at least one node read holds the latest value."
)
QUOTE = "the client sends each write to several replicas in parallel"


def _option(text, correct, **extra):
    return {"text": text, "correct": correct, "why": "because", **extra}


def _item(**overrides):
    item = {
        "question": "How does a client write under leaderless replication?",
        "options": [
            _option("It sends every write to several replicas at once", True, quote=QUOTE),
            _option("It sends every write to one elected leader", False, mistake="neighbour"),
            _option("It waits for a follower to be promoted first", False, mistake="neighbour"),
            _option("It writes only to the replica closest to it", False, mistake="neighbour"),
        ],
    }
    item.update(overrides)
    return item


def _refusal(item, kind="single", passage=PASSAGE) -> QuizRefusal:
    with pytest.raises(QuizRefusal) as caught:
        check_structure(parse_item(json.dumps(item)), kind, passage)
    return caught.value


def test_a_clean_item_passes_and_maps_the_mistake_code():
    parsed = parse_item(json.dumps(_item()))
    check_structure(parsed, "single", PASSAGE)
    assert [o.trap for o in parsed.wrong] == ["related_but_different"] * 3
    assert parsed.right[0].quote == QUOTE


def test_swapped_field_names_are_read():
    raw = json.dumps(
        {
            "stem": "How does a client write under leaderless replication?",
            "choices": [
                {"option": o["text"], "is_correct": o["correct"], "explanation": "x"}
                | ({"evidence": QUOTE} if o["correct"] else {"trap": "neighbour"})
                for o in _item()["options"]
            ],
        }
    )
    check_structure(parse_item(raw), "single", PASSAGE)


def test_no_json_is_unparsed():
    with pytest.raises(QuizRefusal) as caught:
        parse_item("Sure! Here is a question about replication.")
    assert caught.value.kind == REFUSE_UNPARSED


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"question": "Leaderless replication sends writes to replicas."}, "not a question"),
        ({"options": _item()["options"][:3]}, "3 options where 4"),
        (
            {"options": [_option("A", True, quote=QUOTE)] * 2 + _item()["options"][2:]},
            "2 right options",
        ),
        (
            {"options": [_option("It sends writes to replicas", True)] + _item()["options"][1:]},
            "without a quote",
        ),
        (
            {
                "options": _item()["options"][:3]
                + [_option("It writes to the nearest replica", False, mistake="vibes")]
            },
            "no known mistake",
        ),
        (
            {"options": _item()["options"][:3] + [_option("<option>", False, mistake="detail")]},
            "no text of its own",
        ),
    ],
)
def test_shape_refusals(change, message):
    refusal = _refusal(_item(**change))
    assert refusal.kind == REFUSE_SHAPE
    assert message in refusal.message


def test_identical_option_text_is_a_duplicate():
    options = _item()["options"]
    refusal = _refusal(_item(options=[*options[:3], {**options[2]}]))
    assert refusal.kind == REFUSE_DUPLICATE


def test_a_quote_not_in_the_passage_is_ungrounded():
    options = _item()["options"]
    bad = _option(options[0]["text"], True, quote="the client always writes to a single leader")
    refusal = _refusal(_item(options=[bad, *options[1:]]))
    assert refusal.kind == REFUSE_UNGROUNDED
    assert "not in the passage" in refusal.message


def test_the_prompts_own_placeholder_is_never_a_quote():
    options = _item()["options"]
    bad = _option(options[0]["text"], True, quote="<words from the material>")
    passage = PASSAGE + " <words from the material>"
    assert _refusal(_item(options=[bad, *options[1:]]), passage=passage).kind == REFUSE_UNGROUNDED


def test_a_wrong_option_the_passage_states_is_refused():
    options = _item()["options"]
    copied = _option("Read repair fixes stale values", False, mistake="neighbour")
    refusal = _refusal(_item(options=[*options[:3], copied]))
    assert refusal.kind == REFUSE_STATED_WRONG


def test_a_four_word_copied_phrase_is_left_to_the_judge():
    options = _item()["options"]
    phrase = _option("Read repair fixes stale", False, mistake="neighbour")
    check_structure(
        parse_item(json.dumps(_item(options=[*options[:3], phrase]))), "single", PASSAGE
    )


def test_all_of_the_above_is_a_giveaway():
    options = _item()["options"]
    refusal = _refusal(
        _item(options=[*options[:3], _option("All of the above", False, mistake="neighbour")])
    )
    assert refusal.kind == REFUSE_GIVEAWAY


def test_a_stem_that_points_at_its_source_is_refused():
    refusal = _refusal(_item(question="According to the passage, how are writes sent?"))
    assert refusal.kind == REFUSE_POINTING


def test_a_right_option_found_by_its_length_is_refused():
    options = _item()["options"]
    wrong_len = max(len(o["text"]) for o in options[1:])
    right_text = "It sends every write to several replicas in parallel " + "x" * int(
        wrong_len * LONGEST_RIGHT_RATIO
    )
    refusal = _refusal(_item(options=[{**options[0], "text": right_text}, *options[1:]]))
    assert refusal.kind == REFUSE_LONGEST_RIGHT


def test_length_is_not_checked_on_multi_answer_questions():
    right = [
        _option(
            "It sends every write to several replicas at once, all in parallel", True, quote=QUOTE
        ),
        _option(
            "Stale values are fixed on read",
            True,
            quote="Read repair fixes stale values when a client notices them",
        ),
    ]
    wrong = [_option(f"Wrong idea number {n}", False, mistake="belief") for n in range(3)]
    check_structure(parse_item(json.dumps(_item(options=right + wrong))), "multi", PASSAGE)


def test_a_quote_wrapped_as_a_json_string_is_still_found():
    options = _item()["options"]
    wrapped = {**options[0], "quote": f'"{QUOTE}",'}
    check_structure(
        parse_item(json.dumps(_item(options=[wrapped, *options[1:]]))), "single", PASSAGE
    )


def test_a_typesetters_line_break_hyphen_is_read_as_the_matcher_reads_it():
    passage = PASSAGE + " Consider the time\u2010\nscale for delivery of every write."
    options = _item()["options"]
    hyphened = {**options[0], "quote": "the time\u2010scale for delivery"}
    check_structure(
        parse_item(json.dumps(_item(options=[hyphened, *options[1:]]))), "single", passage
    )


def test_trimming_never_admits_invented_words():
    options = _item()["options"]
    invented = {**options[0], "quote": '"the client writes to a single leader",'}
    assert _refusal(_item(options=[invented, *options[1:]])).kind == REFUSE_UNGROUNDED


def test_an_invented_code_takes_the_levels_only_code():
    options = _item()["options"]
    invented = {**options[3], "mistake": "falsehood"}
    item = parse_item(json.dumps(_item(options=[*options[:3], invented])))
    check_structure(item, "single", PASSAGE, ("neighbour",))
    assert item.wrong[-1].trap == "related_but_different"


def test_an_invented_code_is_refused_where_the_level_offers_a_choice():
    options = _item()["options"]
    invented = {**options[3], "mistake": "falsehood"}
    with pytest.raises(QuizRefusal) as caught:
        check_structure(
            parse_item(json.dumps(_item(options=[*options[:3], invented]))),
            "single",
            PASSAGE,
            ("detail", "swap", "condition"),
        )
    assert caught.value.kind == REFUSE_SHAPE


def test_a_doubly_escaped_newline_in_a_quote_is_whitespace():
    options = _item()["options"]
    escaped = {**options[0], "quote": "the client sends each write\\nto several replicas"}
    check_structure(
        parse_item(json.dumps(_item(options=[escaped, *options[1:]]))), "single", PASSAGE
    )
