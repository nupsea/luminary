"""The quiz endpoints over HTTP, with a stub model writing items from the passage it is given."""

import asyncio
import json
import re
from contextlib import contextmanager
from unittest.mock import patch

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import (
    FlashcardModel,
    MisconceptionModel,
    QuizItemModel,
    QuizOptionModel,
    ReviewEventModel,
    StudySessionModel,
)
from app.services import quiz_builder, quiz_nli, quiz_service
from app.services.quiz_parsers import ParsedItem, ParsedOption, QuizRefusal
from tests.factories import make_card, make_chunk, make_document, make_section

TOPICS = ["replication", "partitioning", "transactions", "consistency"]
WORDS = [
    "amber",
    "birch",
    "cedar",
    "delta",
    "ember",
    "fjord",
    "grove",
    "heron",
    "inlet",
    "juniper",
    "kestrel",
    "lagoon",
]
OTHER = ["oak", "elm", "fir", "yew", "ash", "pine", "teak", "palm"]
MARK = "Indeed"


def _sentences(topic: str, n: int) -> list[str]:
    """Sentence 0 is the longest, so it is each passage's key sentence."""
    return [
        f"Fact {WORDS[i]} about {topic} says that the {topic} layer handles the {WORDS[i]} case "
        f"with care{' and attention' if i == 0 else ''}"
        for i in range(n)
    ]


class StubLLM:
    """A model for each quiz prompt: it phrases the key sentences, writes wrong answers of the
    same length, answers with the material by finding its own right answers, and guesses wrong
    without it unless *guessable*."""

    def __init__(self, fail: bool = False, garbled: int = 0, guessable: bool = False) -> None:
        self.calls = 0
        self.questions = 0
        self.fail = fail
        self.garbled = garbled
        self.guessable = guessable

    async def generate(self, prompt: str, system: str = "", **kwargs) -> str:
        self.calls += 1
        if self.fail:
            raise ConnectionError("connection refused")
        if "KEY SENTENCE" in prompt or "A LIST" in prompt:
            return self._question(prompt)
        if "wrong answers to this question" in prompt:
            return self._wrong(prompt)
        return self._answer(prompt)

    def _question(self, prompt: str) -> str:
        self.questions += 1
        if self.questions <= self.garbled:
            return "Here is a question about the passage."
        keys = re.findall(r'"""\s*(Fact .+?)\s*"""', re.split("KEY SENTENCE|A LIST", prompt)[1])
        topic = re.search(r"about (\w+) says", keys[0]).group(1)
        answers = [
            f"{MARK}, the {topic} layer handles the {re.search(r'Fact (\w+)', k).group(1)} case "
            "with care."
            for k in keys
        ]
        if len(keys) == 1:
            stem = f"How does the {topic} layer treat what it receives?"
            return json.dumps({"question": stem, "answer": answers[0]})
        stem = f"Which statements about the {topic} layer are true?"
        return json.dumps({"question": stem, "answers": answers})

    def _wrong(self, prompt: str) -> str:
        n = int(re.search(r"Write (\d) wrong answers", prompt).group(1))
        topic = re.search(r"QUESTION: .*?the (\w+) layer", prompt).group(1)
        wrong = [
            {
                "text": f"The {topic} layer drops the {OTHER[i]} case it receives without care.",
                "mistake": "belief",
            }
            for i in range(n)
        ]
        return json.dumps({"wrong": wrong})

    def _answer(self, prompt: str) -> str:
        options = re.findall(r"^([A-E])\. (.*)$", prompt, re.MULTILINE)
        right = [letter for letter, text in options if text.startswith(MARK)]
        if "MATERIAL:" in prompt or self.guessable:
            return json.dumps({"answer": right})
        return json.dumps({"answer": [next(c for c, t in options if not t.startswith(MARK))]})


def _cosines(texts):
    n = len(texts)
    return np.full((n, n), 0.5) + np.eye(n) * 0.5


async def _not_entailed(premises, hypothesis):
    """Only the stub's own right answers follow from the material."""
    return 0.9 if hypothesis.startswith(MARK) else 0.0


