"""Unit-first flashcards (#191): code picks the sentences, the model phrases one card each."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.models import ChunkModel, DocumentModel
from app.services import llm_output_stats
from app.services.flashcard import FlashcardService
from app.services.flashcard_generators import _unit_cards
from app.services.flashcard_parsers import REJECT_DEICTIC, REJECT_EMPTY_FIELD, card_rejection
from app.services.flashcard_units import (
    MIN_ANSWER_COVERAGE,
    best_unit,
    choose_units,
    listed_sentence,
    names_not_in,
    split_speeches,
    split_units,
)

STORY = (
    "The Queen called for her servant, a huntsman.\n"
    "Pointing her long fingernail at him she said, take Snow White deep into the woods and\n"
    "never let her come back to the castle again.\n"
    "The huntsman was shocked!\n"
)


def test_a_hard_wrapped_sentence_is_one_unit():
    units = split_units(STORY)
    assert units[1].startswith("Pointing") and units[1].endswith("castle again.")
    assert len(units) == 3


def test_the_excerpt_separator_never_joins_a_sentence():
    text = "The first excerpt ends here.\n\n[...]\n\nThe second excerpt starts here."
    assert split_units(text) == ["The first excerpt ends here.", "The second excerpt starts here."]


def test_a_footnote_marker_still_ends_a_sentence():
    # Fused, the two read as one long sentence that length selection then picked (AI Engineering).
    text = (
        "A token can be a part of a word, depending on the model.2 For example, GPT-4 breaks "
        "the phrase into nine tokens.13 Tokens are counted."
    )
    assert split_units(text) == [
        "A token can be a part of a word, depending on the model.2",
        "For example, GPT-4 breaks the phrase into nine tokens.13",
        "Tokens are counted.",
    ]


@pytest.mark.parametrize(
    "text", ["Use GPT-3.5 Turbo for this.", "See section 4.2 The results follow."]
)
def test_a_decimal_is_not_a_footnote(text):
    assert split_units(text) == [text]


def test_a_sentence_that_opens_with_its_example_is_never_chosen():
    claim = "A token can be a character, a word, or a part of a word, depending on the model."
    example = "For example, GPT-4 breaks the phrase I can't wait to build AI apps into nine tokens."
    assert choose_units([claim, example], 1) == [claim]
    assert choose_units([example], 1) == []
    assert choose_units(["E.g. a vowel and a consonant make up this syllable."], 1) == []
    # A chunk's section label in front does not hide the opener.
    labelled = "[Debugging] For example, Linux started out as a program to explore a chip."
    assert choose_units([labelled], 1) == []


def test_a_section_label_stays_with_its_own_paragraph():
    text = "The last sentence of chunk one.\n\n[Book XII]\nUlysses was tied to the mast."
    units = split_units(text)
    assert units[0] == "The last sentence of chunk one."
    assert units[1] == "[Book XII] Ulysses was tied to the mast."


PLAY = (
    "Farewell, and let your haste commend your duty.\n"
    "LAERTES.\n"
    "Think it no more.\n"
    "For nature crescent does not grow alone\n"
    "In thews and bulk, but as this temple waxes.\n"
    "\n"
    "OPHELIA.\n"
    "I shall the effect of this good lesson keep.\n"
)


def test_a_speaker_line_starts_a_speech_rather_than_ending_the_last_one():
    assert split_speeches(PLAY) == [
        ("Farewell, and let your haste commend your duty.", None),
        ("Think it no more.", "Laertes"),
        (
            "For nature crescent does not grow alone In thews and bulk, but as this temple waxes.",
            "Laertes",
        ),
        ("I shall the effect of this good lesson keep.", "Ophelia"),
    ]


@pytest.mark.parametrize("seam", ["\n[...]\n\n", "\n[Lends the tongue vows]\n", "\n"])
def test_the_next_chunk_does_not_inherit_the_last_speaker(seam):
    # The next chunk opens mid-speech; its speaker line is in a chunk the model was not shown.
    text = PLAY + seam + "Appears no other thing to me. What a piece of work is man."
    assert [speaker for _unit, speaker in split_speeches(text)][-1] is None


@pytest.mark.parametrize(
    "labels",
    [
        ("NOTES:", "ELSE:"),
        ("N.E.", "N.S."),
        ("CHAPTER II.", "CHAPTER III."),
        ("ACT I.", "SCENE II."),
        ("HAMLET.",),
    ],
)
def test_headings_and_a_lone_label_are_not_speakers(labels):
    text = "\n".join(f"{label}\nA sentence that follows the label line here." for label in labels)
    assert all(speaker is None for _unit, speaker in split_speeches(text))


def test_a_label_that_finishes_a_sentence_is_not_a_speaker():
    text = "Input byte from the port into\nAL.\n\nInput word from the port into\nAX.\n"
    assert all(speaker is None for _unit, speaker in split_speeches(text))


def test_the_model_sees_the_speaker_and_not_the_section_label():
    unit = "[the_gita > CHAPTER II — Sanjaya.] Thou wilt win Swarga's safety."
    assert listed_sentence(unit, None) == "Thou wilt win Swarga's safety."
    assert listed_sentence("Think it no more.", "Laertes") == "Laertes says: Think it no more."


def test_code_is_grouped_rather_than_split_at_dots():
    code = "def f(x):\n    return x.value\n"
    assert split_units(code) == ["def f(x):\n    return x.value"]


def test_the_longest_prose_units_are_chosen_in_passage_order():
    units = [
        "A short line.",
        "The Queen decided to be rid of Snow White once and for all, and called the huntsman.",
        "She laughed.",
        "The huntsman could not kill Snow White and told her to run far away into the woods.",
    ]
    assert choose_units(units, 2) == [units[1], units[3]]
    assert choose_units(units, 2, skip={units[1]}) == [units[0], units[3]]


@pytest.mark.parametrize(
    "furniture",
    [
        "[DataJunction as Netflix's answer to the modern data stack > ### API First]",
        "[AI-Ready Data vs.",
        "---------------------------------------------------------------------",
        "## **Part 4: Do Not Open The Door**",
        "Layer normalization. arXiv preprint arXiv:1607.06450, 2016.",
        "In Proceedings of the IEEE Conference on Computer Vision, pages 770–778, 2016.",
    ],
)
def test_furniture_never_outranks_a_sentence(furniture):
    sentence = "Stable data creates a shared reference point for teams."
    assert choose_units([furniture, sentence], 1) == [sentence]


def test_a_heading_does_not_cost_the_sentence_after_it():
    unit = "## **Part 1: Mirror, Mirror** ONCE UPON A TIME, a Princess named Snow White lived here."
    assert choose_units([unit], 1) == [unit]


def test_a_card_quotes_the_sentence_that_carries_its_answer():
    units = ["The swineherd filled the bread baskets as fast as he could.", "He mixed wine."]
    unit, coverage = best_unit("He filled the baskets as fast as he could.", units)
    assert unit == units[0]
    assert coverage >= MIN_ANSWER_COVERAGE


def test_an_answer_no_sentence_carries_falls_below_the_floor():
    units = ["Temporal bounds constrain the allowed time window for completing a pattern."]
    _unit, coverage = best_unit("The passage does not explicitly state what these are.", units)
    assert coverage < MIN_ANSWER_COVERAGE


def test_the_coverage_floor_sits_between_its_two_graded_cases():
    unit = (
        "Any other expression on the left side is a syntax error (we will see exceptions to this "
        "rule later)."
    )
    bad = (
        "The passage states that any other expression on the left side results in a syntax error "
        "rather than giving a reason for allowing it elsewhere."
    )
    assert best_unit(bad, [unit])[1] < MIN_ANSWER_COVERAGE
    verse = (
        "Therefore, arise, thou Son of Kunti! brace Thine arm for conflict, nerve thy heart to "
        "meet-- As things alike to thee--pleasure or pain, Profit or ruin, victory or defeat: So "
        "minded, gird thee to the fight, for so Thou shalt not sin!"
    )
    assert best_unit("for so he shall not sin!", [verse])[1] >= MIN_ANSWER_COVERAGE


PLAY_SCENE = (
    "HAMLET. Let the bloat King tempt you again to bed, Pinch wanton on your cheek. "
    "QUEEN. What shall I do? Laertes' Effect"
)


@pytest.mark.parametrize(
    ("question", "unshown"),
    [
        ("What plan does King Polonius propose?", ["Polonius"]),
        ("What does Hamlet tell the Queen to let the King do?", []),
        ("What did Hamlet's speech ask of the Queen?", []),
        ("What is Laertes' role?", []),
        ("Who first stated the Law of Eﬀect?", ["Law"]),
        ("Polonius asks what of the Queen?", []),
    ],
)
def test_a_name_the_passage_never_gives_is_found(question, unshown):
    assert names_not_in(question, PLAY_SCENE) == unshown


@pytest.mark.parametrize(
    "question",
    [
        "How do you use this system based on sentence five?",
        "What actions does one not need to perform according to sentence 4?",
        "What happens to things over time according to the first paragraph?",
        "Why does §4.2 dominate the fused ranking?",
        "How does BM25 contribute uniquely to understanding the given concept?",
        "How did Linux start according to [Debugging]?",
        "Why does the text argue against a hard line between premises and conclusions?",
        "What does the sentence say about one who acts with detachment?",
        "What does the speaker wish to do during the lesson?",
        "What did I exclaim after listening to the professor?",
        "What effect did the professor's words have on me?",
    ],
)
def test_a_question_may_not_point_at_a_position_in_the_prompt(question):
    verdict = card_rejection(question, "A real answer of sufficient length.")
    assert verdict is not None and verdict[0] == REJECT_DEICTIC


@pytest.mark.parametrize(
    "question",
    [
        "What does a cross-encoder feed through the transformer as `[Query, Document]`?",
        "What does the list [1] hold after append?",
        "What type does List[Int] describe?",
        "What is a Type I error in hypothesis testing?",
        "Why must the instruction encode its operand size using the 'I' flag?",
        "What does the sentence 'The penny dropped' mean?",
    ],
)
def test_brackets_that_are_not_a_section_label_are_allowed(question):
    assert card_rejection(question, "A real answer of sufficient length.") is None


@pytest.mark.parametrize(
    "answer",
    [
        "The text does not state what is assumed to be equivalent.",
        "The passage does not explicitly state what these bounds are.",
        "[The context preceding this sentence].",
    ],
)
def test_an_answer_that_concedes_there_is_none_is_rejected(answer):
    verdict = card_rejection("What is assumed to be equivalent to the fetal dose?", answer)
    assert verdict is not None and verdict[0] == REJECT_EMPTY_FIELD


@pytest.mark.parametrize("answer", ["[1, 2, 3]", "['alice', 'bob']", "It returns [True, False]."])
def test_a_bracketed_value_is_still_an_answer(answer):
    assert card_rejection("What does sorted([3, 1, 2]) return here?", answer) is None


def _llm(cards: list[dict]) -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=json.dumps({"cards": cards}))
    return llm


async def test_unit_cards_quote_the_supporting_sentence_not_the_models_number():
    text = (
        "The swineherd filled the bread baskets with bread as fast as he could.\n"
        "He mixed wine also in bowls of ivy-wood and took his seat facing Ulysses.\n"
    )
    # The model labels the bread card with the wine sentence's number, as it did on 31 of 149.
    llm = _llm(
        [
            {
                "id": 2,
                "question": "How did the swineherd fill the baskets?",
                "answer": "With bread as fast as he could.",
            }
        ]
    )
    cards = await _unit_cards(llm, text, 2, set(), None, "doc")
    assert cards[0]["source_excerpt"].startswith("The swineherd filled")


async def test_unit_cards_drop_a_pasted_sentence_and_an_unsupported_answer():
    text = "A metrics platform does not need a flashy front-end to deliver its value to users.\n"
    before = dict(llm_output_stats.snapshot()["counts"])
    llm = _llm(
        [
            {
                "id": 1,
                "question": "A metrics platform does not need a flashy front-end",
                "answer": "Its core is the semantic layer.",
            },
            {
                "id": 1,
                "question": "What does a metrics platform not need?",
                "answer": "Quarterly revenue forecasts from finance.",
            },
        ]
    )
    assert await _unit_cards(llm, text, 1, set(), None, "doc") == []
    after = llm_output_stats.snapshot()["counts"]
    moved = {k: after[k] - before.get(k, 0) for k in after}
    assert moved["card_reject_not_a_question"] == 1
    assert moved["card_reject_ungrounded"] == 1


async def test_unit_cards_drop_a_question_naming_someone_the_passage_does_not():
    text = "One of her maids who knew what she was doing told us, and we caught her at work.\n"
    llm = _llm(
        [
            {
                "id": 1,
                "question": "Who told Telemachus that Arachne was undoing her work?",
                "answer": "One of her maids who knew what she was doing.",
            },
            {
                "id": 1,
                "question": "Who told the suitors she was undoing her work?",
                "answer": "One of her maids who knew what she was doing.",
            },
        ]
    )
    cards = await _unit_cards(llm, text, 1, set(), None, "doc")
    assert [c["question"] for c in cards] == ["Who told the suitors she was undoing her work?"]


async def test_a_speech_is_listed_with_its_speaker_and_quoted_verbatim():
    llm = _llm(
        [
            {
                "id": 1,
                "question": "What does Laertes say nature does not do alone?",
                "answer": "Nature crescent does not grow alone in thews and bulk.",
            }
        ]
    )
    cards = await _unit_cards(llm, PLAY, 1, set(), None, "doc")
    assert "1. Laertes says: For nature crescent" in llm.generate.call_args.args[0]
    assert cards[0]["source_excerpt"].startswith("For nature crescent")


async def test_a_later_batch_asks_about_sentences_not_yet_used():
    text = (
        "The first long sentence about consensus protocols and their failure modes.\n"
        "The second long sentence about leader election under network partitions.\n"
    )
    asked: set[str] = set()
    llm = _llm([])
    await _unit_cards(llm, text, 1, asked, None, "doc")
    await _unit_cards(llm, text, 1, asked, None, "doc")
    listed = [
        c.args[0].split("Sentences:\n")[1].split("\n")[0] for c in llm.generate.call_args_list
    ]
    assert sorted(line[3:13] for line in listed) == ["The first ", "The second"]


@pytest.fixture()
def unit_first(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("FLASHCARD_UNIT_SELECTION", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("FLASHCARD_UNIT_SELECTION")
    get_settings.cache_clear()


async def test_generate_takes_the_unit_path_when_it_is_on(test_db, unit_first):
    _engine, factory, _tmp = test_db
    text = (
        "Ulysses ordered his men to plug their ears with wax before they passed the Sirens.\n"
        "He himself was tied to the mast so that he could hear the song without steering away.\n"
    )
    async with factory() as session:
        session.add(
            DocumentModel(
                id="d1",
                title="The Odyssey",
                format="txt",
                content_type="notes",
                word_count=40,
                page_count=1,
                file_path="/tmp/o.txt",
                stage="complete",
            )
        )
        session.add(
            ChunkModel(
                id="c1",
                document_id="d1",
                section_id=None,
                text=text,
                token_count=40,
                page_number=1,
                chunk_index=0,
            )
        )
        await session.commit()

    llm = _llm(
        [
            {
                "id": 1,
                "question": "What did Ulysses order his men to do?",
                "answer": "Plug their ears with wax before they passed the Sirens.",
            }
        ]
    )
    async with factory() as session:
        with (
            patch("app.services.flashcard.get_llm_service", return_value=llm),
            patch("app.services.embedder.get_embedding_service", side_effect=RuntimeError),
        ):
            cards = await FlashcardService().generate(
                document_id="d1", scope="full", section_heading=None, count=1, session=session
            )

    assert llm.generate.call_args.kwargs["system"].startswith("You write flashcards")
    assert [c.source_excerpt for c in cards] == [text.splitlines()[0]]
