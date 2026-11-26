"""Writing quiz items: code picks the passage, the kind and the level; the model writes JSON.

An item reaches the bank only through every gate in `quiz_parsers` plus the two that need more
than the text: option similarity from the embedder, and the separate factuality judge, which is
never the model that wrote the item (I-35). See docs/quiz.md.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFound
from app.models import ChunkModel, QuizItemModel, QuizOptionModel
from app.repos.document_repo import DocumentRepo
from app.repos.quiz_repo import QuizRepo
from app.services import llm_output_stats
from app.services.flashcard_factuality import (
    FACTUALITY_SUPPORTED,
    FACTUALITY_UNVERIFIABLE,
    check_answer,
    effective_generation_model,
    factuality_model,
    is_self_judging,
)
from app.services.flashcard_parsers import _normalise_for_match
from app.services.flashcard_units import bare_passage
from app.services.llm_admission import awaited
from app.services.llm_errors import describe
from app.services.quiz_parsers import (
    OPTION_COUNT,
    REFUSE_DUPLICATE,
    REFUSE_JUDGED_RIGHT,
    REFUSE_JUDGED_WRONG,
    REFUSE_LEVEL,
    ParsedItem,
    QuizRefusal,
    check_structure,
    parse_item,
)
from app.services.quiz_prompts import QUIZ_ITEM_SYSTEM, level_codes, quiz_item_prompt
from app.types import QuizKind, QuizLevel, QuizScopeType

logger = logging.getLogger(__name__)

# Chunks of one section are joined in reading order up to the ceiling, which a 4B model reads
# whole. The floor is three sentences: enough for one right claim and three that are not it.
_MIN_PASSAGE_CHARS = 300
_MAX_PASSAGE_CHARS = 2400

# One write and up to two rewrites per question, each on fresh material, since the passage itself
# can be the cause (a list, a table of contents).
CALLS_PER_QUESTION = 3

# Two options this close say the same thing. Above the closest distinct pair measured (0.837,
# a wrong option against its right one); no real near-duplicate has yet bracketed it from above.
DUPLICATE_COSINE = 0.95

# How close a wrong option sits to the nearest right one, per level. OFF: on 70 measured wrong
# options the medians were easy 0.645, medium 0.601, hard 0.610, so cosine does not tell the
# levels apart and a band would refuse at random. Re-enable with a measure that separates them.
LEVEL_BANDS: dict[QuizLevel, tuple[float, float]] = {}


# An option is often a phrase that means something only under its stem, so the judge sees the
# stem; against a "which of these" stem one true option reads as a partial answer, so the judge
# is told it judges one option alone.
_JUDGE_NOTE = "(This is one of several options. Judge only whether this option is right.)"


def judge_question(stem: str) -> str:
    return f"{stem}\n{_JUDGE_NOTE}"


class ModelUnavailable(Exception):
    """The writing model could not be reached; the reason is the user-facing sentence."""


@dataclass(frozen=True)
class Window:
    section_id: str | None
    chunk_ids: tuple[str, ...]
    text: str


async def scope_sections(
    session: AsyncSession, document_id: str, scope_type: QuizScopeType, scope_ref: str
) -> list[str] | None:
    """The sections a scope covers, or None for the whole document. A chapter or section that is
    not in the document is an error, never the whole document (I-70)."""
    if scope_type == "document":
        return None
    if scope_type == "section":
        section = await DocumentRepo(session).section(scope_ref)
        if section is None or section.document_id != document_id:
            raise NotFound(f"No section {scope_ref!r} in document {document_id}")
        return [section.id]
    from app.services.chapters import chapters_for_document  # noqa: PLC0415

    doc = await DocumentRepo(session).get_or_404(document_id)
    for chapter in await chapters_for_document(document_id, doc.title or "", session):
        if chapter.id == scope_ref:
            return list(chapter.section_ids)
    raise NotFound(f"No chapter {scope_ref!r} in document {document_id}")


async def scope_chunks(
    session: AsyncSession, document_id: str, section_ids: Sequence[str] | None
) -> list[ChunkModel]:
    from app.services.flashcard import _fetch_document_chunks  # noqa: PLC0415

    if section_ids is None:
        return await _fetch_document_chunks(document_id, session)
    repo = DocumentRepo(session)
    chunks: list[ChunkModel] = []
    for section_id in section_ids:
        chunks.extend(await repo.chunks_in_section(section_id, document_id))
    return chunks


def _continues(run: Sequence[ChunkModel], chunk: ChunkModel) -> bool:
    """Whether *chunk* extends *run*: the next chunk of the same section, within the ceiling."""
    last = run[-1]
    size = sum(len(c.text or "") for c in run) + len(chunk.text or "")
    return (
        chunk.section_id == last.section_id
        and chunk.chunk_index == last.chunk_index + 1
        and size <= _MAX_PASSAGE_CHARS
    )


def _window(run: Sequence[ChunkModel]) -> Window | None:
    text = bare_passage([c.text or "" for c in run])
    if len(text) < _MIN_PASSAGE_CHARS:
        return None
    return Window(run[0].section_id, tuple(c.id for c in run), text)


def windows(chunks: Sequence[ChunkModel]) -> list[Window]:
    """Runs of consecutive chunks within one section, each between the passage bounds."""
    runs: list[list[ChunkModel]] = []
    for chunk in sorted(chunks, key=lambda c: c.chunk_index):
        if runs and _continues(runs[-1], chunk):
            runs[-1].append(chunk)
        else:
            runs.append([chunk])
    return [w for w in (_window(run) for run in runs) if w is not None]


def order_windows(
    candidates: Sequence[Window], used_chunk_ids: set[str], weakness: dict[str, int]
) -> list[Window]:
    """Material no item was written from comes first, weakest sections before the rest; then
    the material the bank already covers, so a well-quizzed chapter still yields questions."""

    def fresh(w: Window) -> bool:
        return not used_chunk_ids.intersection(w.chunk_ids)

    def key(w: Window) -> tuple[bool, int]:
        return (not fresh(w), -weakness.get(w.section_id or "", 0))

    return sorted(candidates, key=key)


def _cosines(texts: list[str]) -> np.ndarray:
    from app.services.embedder import get_embedding_service  # noqa: PLC0415

    vectors = np.array(get_embedding_service().encode(texts), dtype=np.float32)
    return vectors @ vectors.T


def _refuse_duplicates(sims: np.ndarray) -> None:
    n = sims.shape[0]
    for i, j in itertools.combinations(range(n), 2):
        if sims[i, j] >= DUPLICATE_COSINE:
            raise QuizRefusal(
                REFUSE_DUPLICATE,
                f"options {i + 1} and {j + 1} say the same thing ({sims[i, j]:.3f})",
            )


def _refuse_off_level(values: Sequence[float | None], level: QuizLevel) -> None:
    band = LEVEL_BANDS.get(level)
    if not band:
        return
    low, high = band
    for value in (v for v in values if v is not None):
        if not low <= value < high:
            raise QuizRefusal(
                REFUSE_LEVEL, f"a wrong option at {value:.3f} is outside {level} [{low}, {high})"
            )


async def measure_options(item: ParsedItem, level: QuizLevel) -> list[float | None]:
    """Each wrong option's cosine to its nearest right option (None for right options). Refuses
    near-duplicate options and, once bands are measured, an item off its level."""
    sims = await asyncio.to_thread(_cosines, [o.text for o in item.options])
    _refuse_duplicates(sims)
    right = [i for i, o in enumerate(item.options) if o.correct]
    values: list[float | None] = [
        None if option.correct else float(max(sims[i, j] for j in right))
        for i, option in enumerate(item.options)
    ]
    _refuse_off_level(values, level)
    return values


async def judge(item: ParsedItem, passage: str, llm) -> str:  # type: ignore[no-untyped-def]
    """`supported` when the separate judge agrees every right option follows from the passage and
    no wrong one does; `unchecked` when there is no judge, it is the writer, or it could not say.
    Raises on a right option it rejects or a wrong option it accepts."""
    checker = factuality_model()
    if not checker or is_self_judging(checker, effective_generation_model()):
        return "unchecked"
    conclusive = True
    for option in item.options:
        verdict = await check_answer(
            judge_question(item.stem), option.text, passage, checker=checker, llm=llm
        )
        if verdict == FACTUALITY_UNVERIFIABLE:
            conclusive = False
        elif option.correct and verdict != FACTUALITY_SUPPORTED:
            raise QuizRefusal(REFUSE_JUDGED_WRONG, f"judge rejects {option.text[:60]!r}")
        elif not option.correct and verdict == FACTUALITY_SUPPORTED:
            raise QuizRefusal(REFUSE_JUDGED_RIGHT, f"judge accepts {option.text[:60]!r}")
    return "supported" if conclusive else "unchecked"


def _quotes_meet(quote: str, excerpt: str) -> bool:
    return bool(quote and excerpt) and (quote in excerpt or excerpt in quote)


def _linked_card(item: ParsedItem, window: Window, cards) -> str | None:  # type: ignore[no-untyped-def]
    """A card filed in this passage whose quote and a right option's quote contain one another:
    the item tests what the card tests, so a miss can reset the card."""
    quotes = [_normalise_for_match(o.quote or "") for o in item.right]
    for card, _section in cards:
        excerpt = _normalise_for_match(card.source_excerpt or "")
        if card.chunk_id in window.chunk_ids and any(_quotes_meet(q, excerpt) for q in quotes):
            return card.id
    return None


def _item_rows(
    item: ParsedItem,
    *,
    document_id: str,
    window: Window,
    level: QuizLevel,
    kind: QuizKind,
    similarities: Sequence[float | None],
    support: str,
    model: str | None,
    flashcard_id: str | None,
) -> tuple[QuizItemModel, list[QuizOptionModel]]:
    row = QuizItemModel(
        id=str(uuid.uuid4()),
        document_id=document_id,
        section_id=window.section_id,
        kind=kind,
        difficulty=level,
        stem=item.stem,
        source_chunk_ids=list(window.chunk_ids),
        flashcard_id=flashcard_id,
        model=model,
        origin="model",
        support_check=support,
    )
    options = [
        QuizOptionModel(
            id=str(uuid.uuid4()),
            item_id=row.id,
            position=i,
            text=o.text,
            is_correct=o.correct,
            explanation=o.explanation,
            evidence_quote=o.quote if o.correct else None,
            trap=None if o.correct else o.trap,
            key_similarity=similarities[i],
        )
        for i, o in enumerate(item.options)
    ]
    return row, options


async def write_item(
    session: AsyncSession,
    *,
    document_id: str,
    candidates: list[Window],
    level: QuizLevel,
    kind: QuizKind,
    llm,  # type: ignore[no-untyped-def]
    model: str | None,
) -> QuizItemModel | None:
    """One item from the first window that yields a clean one, within the call budget. Each
    window tried is taken off *candidates*, so no passage is asked about twice in a quiz.
    *model* is None unless the user chose one, so the LLM service keeps routing it (and its
    offline reroute); the item records the model that actually wrote it."""
    cards = await QuizRepo(session).grounded_cards(document_id)
    n_right = 1 if kind == "single" else random.choice((2, 3))  # noqa: S311 -- not a secret
    writer = model or effective_generation_model() or None
    for _ in range(CALLS_PER_QUESTION):
        if not candidates:
            break
        window = candidates.pop(0)
        prompt = quiz_item_prompt(window.text, level, OPTION_COUNT[kind], n_right)
        try:
            with awaited():
                raw = await llm.generate(
                    prompt,
                    system=QUIZ_ITEM_SYSTEM,
                    model=model,
                    stream=False,
                    background=True,
                    response_format={"type": "json_object"},
                )
        except Exception as exc:  # noqa: BLE001 -- every failure to reach the model is one case
            raise ModelUnavailable(describe(exc)[1]) from exc
        try:
            item = parse_item(raw)
            check_structure(item, kind, window.text, level_codes(level))
            similarities = await measure_options(item, level)
            support = await judge(item, window.text, llm)
        except QuizRefusal as refusal:
            llm_output_stats.record_quiz_gate(refusal.kind)
            logger.info("quiz: refused a %s %s item: %s", level, kind, refusal)
            continue
        llm_output_stats.record_quiz_gate(None)
        row, options = _item_rows(
            item,
            document_id=document_id,
            window=window,
            level=level,
            kind=kind,
            similarities=similarities,
            support=support,
            model=writer,
            flashcard_id=_linked_card(item, window, cards),
        )
        QuizRepo(session).add_all([row, *options])
        return row
    return None


def _other_answers(card, pool, n: int = 3) -> list:  # type: ignore[no-untyped-def]
    """Up to *n* other cards whose answers differ from *card*'s and from each other."""
    seen = {_normalise_for_match(card.answer)}
    others = []
    for other, _section in pool:
        key = _normalise_for_match(other.answer)
        if other.id != card.id and key not in seen:
            seen.add(key)
            others.append(other)
    return others[:n]