async def _nowhere(self, text):
    return []


@contextmanager
def _model(llm, entailment=_not_entailed):
    with (
        patch("app.services.llm.get_llm_service", return_value=llm),
        patch.object(quiz_builder, "_cosines", _cosines),
        patch.object(quiz_nli, "entailment", entailment),
        patch.object(quiz_builder._Writer, "elsewhere", _nowhere),
    ):
        yield llm


async def _call(method: str, url: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


async def _settle():
    while quiz_service._background_tasks:
        await asyncio.gather(*list(quiz_service._background_tasks))


@pytest.fixture
async def library(test_db):
    """A document of four sections, one passage each, and a card quoting section one."""
    _, factory, _ = test_db
    doc = make_document(title="Systems")
    rows: list = [doc]
    sections = []
    index = 0
    for order, topic in enumerate(TOPICS):
        section = make_section(document_id=doc.id, heading=topic.title(), section_order=order)
        sections.append(section)
        rows.append(section)
        sentences = _sentences(topic, 12)
        for part in range(3):
            text = ". ".join(sentences[part * 4 : part * 4 + 4]) + "."
            if topic == "consistency" and part == 0:
                # One list in the document, for multi-answer questions.
                items = "\n".join(f"\u2022 {s}" for s in sentences[:4])
                text = f"The consistency layer keeps several promises, including:\n{items}\n"
            rows.append(
                make_chunk(
                    id=f"{topic}-{part}",
                    document_id=doc.id,
                    section_id=section.id,
                    chunk_index=index,
                    text=text,
                )
            )
            index += 1
    card = make_card(
        document_id=doc.id,
        chunk_id="replication-0",
        question="What does the replication layer do with case 0?",
        answer="It handles it with care.",
        source_excerpt=_sentences("replication", 1)[0],
        grounding="verified",
    )
    rows.append(card)
    async with factory() as session:
        session.add_all(rows)
        await session.commit()
    return {"doc": doc, "sections": sections, "card": card, "factory": factory}


@pytest.fixture
def stub():
    with _model(StubLLM()) as llm:
        yield llm


async def _quiz(library, **fields):
    body = {"document_id": library["doc"].id, "difficulty": "medium", "question_kinds": "single"}
    resp = await _call("POST", "/study/quizzes", json=body | fields)
    assert resp.status_code == 201, resp.text
    await _settle()
    return (await _call("GET", f"/study/quizzes/{resp.json()['id']}")).json()


def _right(question, options_by_id):
    return [o for o in question["options"] if options_by_id[o["id"]].is_correct]


async def _options(library):
    async with library["factory"]() as session:
        return {o.id: o for o in (await session.execute(select(QuizOptionModel))).scalars()}


@pytest.mark.asyncio
async def test_a_fixed_quiz_writes_every_question_and_hides_the_answers(library, stub):
    quiz = await _quiz(library, question_count=3)
    assert quiz["status"] == "ready"
    assert len(quiz["questions"]) == 3
    assert stub.questions == 3
    for q in quiz["questions"]:
        assert q["level"] == "medium" and q["kind"] == "single" and q["select_count"] == 1
        assert q["origin"] == "model" and q["support_check"] == "unchecked"
        assert not q["revealed"]
        assert all(o["is_correct"] is None and o["quote"] is None for o in q["options"])
    # Each question was written from its own section.
    assert len({q["section_id"] for q in quiz["questions"]}) == 3


@pytest.mark.asyncio
async def test_a_question_refused_on_every_try_does_not_end_the_quiz(library):
    with _model(StubLLM(garbled=3)) as llm:
        quiz = await _quiz(library, question_count=1)
    # Three refused writes used three passages; the fourth passage gave the question.
    assert (llm.questions, quiz["status"], len(quiz["questions"])) == (4, "ready", 1)


@pytest.mark.asyncio
async def test_a_miss_resets_the_linked_card_and_a_confident_one_opens_a_misconception(
    library, stub
):
    quiz = await _quiz(library, question_count=1)
    [question] = quiz["questions"]
    options = await _options(library)
    wrong = next(o for o in question["options"] if not options[o["id"]].is_correct)
    resp = await _call(
        "POST",
        f"/study/quizzes/{quiz['id']}/answers",
        json={"position": 0, "selected_option_ids": [wrong["id"]], "confidence": "sure"},
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["outcome"] == "wrong" and body["card_reset"] and body["retake"]
    revealed = body["question"]
    assert revealed["revealed"]
    [right] = [o for o in revealed["options"] if o["is_correct"]]
    assert right["quote"] == _sentences("replication", 1)[0] + "."
    assert all(
        o["trap"] == "common_misconception" for o in revealed["options"] if not o["is_correct"]
    )

    async with library["factory"]() as session:
        card = await session.get(FlashcardModel, library["card"].id)
        assert card.fsrs_state != "new" and card.lapses == 1
        [event] = (await session.execute(select(ReviewEventModel))).scalars().all()
        assert event.rating == "again" and event.flashcard_id == card.id
        [miss] = (await session.execute(select(MisconceptionModel))).scalars().all()
        assert miss.user_answer == wrong["text"]


@pytest.mark.asyncio
async def test_a_right_answer_never_touches_the_card(library, stub):
    quiz = await _quiz(library, question_count=1)
    [question] = quiz["questions"]
    right = _right(question, await _options(library))
    resp = await _call(
        "POST",
        f"/study/quizzes/{quiz['id']}/answers",
        json={"position": 0, "selected_option_ids": [right[0]["id"]], "confidence": "sure"},
    )
    assert resp.json()["outcome"] == "correct" and not resp.json()["card_reset"]
    async with library["factory"]() as session:
        card = await session.get(FlashcardModel, library["card"].id)
        assert (card.fsrs_state, card.reps, card.due_date) == (
            "new",
            0,
            library["card"].due_date,
        )
        assert not (await session.execute(select(ReviewEventModel))).scalars().all()


@pytest.mark.asyncio
async def test_exam_mode_reveals_nothing_until_the_finish(library, stub):
    quiz = await _quiz(library, question_count=2, mode="exam")
    q = quiz["questions"][0]
    resp = await _call(
        "POST",
        f"/study/quizzes/{quiz['id']}/answers",
        json={"position": 0, "selected_option_ids": [q["options"][0]["id"]]},
    )
    assert not resp.json()["question"]["revealed"]
    assert all(o["is_correct"] is None for o in resp.json()["question"]["options"])
    done = (await _call("POST", f"/study/quizzes/{quiz['id']}/finish")).json()
    assert done["status"] == "complete"
    assert all(q["revealed"] for q in done["questions"])


@pytest.mark.asyncio
async def test_an_answer_is_given_once_and_only_from_the_questions_options(library, stub):
    quiz = await _quiz(library, question_count=1)
    option = quiz["questions"][0]["options"][0]["id"]
    url = f"/study/quizzes/{quiz['id']}/answers"
    bad = await _call("POST", url, json={"position": 0, "selected_option_ids": ["nope"]})
    assert bad.status_code == 422
    assert (
        await _call("POST", url, json={"position": 0, "selected_option_ids": [option]})
    ).status_code == 200
    again = await _call("POST", url, json={"position": 0, "selected_option_ids": [option]})
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_results_hold_score_calibration_traps_and_sections_to_revisit(library, stub):
    quiz = await _quiz(library, question_count=3)
    options = await _options(library)
    url = f"/study/quizzes/{quiz['id']}/answers"
    plan = [("right", "sure"), ("wrong", "sure"), ("right", "guess")]
    for q, (pick, confidence) in zip(quiz["questions"], plan, strict=True):
        choice = next(o for o in q["options"] if options[o["id"]].is_correct == (pick == "right"))
        await _call(
            "POST",
            url,
            json={
                "position": q["position"],
                "selected_option_ids": [choice["id"]],
                "confidence": confidence,
            },
        )
    done = (await _call("POST", f"/study/quizzes/{quiz['id']}/finish")).json()
    results = done["results"]
    assert (results["answered"], results["correct"], results["score_pct"]) == (3, 2, 66.7)
    calibration = {c["confidence"]: (c["answered"], c["correct"]) for c in results["calibration"]}
    assert calibration == {"sure": (2, 1), "think": (0, 0), "guess": (1, 1)}
    assert results["traps"] == [{"trap": "common_misconception", "shown": 9, "picked": 1}]
    [revisit] = results["revisit"]
    assert revisit["section_id"] == quiz["questions"][1]["section_id"] and revisit["missed"] == 1
    assert results["retake_count"] == 2
    async with library["factory"]() as session:
        study = await session.get(StudySessionModel, (await _quiz_session(library, quiz["id"])))
        assert study.mode == "quiz" and study.ended_at is not None and study.cards_correct == 2

    retake = await _call("POST", f"/study/quizzes/{quiz['id']}/retake")
    assert retake.status_code == 201
    body = retake.json()
    assert body["retake_of"] == quiz["id"] and body["status"] == "ready"
    assert [q["item_id"] for q in body["questions"]] == [
        quiz["questions"][1]["item_id"],
        quiz["questions"][2]["item_id"],
    ]


async def _quiz_session(library, quiz_id):
    from app.models import QuizModel

    async with library["factory"]() as session:
        return (await session.get(QuizModel, quiz_id)).session_id


@pytest.mark.asyncio
async def test_adaptive_writes_each_question_after_the_answer_before_it(library, stub):
    quiz = await _quiz(library, difficulty="adaptive", question_count=3)
    assert [q["level"] for q in quiz["questions"]] == ["medium"]
    for position in range(2):
        options = await _options(library)
        current = (await _call("GET", f"/study/quizzes/{quiz['id']}")).json()
        q = current["questions"][position]
        await _call(
            "POST",
            f"/study/quizzes/{quiz['id']}/answers",
            json={"position": position, "selected_option_ids": [_right(q, options)[0]["id"]]},
        )
        await _settle()
    final = (await _call("GET", f"/study/quizzes/{quiz['id']}")).json()
    assert [q["level"] for q in final["questions"]] == ["medium", "medium", "hard"]
    assert final["status"] == "ready"


@pytest.mark.asyncio
async def test_a_second_quiz_takes_unseen_bank_items_before_calling_the_model(library, stub):
    first = await _quiz(library, question_count=2)
    calls = stub.calls
    second = await _quiz(library, question_count=2)
    assert stub.calls == calls
    assert {q["item_id"] for q in second["questions"]} == {q["item_id"] for q in first["questions"]}


@pytest.mark.asyncio
async def test_without_a_model_questions_come_from_grounded_cards(library):
    async with library["factory"]() as session:
        for i in range(4):
            session.add(
                make_card(
                    document_id=library["doc"].id,
                    chunk_id=f"partitioning-{i % 3}",
                    question=f"What does partitioning do with case {i}?",
                    answer=f"It routes case {i} to shard {i}.",
                    source_excerpt=f"Fact {i} about partitioning says",
                    grounding="verified",
                )
            )
        await session.commit()
    with _model(StubLLM(fail=True)):
        quiz = await _quiz(library, question_count=2, difficulty="hard")
    assert quiz["status"] == "ready" and len(quiz["questions"]) == 2
    for q in quiz["questions"]:
        assert q["origin"] == "cards" and q["level"] == "easy" and len(q["options"]) == 4


@pytest.mark.asyncio
async def test_no_model_and_no_cards_is_an_error_with_the_reason(library):
    async with library["factory"]() as session:
        for card in (await session.execute(select(FlashcardModel))).scalars():
            await session.delete(card)
        await session.commit()
    with patch("app.services.llm.get_llm_service", return_value=StubLLM(fail=True)):
        quiz = await _quiz(library, question_count=2)
    assert quiz["status"] == "error" and quiz["error"]
    assert quiz["questions"] == []


@pytest.mark.asyncio
async def test_a_scope_that_names_nothing_in_the_document_is_not_found(library, stub):
    resp = await _call(
        "POST",
        "/study/quizzes",
        json={"document_id": library["doc"].id, "scope_type": "section", "scope_ref": "nope"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_a_section_quiz_stays_in_its_section(library, stub):
    section = library["sections"][2]
    quiz = await _quiz(library, scope_type="section", scope_ref=section.id, question_count=3)
    # One passage in the section, so one question, and the quiz says so.
    assert quiz["question_count"] == 1
    assert [q["section_id"] for q in quiz["questions"]] == [section.id]


@pytest.mark.asyncio
async def test_a_single_answer_item_becomes_a_grounded_card(library, stub):
    quiz = await _quiz(library, question_count=3)
    unlinked = next(q for q in quiz["questions"] if q["section_id"] != library["sections"][0].id)
    resp = await _call("POST", f"/study/quiz-items/{unlinked['item_id']}/to-card")
    assert resp.status_code == 201, resp.text
    async with library["factory"]() as session:
        card = await session.get(FlashcardModel, resp.json()["flashcard_id"])
        assert card.grounding == "verified" and card.question == unlinked["stem"]
        item = await session.get(QuizItemModel, unlinked["item_id"])
        assert item.flashcard_id == card.id
    again = await _call("POST", f"/study/quiz-items/{unlinked['item_id']}/to-card")
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_a_multi_answer_item_does_not_become_a_card(library, stub):
    quiz = await _quiz(library, question_count=2, question_kinds="multi")
    item = quiz["questions"][0]
    assert item["kind"] == "multi" and item["select_count"] in (2, 3)
    resp = await _call("POST", f"/study/quiz-items/{item['item_id']}/to-card")
    assert resp.status_code == 422


def _parsed() -> ParsedItem:
    return ParsedItem(
        stem="What holds?",
        options=[
            ParsedOption(f"{MARK} right one", True, quote="q"),
            ParsedOption("wrong one", False, trap="near_miss_detail"),
        ],
    )


@pytest.mark.asyncio
async def test_options_that_say_the_same_thing_are_refused():
    with patch.object(quiz_builder, "_cosines", lambda texts: np.array([[1.0, 0.97], [0.97, 1.0]])):
        with pytest.raises(QuizRefusal) as caught:
            await quiz_builder.measure_options(_parsed())
    assert caught.value.kind == "duplicate_options" and "0.970" in caught.value.message


@pytest.mark.asyncio
async def test_key_similarity_is_the_cosine_to_the_nearest_right_option():
    with patch.object(quiz_builder, "_cosines", lambda texts: np.array([[1.0, 0.8], [0.8, 1.0]])):
        assert await quiz_builder.measure_options(_parsed()) == [None, pytest.approx(0.8)]


@pytest.mark.asyncio
async def test_a_wrong_answer_the_material_states_is_dropped_and_too_few_refuse_the_question(
    library,
):
    async def states_the_oak_case(premises, hypothesis):
        return 0.9 if " oak " in hypothesis or hypothesis.startswith(MARK) else 0.0

    with _model(StubLLM(), entailment=states_the_oak_case):
        quiz = await _quiz(library, question_count=1)
    options = await _options(library)
    texts = [options[o["id"]].text for o in quiz["questions"][0]["options"]]
    assert not any(" oak " in t for t in texts) and len(texts) == 4

    async def states_everything(premises, hypothesis):
        return 0.9

    with _model(StubLLM(), entailment=states_everything):
        empty = await _quiz(library, question_count=1, difficulty="hard")
    assert empty["questions"] == [] and empty["status"] == "error"


@pytest.mark.asyncio
async def test_a_question_guessed_without_the_material_is_refused_above_easy(library):
    with _model(StubLLM(guessable=True)):
        medium = await _quiz(library, question_count=1, difficulty="medium")
        easy = await _quiz(library, question_count=1, difficulty="easy")
    assert medium["questions"] == []
    assert len(easy["questions"]) == 1


class _Judge:
    """Answers the open-book check with *picks*: "right" for the item's right letters."""

    def __init__(self, picks) -> None:
        self.picks = picks
        self.models: list[str | None] = []

    async def generate(self, prompt, **kwargs):
        self.models.append(kwargs.get("model"))
        assert "MATERIAL:" in prompt
        options = re.findall(r"^([A-E])\. (.*)$", prompt, re.MULTILINE)
        if self.picks == "right":
            return json.dumps({"answer": [c for c, t in options if t.startswith(MARK)]})
        return json.dumps({"answer": self.picks})


async def _judged(picks, checker="judge", writer="writer"):
    judge = _Judge(picks)
    with (
        patch.object(quiz_builder, "factuality_model", return_value=checker),
        patch.object(quiz_builder, "effective_generation_model", return_value=writer),
    ):
        verdict = await quiz_builder._judge(
            quiz_builder._Writer(llm=judge, model=None, document_id="d"), _parsed(), "passage"
        )
    assert judge.models in ([], [checker])
    return verdict


@pytest.mark.asyncio
async def test_the_judge_supports_only_the_right_answers_and_never_its_own_writing():
    assert await _judged("right") == "supported"
    with pytest.raises(QuizRefusal) as caught:
        await _judged(["A", "B"])
    assert caught.value.kind == "not_answerable"
    assert await _judged(["A", "B"], checker="same", writer="same") == "unchecked"
    assert await _judged(["A", "B"], checker="") == "unchecked"


@pytest.mark.asyncio
async def test_deleting_a_card_unties_the_item_that_tested_it(library, stub):
    from app.repos.flashcard_repo import FlashcardRepo

    quiz = await _quiz(library, question_count=1)
    item_id = quiz["questions"][0]["item_id"]
    async with library["factory"]() as session:
        assert (await session.get(QuizItemModel, item_id)).flashcard_id == library["card"].id
        await FlashcardRepo(session).delete_by_id(library["card"].id)
    async with library["factory"]() as session:
        item = await session.get(QuizItemModel, item_id)
        assert item is not None and item.flashcard_id is None


@pytest.mark.asyncio
async def test_deleting_a_document_takes_its_quizzes_items_and_answers(library, stub):
    from app.models import DocumentModel, QuizAttemptModel, QuizModel
    from app.services.document_deletion_service import DocumentDeletionService

    quiz = await _quiz(library, question_count=2)
    q = quiz["questions"][0]
    await _call(
        "POST",
        f"/study/quizzes/{quiz['id']}/answers",
        json={"position": 0, "selected_option_ids": [q["options"][0]["id"]]},
    )
    async with library["factory"]() as session:
        doc = await session.get(DocumentModel, library["doc"].id)
        await DocumentDeletionService().delete_sqlite_cascade(session, doc)
        await session.commit()
    async with library["factory"]() as session:
        for model in (QuizModel, QuizItemModel, QuizOptionModel, QuizAttemptModel):
            assert not (await session.execute(select(model))).scalars().all(), model.__name__


@pytest.mark.asyncio
async def test_an_answer_no_key_sentence_entails_is_refused():
    async def entails(premises, hypothesis):
        return 0.9 if premises == ["key one"] and hypothesis == "answer one" else 0.0

    with patch.object(quiz_nli, "entailment", entails):
        await quiz_builder._check_keys(["answer one"], ["key one"])
        with pytest.raises(QuizRefusal) as caught:
            await quiz_builder._check_keys(["answer one", "answer two"], ["key one", "key two"])
    assert caught.value.kind == "answer_off_key" and "answer two" in caught.value.message


@pytest.mark.asyncio
async def test_without_the_entailment_model_no_question_is_written(library):
    from app.exceptions import ModelNotDownloaded

    async def missing(premises, hypothesis):
        raise ModelNotDownloaded("facebook/bart-large-mnli is not downloaded.", model="nli")

    with _model(StubLLM(), entailment=missing):
        quiz = await _quiz(library, question_count=1)
    assert all(q["origin"] != "model" for q in quiz["questions"])
