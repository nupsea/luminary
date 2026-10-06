"""Chapter cards (#231): one card per study note, gated, stored held until practised."""

import json
import re
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import func, select

from app.models import (
    ChunkModel,
    DocumentModel,
    FlashcardModel,
    ReadingPositionModel,
    SectionModel,
)
from app.repos.flashcard_repo import FlashcardRepo
from app.repos.study_repo import DueScope, StudyRepo
from app.services import chapter_backfill, chapter_cards
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
        self.foreground = 0

    async def generate(self, prompt: str, *, system: str, **kw) -> str:
        self.calls += 1
        self.foreground += not kw.get("background")
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
    # Background: stays on this machine in Hybrid mode and yields to the user.
    assert fakes.calls > 0 and fakes.foreground == 0

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


# -- writing the rest as the reader goes ---------------------------------------------------------

# Long enough that the document is not one chapter (chapters.WHOLE_DOCUMENT_CHARS).
_CHAPTER_TEXT = (LOG + " ") * 120


@pytest.fixture
async def long_book(memory_db):
    async with memory_db.factory() as session:
        session.add(
            DocumentModel(id="bk", title="DDIA", format="pdf", content_type="book", file_path="/x")
        )
        for i in range(5):
            sid = f"ch{i}"
            session.add(
                SectionModel(
                    id=sid,
                    document_id="bk",
                    heading=f"Chapter {i + 1}. Part",
                    level=1,
                    section_order=i,
                )
            )
            session.add(
                ChunkModel(
                    id=f"k{i}", document_id="bk", section_id=sid, text=_CHAPTER_TEXT, chunk_index=i
                )
            )
        await session.commit()
    return memory_db


async def _written(db) -> set[str]:
    async with db.factory() as session:
        return await FlashcardRepo(session).chapters_written("bk")


async def _read_at(db, section_id: str) -> None:
    async with db.factory() as session:
        session.add(ReadingPositionModel(document_id="bk", last_section_id=section_id))
        await session.commit()


async def test_ingestion_writes_only_the_first_chapters(long_book, fakes):
    await chapter_cards.chapter_cards_handler("bk", "job")
    assert await _written(long_book) == {"ch0", "ch1"}


async def test_nothing_beyond_ingestion_for_a_book_nobody_opened(long_book, fakes):
    await chapter_cards.chapter_cards_handler("bk", "job")
    assert await chapter_backfill.next_chapter() is None


async def test_the_chapter_being_read_and_the_next_come_first(long_book, fakes):
    await chapter_cards.chapter_cards_handler("bk", "job")
    await _read_at(long_book, "ch2")

    pick = await chapter_backfill.next_chapter()
    assert (pick.chapter.id, pick.ahead) == ("ch2", True)

    async with long_book.factory() as session:
        repo = FlashcardRepo(session)
        await repo.record_chapter_written("bk", "ch2", 0)
        await repo.record_chapter_written("bk", "ch3", 0)
        await session.commit()
    pick = await chapter_backfill.next_chapter()
    assert (pick.chapter.id, pick.ahead) == ("ch4", False)


async def test_a_reader_in_the_pdf_view_is_placed_by_page(long_book, fakes):
    """The PDF view saves a page and no section; reading chapter 3 there is not chapter 1."""
    from sqlalchemy import update

    await chapter_cards.chapter_cards_handler("bk", "job")
    async with long_book.factory() as session:
        for i in range(5):
            await session.execute(
                update(ChunkModel).where(ChunkModel.id == f"k{i}").values(page_number=10 * i + 5)
            )
        session.add(ReadingPositionModel(document_id="bk", last_pdf_page=25))
        await session.commit()

    pick = await chapter_backfill.next_chapter()
    assert (pick.chapter.id, pick.ahead) == ("ch2", True)


@pytest.mark.parametrize(
    ("plugged", "percent", "ahead", "blocked"),
    [
        (False, 90, False, "on battery"),
        (False, 20, True, "battery low"),
        (False, 90, True, None),
        (True, 10, False, None),
    ],
)
def test_battery_policy(monkeypatch, plugged, percent, ahead, blocked):
    battery = SimpleNamespace(percent=percent, power_plugged=plugged)
    monkeypatch.setattr(chapter_backfill.psutil, "sensors_battery", lambda: battery)
    assert chapter_backfill._battery_reason(ahead) == blocked


async def test_later_chapters_wait_while_the_learner_is_asking(monkeypatch, memory_db):
    from app.services import llm_admission

    async with llm_admission.interactive_call():
        assert await chapter_backfill._idle_reason() == "in use"
    # The quiet period after the question still counts as in use.
    assert await chapter_backfill._idle_reason() == "in use"


