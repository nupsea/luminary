"""The quiz endpoints over HTTP, with a stub model writing items from the passage it is given."""

import asyncio
import json
import re
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
from app.services import quiz_builder, quiz_service
from app.services.quiz_parsers import ParsedItem, ParsedOption, QuizRefusal
from tests.factories import make_card, make_chunk, make_document, make_section

TOPICS = ["replication", "partitioning", "transactions", "consistency"]


def _sentences(topic: str, n: int) -> list[str]:
    return [
        f"Fact {i} about {topic} says that the {topic} layer handles case number {i} with care."
        for i in range(n)
    ]


class StubLLM:
    """Writes a clean item: right options quote the passage's first sentences."""

    def __init__(self, fail: bool = False, garbled: int = 0) -> None:
        self.calls = 0
        self.fail = fail
        self.garbled = garbled

    async def generate(self, prompt: str, system: str = "", **kwargs) -> str:
        self.calls += 1
        if self.fail:
            raise ConnectionError("connection refused")
        if self.calls <= self.garbled:
            return "Here is a question about the passage."
        passage = prompt.split('"""')[1].strip()
        n_options = int(re.search(r"exactly (\d) options", prompt).group(1))
        n_right = int(re.search(r"exactly (\d) of them", prompt).group(1))
        sentences = [s.strip() for s in passage.split(".") if len(s.split()) >= 6]
        right = [
            {
                "text": f"Claim {i}: {sentences[i][:40]}",
                "correct": True,
                "quote": sentences[i],
                "why": "stated",
            }
            for i in range(n_right)
        ]
        wrong = [
            {
                "text": f"Invented claim {i} about something else entirely",
                "correct": False,
                "mistake": "neighbour",
                "why": "not stated",
            }
            for i in range(n_options - n_right)
        ]
        topic = re.search(r"about (\w+) says", passage).group(1)
        return json.dumps(
            {"question": f"What holds for the {topic} layer?", "options": right + wrong}
        )


def _cosines(texts):
    n = len(texts)
    return np.full((n, n), 0.5) + np.eye(n) * 0.5


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
    llm = StubLLM()
    with (
        patch("app.services.llm.get_llm_service", return_value=llm),
        patch.object(quiz_builder, "_cosines", _cosines),
    ):
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
    assert stub.calls == 3
    for q in quiz["questions"]:
        assert q["level"] == "medium" and q["kind"] == "single" and q["select_count"] == 1
        assert q["origin"] == "model" and q["support_check"] == "unchecked"
        assert not q["revealed"]
        assert all(o["is_correct"] is None and o["quote"] is None for o in q["options"])
    # Each question was written from its own section.
    assert len({q["section_id"] for q in quiz["questions"]}) == 3


@pytest.mark.asyncio
async def test_a_question_refused_on_every_try_does_not_end_the_quiz(library):
    llm = StubLLM(garbled=3)
    with (
        patch("app.services.llm.get_llm_service", return_value=llm),
        patch.object(quiz_builder, "_cosines", _cosines),
    ):
        quiz = await _quiz(library, question_count=1)
    # Three refused writes used three passages; the fourth passage gave the question.
    assert (llm.calls, quiz["status"], len(quiz["questions"])) == (4, "ready", 1)


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
    assert right["quote"] == _sentences("replication", 1)[0].rstrip(".")
    assert all(
        o["trap"] == "related_but_different" for o in revealed["options"] if not o["is_correct"]
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
    assert results["traps"] == [{"trap": "related_but_different", "shown": 9, "picked": 1}]
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
    with (
        patch("app.services.llm.get_llm_service", return_value=StubLLM(fail=True)),
        patch.object(quiz_builder, "_cosines", _cosines),
    ):
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
            ParsedOption("right one", True, "", quote="q"),
            ParsedOption("wrong one", False, "", trap="near_miss_detail"),
        ],
    )


@pytest.mark.asyncio
async def test_options_that_say_the_same_thing_are_refused():
    with patch.object(quiz_builder, "_cosines", lambda texts: np.array([[1.0, 0.97], [0.97, 1.0]])):
        with pytest.raises(QuizRefusal) as caught:
            await quiz_builder.measure_options(_parsed(), "hard")
    assert caught.value.kind == "duplicate_options" and "0.970" in caught.value.message


@pytest.mark.asyncio
async def test_key_similarity_is_the_cosine_to_the_nearest_right_option():
    with patch.object(quiz_builder, "_cosines", lambda texts: np.array([[1.0, 0.8], [0.8, 1.0]])):
        assert await quiz_builder.measure_options(_parsed(), "hard") == [None, pytest.approx(0.8)]


async def _judged(verdicts: dict[str, str], checker="judge", writer="writer"):
    async def fake_check(question, answer, passage, *, checker, llm):
        assert question.startswith("What holds?\n") and "one of several options" in question
        return verdicts[answer]

    with (
        patch.object(quiz_builder, "factuality_model", return_value=checker),
        patch.object(quiz_builder, "effective_generation_model", return_value=writer),
        patch.object(quiz_builder, "check_answer", fake_check),
    ):
        return await quiz_builder.judge(_parsed(), "passage", llm=None)


@pytest.mark.asyncio
async def test_the_judge_supports_an_item_only_when_every_option_is_judged():
    assert await _judged({"right one": "supported", "wrong one": "unsupported"}) == "supported"
    assert await _judged({"right one": "supported", "wrong one": "unverifiable"}) == "unchecked"


@pytest.mark.asyncio
async def test_the_judge_refuses_a_wrong_option_it_finds_true_and_a_right_one_it_does_not():
    with pytest.raises(QuizRefusal) as caught:
        await _judged({"right one": "supported", "wrong one": "supported"})
    assert caught.value.kind == "wrong_option_supported"
    with pytest.raises(QuizRefusal) as caught:
        await _judged({"right one": "unsupported", "wrong one": "unsupported"})
    assert caught.value.kind == "right_option_unsupported"


@pytest.mark.asyncio
async def test_the_writer_never_judges_its_own_options():
    verdicts = {"right one": "supported", "wrong one": "supported"}
    assert await _judged(verdicts, checker="same", writer="same") == "unchecked"
    assert await _judged(verdicts, checker="") == "unchecked"
