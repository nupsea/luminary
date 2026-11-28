"""Every structural quiz gate, fired once on purpose, with the message it gives."""

import json

import pytest

from app.services.quiz_material import (
    join_chunks,
    pick_keys,
    pick_list,
    unfit_reason,
    untested_items,
)
from app.services.quiz_parsers import (
    DROP_ABSOLUTE,
    DROP_FIRST_PERSON,
    DROP_LENGTH,
    DROP_STATED,
    DROP_UNTESTED_ITEM,
    REFUSE_ANSWER_IN_STEM,
    REFUSE_COUNT_IN_STEM,
    REFUSE_INVENTED_NAME,
    REFUSE_OTHER_SCRIPT,
    REFUSE_POINTING,
    REFUSE_RIGHT_IS_LONGEST,
    REFUSE_SHAPE,
    REFUSE_UNPARSED,
    REFUSE_UNSUPPORTED_WHY,
    REFUSE_VAGUE_SUBJECT,
    ParsedItem,
    ParsedOption,
    QuizRefusal,
    check_lengths,
    check_question,
    distinct,
    drop_reason,
    parse_letters,
    parse_question,
    parse_wrong,
)

PASSAGE = (
    "In leaderless replication, the client sends each write to several replicas in parallel. "
    "Read repair fixes stale values when a client notices them during a read of several nodes. "
    "Quorum reads and writes overlap when the number of nodes written plus the number read "
    "exceeds the replica count, so at least one node read holds the latest value."
)
KEY = "In leaderless replication, the client sends each write to several replicas in parallel."
QUESTION = "How does a client write data under leaderless replication?"
ANSWER = "It sends every write to several replicas at the same time."


def _refused(call, *args) -> QuizRefusal:
    with pytest.raises(QuizRefusal) as caught:
        call(*args)
    return caught.value


# ---- the material


def test_overlapping_chunks_are_joined_without_the_repeat():
    first = "Leaders accept writes. Followers apply the replication log in the same order."
    second = "apply the replication log in the same order. Failover promotes a follower."
    joined = join_chunks([first, second])
    assert joined.count("apply the replication log") == 1
    assert joined.endswith("Failover promotes a follower.")


def test_a_contents_page_licence_quotations_and_references_are_not_material():
    contents = "\n".join(f"CHAPTER {n}. The Whale as a Dish." for n in range(60, 70))
    quotations = "\n".join(f"“A whale.”\n— Hamlet {n}." for n in range(4))
    references = "[1] E. F. Codd: A Relational Model.\n[2] M. Stonebraker: What Goes Around."
    assert unfit_reason(contents) == "contents"
    assert unfit_reason(quotations) == "quotations"
    assert unfit_reason("This eBook is for the use of anyone anywhere.") == "licence"
    assert unfit_reason(references) == "references"
    assert unfit_reason(PASSAGE) is None


def test_a_key_is_a_whole_sentence_and_a_fragment_is_never_one():
    fragment = "partway through a sentence that the chunk boundary cut in half and then went on. "
    [key] = pick_keys(fragment + PASSAGE, 1, set())
    assert key[0].isupper() and not key.startswith("partway")


def test_a_question_or_a_numbered_note_is_never_a_key():
    note = (
        "2. In order that the whole subject may be laid before the public, it is proposed to "
        "publish them weekly."
    )
    asked = "What inducements could the separate states have, if disunited, to make war?"
    [key] = pick_keys(f"{note} {asked} {PASSAGE}", 1, set())
    assert key not in (note, asked)


def test_a_key_far_from_the_section_summary_loses_to_a_shorter_central_one():
    long_aside = (
        "It is out of the idolatrous dotings of the old Egyptians upon broiled ibis and roasted "
        "river horse that you see the mummies of those creatures in their huge bake-houses."
    )
    central = "Ishmael goes to sea whenever he grows grim about the mouth and gloomy in his soul."
    passage = f"{long_aside} {central}"
    assert pick_keys(passage, 1, set()) == [long_aside]
    assert pick_keys(passage, 1, set(), closeness=[0.40, 0.58]) == [central]
    assert pick_keys(passage, 1, set(), closeness=[0.50, 0.58]) == [long_aside]


def test_a_sentence_about_the_work_itself_is_never_a_key():
    plan = (
        "We had occasion, in a former paper, to take notice of the repeated trials made to reform "
        "the constitution of the confederacy."
    )
    ahead = "We will return to the question of consistency guarantees and their costs later on."
    [key] = pick_keys(f"{plan} {ahead} {PASSAGE}", 1, set())
    assert key not in (plan, ahead)


