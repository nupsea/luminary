"""Chapter cards (#231): one card per study note, gated, stored held until practised."""

import json
import re

import numpy as np
import pytest
from sqlalchemy import func, select

from app.models import ChunkModel, DocumentModel, FlashcardModel, SectionModel
from app.repos.study_repo import DueScope, StudyRepo
from app.services import chapter_cards
from app.services.flashcard_chapter import (
    MAX_CHAPTER_WINDOWS,
    Passage,
    Window,
    build_windows,
    card_from_reply,
)
from app.services.flashcard_prompts import CHAPTER_NOTES_SYSTEM
from app.services.flashcard_units import split_units

LOG = (
    "A log is an append-only sequence of records stored on disk. "
    "Appending to a log is very efficient because every write is sequential. "
    "Finding a key by scanning the whole log takes time proportional to its length."
)
INDEX = (
    "An index is an additional structure derived from the primary data. "
    "Every index speeds up some reads but slows down every write to the database."
)


def _window(text: str, heading: str = "Storage") -> Window:
    return Window(heading=heading, text=text, chunk_ids=["c1"], units=split_units(text))


def _reply(question: str, answer: str) -> str:
    return json.dumps({"question": question, "answer": answer})


def _gate(question: str, answer: str, text: str = LOG, book: str = "DDIA") -> str:
    evidence = split_units(text)[0]
    _, why = card_from_reply(
        _reply(question, answer),
        book=book,
        window=_window(text),
        shown=evidence,
        evidence=evidence,
        known_names="",
        document_id="d",
    )
    return why


def test_a_grounded_standalone_card_passes():
    assert _gate("What is a log in a storage engine?", "An append-only sequence of records") == "ok"


@pytest.mark.parametrize(
    ("question", "answer", "reason"),
    [
        ("A log is what", "An append-only sequence of records", "not a question"),
        ("What is a log in a storage engine?", "A replicated consensus protocol", "no sentence"),
        ("What did the study find about logs?", "An append-only sequence of records", "referent"),
    ],
)
def test_each_gate_fires(question, answer, reason):
    assert reason in _gate(question, answer)


def test_the_narrator_passes_only_when_the_question_names_the_book():
    text = "The narrator descended the well on metal bars made for smaller creatures."
    answer = "On metal bars made for smaller creatures"
    named = "How does the narrator of The Time Machine descend the well?"
    unnamed = "How does the narrator descend the well?"
    assert _gate(named, answer, text, book="The Time Machine") == "ok"
    assert _gate(unnamed, answer, text, book="The Time Machine") != "ok"


def test_windows_drop_reference_lists_and_chunk_overlap():
    tail = LOG[-200:]
    windows = build_windows(
        [
            Passage("c1", LOG, "Logs"),
            Passage("c2", tail + " " + INDEX, "Logs"),
            Passage("c3", "[1] A. Author. In Proceedings of X, pages 1-9, 2001.\n" * 4, "Notes"),
        ]
    )
    assert len(windows) == 1
    assert windows[0].text.count("proportional to its length") == 1
    assert windows[0].chunk_ids == ["c1", "c2"]


def test_a_very_long_chapter_is_sampled_not_read_whole():
    passages = [Passage(f"c{i}", f"Section {i}. " + LOG * 25, f"H{i}") for i in range(80)]
    assert len(build_windows(passages)) == MAX_CHAPTER_WINDOWS


# -- the enrichment job -------------------------------------------------------------------

_WORD = re.compile(r"[a-z]+")


def _embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        v = np.zeros(256, dtype=np.float32)
        for w in _WORD.findall(t.lower()):
            v[hash(w) % 256] += 1.0
        out.append((v / (np.linalg.norm(v) or 1.0)).tolist())
    return out


class _Embedder:
    encode = staticmethod(_embed)


class _FakeLLM:
    """Notes name what a window says; each card answers with its evidence's opening words."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str, *, system: str, **_kw) -> str:
        self.calls += 1
        if system == CHAPTER_NOTES_SYSTEM:
            return json.dumps({"notes": ["A log is an append-only sequence of records."]})
        evidence = prompt.split("Evidence from the book:\n", 1)[1].split("\n")[0]
        return _reply("What is a log in a storage engine?", " ".join(evidence.split()[:8]))


@pytest.fixture
async def book(memory_db):
    async with memory_db.factory() as session:
        session.add(
            DocumentModel(
                id="doc",
                title="DDIA",
                format="pdf",
                content_type="book",
                file_path="/tmp/ddia.pdf",
            )
        )
        session.add(
            SectionModel(id="s1", document_id="doc", heading="Logs", level=1, section_order=0)
        )
        session.add(
            ChunkModel(id="c1", document_id="doc", section_id="s1", text=LOG, chunk_index=0)
        )
        await session.commit()
    return memory_db


@pytest.fixture
def fakes(monkeypatch):
    llm = _FakeLLM()
    import app.services.flashcard as flashcard

    monkeypatch.setattr(flashcard, "get_llm_service", lambda: llm)
    monkeypatch.setattr(chapter_cards, "get_embedding_service", lambda: _Embedder())
    return llm


async def test_the_job_writes_held_cards_outside_the_review_queue(book, fakes):
    await chapter_cards.chapter_cards_handler("doc", "job")

    async with book.factory() as session:
        cards = (await session.execute(select(FlashcardModel))).scalars().all()
        assert len(cards) == 1
        card = cards[0]
        assert (card.fsrs_state, card.due_date, card.chapter_id) == ("held", None, "s1")
        assert card.section_heading == "DDIA"
        assert card.source_chunk_ids == ["c1"]
        assert card.grounding == "verified"
        assert await StudyRepo(session).count_due(DueScope(document_ids=["doc"])) == 0


async def test_a_rerun_skips_chapters_that_already_have_cards(book, fakes):
    await chapter_cards.chapter_cards_handler("doc", "job")
    calls = fakes.calls
    await chapter_cards.chapter_cards_handler("doc", "job")

    assert fakes.calls == calls
    async with book.factory() as session:
        assert (await session.execute(select(func.count(FlashcardModel.id)))).scalar_one() == 1
