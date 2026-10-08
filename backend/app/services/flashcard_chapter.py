"""Chapter cards (#231): what a chapter is about decides what gets asked.

Per window of about 3.5k characters the model writes the 1-3 ideas a student should learn,
and every idea becomes one card, written from the idea and the sentences that carry it. A 4B
summarises well and was measured bad at choosing what to ask from raw sentences (#191); every
selection step tried over the notes (centrality, the model's own pick, its ranking) picked
worse than taking them all in reading order.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.services.enrichment_concurrency import get_enrichment_llm_semaphore
from app.services.flashcard import _is_reference_chunk
from app.services.flashcard_parsers import _parse_llm_response, card_field, card_rejection
from app.services.flashcard_prompts import (
    CHAPTER_CARD_USER_TMPL,
    CHAPTER_NOTES_USER_TMPL,
    chapter_card_system,
    chapter_notes_system,
)
from app.services.flashcard_units import (
    MIN_ANSWER_COVERAGE,
    _content,
    _learnable_words,
    best_unit,
    names_not_in,
    split_units,
)

logger = logging.getLogger(__name__)

WINDOW_CHARS = 3500
MIN_WINDOW_CHARS = 600
# Work per chapter is bounded by sampling windows evenly past this many: DDIA's longest chapter
# (176k characters, 50 windows) is read whole, the IBM manual's 1.48M-character instruction
# reference is not.
MAX_CHAPTER_WINDOWS = 50
# Overlapping chunks repeat up to this many characters of the chunk before them.
_MAX_OVERLAP = 800
_MIN_OVERLAP = 40

Embed = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class Book:
    """What the chapter prompts and gates know of the document."""

    title: str
    genre: str
    # Names the entity graph holds, allowed in a question its window does not show.
    known_names: str = ""
    # PERSON entities of two or more words; one-word ones are noise on technical books
    # ("users", "flink" on apache-iceberg would refuse 33 of its 278 cards).
    people: tuple[str, ...] = ()


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    text: str
    heading: str


@dataclass
class Window:
    heading: str
    text: str = ""
    chunk_ids: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)

    def add(self, passage: Passage, text: str) -> None:
        if passage.heading not in self.heading.split(" / "):
            self.heading = f"{self.heading} / {passage.heading}"
        self.text = f"{self.text}\n\n{text}" if self.text else text
        self.chunk_ids.append(passage.chunk_id)


@dataclass(frozen=True)
class ChapterCard:
    question: str
    answer: str
    source_excerpt: str
    window: Window


def _without_overlap(prev: str, nxt: str) -> str:
    for k in range(min(_MAX_OVERLAP, len(prev), len(nxt)), _MIN_OVERLAP, -1):
        if prev.endswith(nxt[:k]):
            return nxt[k:]
    return nxt


def _opens_window(cur: Window, heading: str, text: str) -> bool:
    """A new window starts when this one is full, or at a section that would overfill it."""
    if len(cur.text) >= WINDOW_CHARS:
        return True
    new_section = heading not in cur.heading.split(" / ")
    return (
        new_section
        and len(cur.text) >= MIN_WINDOW_CHARS
        and len(cur.text) + len(text) > WINDOW_CHARS
    )


def _sampled(windows: list[Window]) -> list[Window]:
    if len(windows) <= MAX_CHAPTER_WINDOWS:
        return windows
    step = len(windows) / MAX_CHAPTER_WINDOWS
    return [windows[int(i * step)] for i in range(MAX_CHAPTER_WINDOWS)]


def _readable(passages: Sequence[Passage]) -> Iterator[tuple[Passage, str]]:
    """Each passage's own text: reference lists dropped, overlap with the one before removed."""
    prev = ""
    for p in passages:
        if _is_reference_chunk(p.text, p.heading):
            continue
        text = _without_overlap(prev, p.text).strip()
        prev = p.text
        if text:
            yield p, text


def build_windows(passages: Sequence[Passage]) -> list[Window]:
    """Section-aligned windows of about WINDOW_CHARS, without reference lists or chunk overlap."""
    windows: list[Window] = []
    for p, text in _readable(passages):
        if not windows or _opens_window(windows[-1], p.heading, text):
            windows.append(Window(heading=p.heading))
        windows[-1].add(p, text)
    for w in windows:
        w.units = list(dict.fromkeys(u for u in split_units(w.text) if _learnable_words(u) > 0))
    return _sampled([w for w in windows if w.units])


def _notes_wanted(window: Window) -> int:
    return 1 if len(window.text) < 1500 else 2 if len(window.text) < 3000 else 3