LIST = (
    "Leaderless replication repairs data in several ways, including:\n"
    "\u2022 Read repair, which writes the newer value back when a read sees a stale one\n"
    "\u2022 Anti-entropy, a background process that copies missing data between replicas\n"
    "\u2022 Hinted handoff, which holds writes for a node that is down until it returns\n"
    "Each has its own cost."
)


def test_a_multi_answer_question_is_written_from_one_list_and_its_opening_line():
    lead_in, items = pick_list(LIST, 2)
    assert lead_in == "Leaderless replication repairs data in several ways, including:"
    assert len(items) == 2 and all(i in LIST for i in items)
    assert pick_list(PASSAGE, 2) is None


# ---- the question


def test_a_clean_question_passes():
    stem, answers = parse_question(json.dumps({"question": QUESTION, "answer": ANSWER}), 1)
    check_question(stem, answers, [KEY], PASSAGE)


def test_no_json_is_unparsed_and_a_statement_is_not_a_question():
    assert _refused(parse_question, "Sure, here it is.", 1).kind == REFUSE_UNPARSED
    raw = json.dumps({"question": "Leaderless replication writes", "answer": ANSWER})
    assert _refused(parse_question, raw, 1).kind == REFUSE_SHAPE


def test_the_prompt_placeholder_is_not_an_answer():
    raw = json.dumps({"question": QUESTION, "answer": "<answer>"})
    assert _refused(parse_question, raw, 1).kind == REFUSE_SHAPE


@pytest.mark.parametrize(
    "asked",
    [
        "According to the material, how does a client write data under leaderless replication?",
        "How does a client write data under leaderless replication according to the text?",
        "How does a client write data under leaderless replication, as described in the passage?",
    ],
)
def test_a_clause_crediting_the_source_is_cut_and_the_rest_is_checked(asked):
    stem, _ = parse_question(json.dumps({"question": asked, "answer": ANSWER}), 1)
    assert stem == "How does a client write data under leaderless replication?"
    check_question(stem, [ANSWER], [KEY], PASSAGE)


def test_a_source_named_inside_the_question_is_not_cut_and_is_refused():
    asked = "What does the passage say a client does with each write?"
    stem, _ = parse_question(json.dumps({"question": asked, "answer": ANSWER}), 1)
    assert stem == asked
    assert _refused(check_question, stem, [ANSWER], [KEY], PASSAGE).kind == REFUSE_POINTING
    stem = "What does the key sentence say about writes under leaderless replication?"
    assert _refused(check_question, stem, [ANSWER], [KEY], PASSAGE).kind == REFUSE_POINTING
    stem = "Which duties of a leader are mentioned for leaderless replication?"
    assert _refused(check_question, stem, [ANSWER], [KEY], PASSAGE).kind == REFUSE_POINTING


def test_a_question_pointing_at_its_source_is_refused():
    stem = "According to the passage, how does a client write?"
    assert _refused(check_question, stem, [ANSWER], [KEY], PASSAGE).kind == REFUSE_POINTING


@pytest.mark.parametrize(
    "stem",
    [
        "According to the story, why were cobblestones carried on the first sloop?",
        "Which problems arise in data systems according to the discussion on fault tolerance?",
        "What comparison does the text make between leaderless and leader-based replication?",
        "Which example does the passage use to illustrate leaderless replication?",
    ],
)
def test_a_question_crediting_a_story_or_discussion_is_refused(stem):
    assert _refused(check_question, stem, [ANSWER], [KEY], PASSAGE).kind == REFUSE_POINTING


def test_a_source_noun_naming_the_subject_is_not_refused():
    check_question(
        "How does the document model make writes easier under leaderless replication?",
        [ANSWER],
        [KEY],
        PASSAGE,
    )


def test_a_name_the_material_never_mentions_is_refused():
    stem = "How does Cassandra write data under leaderless replication?"
    refusal = _refused(check_question, stem, [ANSWER], [KEY], PASSAGE)
    assert refusal.kind == REFUSE_INVENTED_NAME and "Cassandra" in refusal.message


def test_a_stand_in_for_the_one_the_question_is_about_is_refused():
    stem = "How does someone write data under leaderless replication?"
    refusal = _refused(check_question, stem, [ANSWER], [KEY], PASSAGE)
    assert refusal.kind == REFUSE_VAGUE_SUBJECT and "someone" in refusal.message
    general = "People who run several replicas send each write to all of them in parallel."
    check_question(
        "What do people who run several replicas do with a write?",
        [ANSWER],
        [general],
        PASSAGE + " " + general,
    )


def test_why_is_asked_only_of_a_sentence_that_gives_a_reason():
    stem = "Why does the client send writes to several replicas under leaderless replication?"
    refusal = _refused(check_question, stem, [ANSWER], [KEY], PASSAGE)
    assert refusal.kind == REFUSE_UNSUPPORTED_WHY
    reasoned = "The client writes to several replicas because any one of them may be down."
    check_question(stem, [ANSWER], [reasoned], PASSAGE + " " + reasoned)