async def test_a_chapter_that_yields_no_card_is_not_written_again(long_book, fakes, monkeypatch):
    async def no_cards(*_a, **_kw):
        return []

    monkeypatch.setattr(chapter_cards, "write_chapter_cards", no_cards)

    async def now(_pick):
        return None

    monkeypatch.setattr(chapter_backfill, "not_now", now)
    await _read_at(long_book, "ch0")
    assert (await chapter_backfill.run_once())[0] is True
    assert (await chapter_backfill.run_once())[0] is True
    assert await _written(long_book) == {"ch0", "ch1"}


async def test_a_chapter_is_never_written_twice_at_once(long_book, fakes, monkeypatch):
    import asyncio

    release = asyncio.Event()
    real = chapter_cards.write_chapter_cards

    async def slow(*a, **kw):
        await release.wait()
        return await real(*a, **kw)

    monkeypatch.setattr(chapter_cards, "write_chapter_cards", slow)
    first = asyncio.create_task(chapter_cards.chapter_cards_handler("bk", "job"))
    await asyncio.sleep(0)
    while not chapter_cards.being_written("bk"):
        await asyncio.sleep(0.01)

    # The backfill passes over the chapter ingestion is writing, waits rather than write the
    # next one alongside it, and refuses the first if handed it.
    await _read_at(long_book, "ch0")
    pick = await chapter_backfill.next_chapter()
    assert pick.chapter.id == "ch1"
    assert await chapter_backfill.not_now(pick) == "a chapter is being written"
    async with long_book.factory() as session:
        chapters = await chapter_cards.chapters_for_document("bk", "DDIA", session)
        assert await chapter_cards.write_chapter("bk", "DDIA", chapters[0], "", session) is None

    release.set()
    await first
    assert await _written(long_book) == {"ch0", "ch1"}
    assert not chapter_cards.being_written("bk")


async def test_a_machine_booted_moments_ago_with_no_question_is_quiet(monkeypatch):
    monkeypatch.setattr(chapter_backfill.time, "monotonic", lambda: 10.0)
    assert chapter_backfill._learner_quiet() is True


async def test_a_model_the_backfill_loaded_is_unloaded_when_work_runs_out(monkeypatch):
    unloaded: list[str] = []
    steps = iter([(True, "qwen3.5:4b"), (True, None), (False, None)])

    async def run_once():
        return next(steps)

    async def unload(model):
        unloaded.append(model)

    monkeypatch.setattr(chapter_backfill, "run_once", run_once)
    monkeypatch.setattr(chapter_backfill, "_unload", unload)
    backfill = chapter_backfill.ChapterBackfill()
    assert [await backfill._step() for _ in range(3)] == [True, True, False]
    assert unloaded == ["qwen3.5:4b"]


async def test_a_model_already_loaded_is_left_for_the_learner(monkeypatch):
    unloaded: list[str] = []

    async def run_once():
        return False, None

    async def unload(model):
        unloaded.append(model)

    monkeypatch.setattr(chapter_backfill, "run_once", run_once)
    monkeypatch.setattr(chapter_backfill, "_unload", unload)
    await chapter_backfill.ChapterBackfill()._step()
    assert unloaded == []


# -- practising a chapter --------------------------------------------------------------------


async def test_practising_a_chapter_admits_its_cards_to_review(book, fakes):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    await chapter_cards.chapter_cards_handler("doc", "job")
    async with book.factory() as session:
        assert await StudyRepo(session).due_or_unscheduled_for_document("doc") == []

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = (await client.get("/sections/doc/chapters")).json()["chapters"]
        practised = await client.post("/sections/doc/chapters/s1/practice")
        after = (await client.get("/sections/doc/chapters")).json()["chapters"]
        missing = await client.post("/sections/doc/chapters/nope/practice")

    assert [(c["id"], c["title"], c["cards"], c["held"], c["due"]) for c in before] == [
        ("s1", "DDIA", 1, 1, 0)
    ]
    assert practised.status_code == 200
    assert [c["fsrs_state"] for c in practised.json()] == ["new"]
    assert [(c["held"], c["due"]) for c in after] == [(0, 1)]
    assert missing.status_code == 404
    async with book.factory() as session:
        assert await StudyRepo(session).count_due(DueScope(document_ids=["doc"])) == 1


async def test_dont_ask_for_this_book_is_remembered(book):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = (await client.get("/sections/doc/chapters")).json()["ask_at_chapter_end"]
        off = await client.put("/sections/doc/chapters/prompt", json={"ask_at_chapter_end": False})
        later = (await client.get("/sections/doc/chapters")).json()["ask_at_chapter_end"]
        unknown = await client.put(
            "/sections/nope/chapters/prompt", json={"ask_at_chapter_end": False}
        )

    assert (first, off.status_code, later, unknown.status_code) == (True, 204, False, 404)