def _parse_notes(raw: str) -> list[str]:
    try:
        items = json.loads(raw).get("notes", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    return [x.strip() for x in items if isinstance(x, str) and x.strip()]


def evidence_for(
    note_vec: np.ndarray, units: Sequence[str], unit_vecs: np.ndarray
) -> tuple[str, str]:
    """(the sentence before, the 1-3 sentences that carry the note).

    Embeddings, not word overlap: a note restates the book in other words (a first-person
    narrator is named in a note), so overlap misses its evidence. Whether the card is
    supported is decided on the answer, which must reuse the book's words.
    """
    best = (-1.0, 0, 1)
    for i in range(len(units)):
        for span in (1, 2, 3):
            if i + span > len(units):
                continue
            v = unit_vecs[i : i + span].mean(axis=0)
            cos = float(v @ note_vec) / (float(np.linalg.norm(v)) or 1.0)
            # A longer span must earn its extra sentences.
            if cos > best[0] + 0.02 * (span - 1):
                best = (cos, i, span)
    _, i, span = best
    return (units[i - 1] if i > 0 else ""), " ".join(units[i : i + span])


# "the study" or "the authors" means nothing months later unless the question names them.
_UNNAMED_WORK = re.compile(
    r"\b(?:the|this|that)\s+(?:experiment|study|survey|paper|report|research"
    r"|authors?|researchers?)\b",
    re.I,
)
_NARRATOR = re.compile(r"\bthe\s+(?:narrator|protagonist)\b", re.I)
_ASKS_WHO = re.compile(r"^\W*(?:who|whom|whose)\b", re.I)
# Kinds of book whose cards are about the subject, never a person (#253).
_SUBJECT_GENRES = frozenset({"technical", "academic"})
_WORDS = re.compile(r"[a-z0-9]+")
_TITLE_FILLER = {"the", "a", "an", "of"}


def _names_the_work(question: str, book: str) -> bool:
    title = set(_WORDS.findall(book.lower().replace("_", " "))) - _TITLE_FILLER
    return bool(title) and title <= set(_WORDS.findall(question.lower()))


_CLOSERS = " \"'\u201d\u2019)]"


def _person_asked(question: str, book: Book) -> str | None:
    """Why a technical or research card is about a person rather than its subject, or None."""
    if book.genre not in _SUBJECT_GENRES:
        return None
    if _ASKS_WHO.search(question):
        return "asks who"
    low = question.lower()
    named = next((p for p in book.people if re.search(rf"\b{re.escape(p)}\b", low)), None)
    return f"names a person ({named})" if named else None


def _question_and_answer(raw: str, document_id: str) -> tuple[str, str] | None:
    replies = _parse_llm_response(raw, document_id, expect="object")
    item = next((x for x in replies if isinstance(x, dict)), None)
    if item is None:
        return None
    return card_field(item, "question", "front", "q"), card_field(item, "answer", "back", "a")


def _answer_coverage(answer: str, shown: str, units: Sequence[str]) -> float:
    """The writer saw a span, so the answer may draw on all of it at the one-sentence floor."""
    words = _content(answer)
    span = len(words & _content(shown)) / len(words) if words else 0.0
    return max(best_unit(answer, list(units))[1], span)


def card_from_reply(
    raw: str,
    *,
    book: Book,
    window: Window,
    shown: str,
    evidence: str,
    document_id: str,
) -> tuple[dict[str, str] | None, str]:
    """The card in *raw* if it passes every gate, else (None, why it was dropped)."""
    parsed = _question_and_answer(raw, document_id)
    if parsed is None:
        return None, "unparsed"
    q, a = parsed
    if not q.rstrip(_CLOSERS).endswith("?"):
        return None, "not a question"
    coverage = _answer_coverage(a, shown, window.units)
    if coverage < MIN_ANSWER_COVERAGE:
        return None, f"answer in no sentence ({coverage:.2f})"
    unshown = names_not_in(q, f"{book.title} {window.heading} {book.known_names} {window.text}")
    if unshown:
        return None, f"names someone unshown {unshown}"
    person = _person_asked(q, book)
    if person:
        return None, person
    # "the narrator" is unresolvable alone, resolvable once the question names the book. Only a
    # story has one: elsewhere it is "the author" restated ("the narrator of ThinkPython2").
    named = book.genre == "narrative" and _names_the_work(q, book.title)
    gated = _NARRATOR.sub("Narrator", q) if named else q
    rejected = card_rejection(gated, a, evidence, " ".join(window.units))
    if rejected:
        return None, rejected[1]
    if _UNNAMED_WORK.search(q):
        return None, "unnamed referent"
    return {"question": q, "answer": a, "source_excerpt": evidence}, "ok"


async def _ask(llm: Any, model: str | None, prompt: str, system: str) -> str:
    # background=True keeps the book on this machine in Hybrid mode and yields the runtime to
    # anything the user is waiting on (llm_admission).
    async with get_enrichment_llm_semaphore():
        return await llm.generate(
            prompt,
            system=system,
            model=model,
            stream=False,
            response_format={"type": "json_object"},
            background=True,
        )


async def write_chapter_cards(
    llm: Any,
    model: str | None,
    embed: Embed,
    *,
    book: Book,
    passages: Sequence[Passage],
    document_id: str,
) -> list[ChapterCard]:
    """One card per study note, in reading order, each through the product's card gates."""
    notes_system, card_system = chapter_notes_system(book.genre), chapter_card_system(book.genre)
    cards: list[ChapterCard] = []
    seen: list[set[str]] = []
    for window in build_windows(passages):
        notes = _parse_notes(
            await _ask(
                llm,
                model,
                CHAPTER_NOTES_USER_TMPL.format(
                    book=book.title,
                    heading=window.heading,
                    text=window.text,
                    k=_notes_wanted(window),
                ),
                notes_system,
            )
        )
        if not notes:
            continue
        vecs = await asyncio.to_thread(embed, notes + window.units)
        note_vecs = np.array(vecs[: len(notes)], dtype=np.float32)
        unit_vecs = np.array(vecs[len(notes) :], dtype=np.float32)
        for note, note_vec in zip(notes, note_vecs, strict=True):
            context, evidence = evidence_for(note_vec, window.units, unit_vecs)
            shown = f"{context} {evidence}".strip()
            raw = await _ask(
                llm,
                model,
                CHAPTER_CARD_USER_TMPL.format(
                    book=book.title, heading=window.heading, note=note, evidence=shown
                ),
                card_system,
            )
            card, why = card_from_reply(
                raw,
                book=book,
                window=window,
                shown=shown,
                evidence=evidence,
                document_id=document_id,
            )
            if card is None:
                logger.info("chapter cards: dropped (%s) for note %r", why, note[:80])
                continue
            key = _content(card["question"])
            if key in seen:
                continue
            seen.append(key)
            cards.append(ChapterCard(window=window, **card))
    return cards