def _card_item_rows(  # type: ignore[no-untyped-def]
    card, section_id: str | None, others, document_id: str
) -> list:
    row = QuizItemModel(
        id=str(uuid.uuid4()),
        document_id=document_id,
        section_id=section_id,
        kind="single",
        # Another card's answer is rejected by anyone who read the passage: easy, whatever level
        # was asked for, and labelled so rather than passed off as that level.
        difficulty="easy",
        stem=card.question,
        source_chunk_ids=list(card.source_chunk_ids or ([card.chunk_id] if card.chunk_id else [])),
        flashcard_id=card.id,
        model=None,
        origin="cards",
        support_check="unchecked",
    )
    right = QuizOptionModel(
        id=str(uuid.uuid4()),
        item_id=row.id,
        position=0,
        text=card.answer,
        is_correct=True,
        explanation="",
        evidence_quote=card.source_excerpt,
    )
    wrong = [
        QuizOptionModel(
            id=str(uuid.uuid4()),
            item_id=row.id,
            position=i,
            text=other.answer,
            is_correct=False,
            explanation=f"This answers another question: {other.question}",
            trap="related_but_different",
        )
        for i, other in enumerate(others, start=1)
    ]
    return [row, right, *wrong]


async def item_from_cards(
    session: AsyncSession,
    *,
    document_id: str,
    section_ids: Sequence[str] | None,
    exclude_cards: set[str],
) -> QuizItemModel | None:
    """A single-answer item with no model: a grounded card's question and answer, and three other
    cards' answers from the same scope as the wrong options. Labelled `origin='cards'`."""
    pool = await QuizRepo(session).grounded_cards(document_id, section_ids)
    random.shuffle(pool)
    chosen = next(((c, s) for c, s in pool if c.id not in exclude_cards), None)
    if chosen is None:
        return None
    card, section_id = chosen
    others = _other_answers(card, pool)
    if len(others) < 3:
        return None
    rows = _card_item_rows(card, section_id, others, document_id)
    QuizRepo(session).add_all(rows)
    return rows[0]
