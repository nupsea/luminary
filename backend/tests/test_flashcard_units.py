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


def test_a_section_label_stays_with_its_own_paragraph():
    text = "The last sentence of chunk one.\n\n[Book XII]\nUlysses was tied to the mast."
    units = split_units(text)
    assert units[0] == "The last sentence of chunk one."
    assert units[1] == "[Book XII] Ulysses was tied to the mast."


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


@pytest.mark.parametrize(
    "question",
    [
        "How do you use this system based on sentence five?",
        "What actions does one not need to perform according to sentence 4?",
        "What happens to things over time according to the first paragraph?",
        "Why does §4.2 dominate the fused ranking?",
        "How does BM25 contribute uniquely to understanding the given concept?",
        "How did Linux start according to [Debugging]?",
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