def test_an_answer_in_another_script_is_refused():
    answer = "It sends every write to several replicas \u540c\u65f6."
    assert _refused(check_question, QUESTION, [answer], [KEY], PASSAGE).kind == REFUSE_OTHER_SCRIPT


def test_a_stem_that_states_its_answer_is_refused():
    stem = "How does the client send every write to several replicas at the same time?"
    assert _refused(check_question, stem, [ANSWER], [KEY], PASSAGE).kind == REFUSE_ANSWER_IN_STEM


def test_a_multi_answer_stem_that_counts_its_answers_is_refused():
    _, keys = pick_list(LIST, 2)
    stem = "Which two ways does leaderless replication repair data?"
    answers = [f"{k.split(',')[0]} repairs stale or missing data between replicas." for k in keys]
    assert _refused(check_question, stem, answers, keys, LIST).kind == REFUSE_COUNT_IN_STEM


# ---- the wrong answers


def _wrong(text, mistake="belief"):
    return ParsedOption(text=text, correct=False, trap={"belief": "common_misconception"}[mistake])


def test_wrong_answers_take_their_slot_code_unless_they_name_another_offered_one():
    raw = json.dumps(
        {
            "wrong": [
                {"text": "It writes to one leader first.", "mistake": "made_up"},
                {"text": "It writes to the nearest replica.", "mistake": "belief"},
            ]
        }
    )
    assert [o.trap for o in parse_wrong(raw, ["broader", "broader"])] == [
        "overgeneralised",
        "overgeneralised",
    ]
    assert [o.trap for o in parse_wrong(raw, ["broader", "belief"])][1] == "common_misconception"


def test_a_wrong_answer_copied_from_the_material_is_dropped():
    option = _wrong("the client sends each write to several replicas in parallel")
    assert drop_reason(option, [ANSWER], PASSAGE) == DROP_STATED


def test_an_absolute_word_only_the_wrong_answer_uses_is_dropped():
    option = _wrong("It always writes to the single replica nearest the client.")
    plain = "It sends each write to several replicas at the same time."
    assert drop_reason(option, [plain], PASSAGE) == DROP_ABSOLUTE
    assert drop_reason(option, ["It always sends writes to many replicas."], PASSAGE) is None


def test_a_wrong_answer_far_off_the_right_answers_length_is_dropped():
    assert drop_reason(_wrong("A leader."), [ANSWER], PASSAGE) == DROP_LENGTH


def test_a_narrators_first_person_in_a_wrong_answer_only_is_dropped():
    option = _wrong("The client told me to send each write to one replica.")
    assert drop_reason(option, [ANSWER], PASSAGE) == DROP_FIRST_PERSON
    first_person_right = "My client sends each write to several replicas."
    assert drop_reason(option, [first_person_right], PASSAGE) is None
    abbreviation = _wrong("The US client sends each write to one replica.")
    assert drop_reason(abbreviation, [ANSWER], PASSAGE) is None


def test_a_wrong_answer_echoing_a_list_item_the_question_leaves_out_is_dropped():
    _, keys = pick_list(LIST, 2)
    untested = untested_items(LIST, keys)
    assert len(untested) == 1 and untested[0] not in keys
    echo = _wrong(untested[0].replace("writes", "reads"))
    stem = "Which ways does leaderless replication repair data?"
    assert drop_reason(echo, keys, LIST, stem=stem, untested=untested) == DROP_UNTESTED_ITEM
    unrelated = _wrong("Leader election, a vote that picks a new primary once the old one fails")
    assert drop_reason(unrelated, keys, LIST, stem=stem, untested=untested) is None
    assert untested_items(LIST, ["not an item of the list"]) == []


def test_a_wrong_answer_repeating_the_right_one_is_dropped():
    kept = distinct([_wrong(ANSWER), _wrong("It writes to one leader.")], [ANSWER])
    assert [o.text for o in kept] == ["It writes to one leader."]


def test_a_right_answer_longer_than_every_wrong_one_is_refused():
    item = ParsedItem(
        stem=QUESTION,
        options=[ParsedOption(text=ANSWER * 2, correct=True), *[_wrong("One leader.")] * 3],
    )
    assert _refused(check_lengths, item, "single").kind == REFUSE_RIGHT_IS_LONGEST


# ---- the judge's and the guesser's letters


def test_letters_are_read_and_an_unoffered_letter_is_ignored():
    assert parse_letters('{"answer": ["B", "d"]}', 4) == {1, 3}
    assert parse_letters('{"answer": ["E"]}', 4) == set()
    assert parse_letters("B", 4) == set()
