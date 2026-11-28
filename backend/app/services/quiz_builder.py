"""Writing quiz items: code picks the passage, the sentences a question tests, the kind and the
level; the model phrases the question, then writes wrong answers to it.

A question reaches the bank only through every gate in `quiz_parsers` and the ones that need more
than the text: entailment (a wrong answer the material states is dropped, I-85), a separate
judge that must find the right answer with the material, and a guess without it. See docs/quiz.md.
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

from app.config import get_settings
from app.exceptions import ModelNotDownloaded, NotFound
from app.models import ChunkModel, QuizItemModel, QuizOptionModel
from app.repos.document_repo import DocumentRepo
from app.repos.quiz_repo import QuizRepo
from app.services import llm_output_stats, model_router, quiz_nli
from app.services.flashcard_factuality import (
    effective_generation_model,
    factuality_model,
    is_self_judging,
)
from app.services.flashcard_parsers import _normalise_for_match
from app.services.llm_admission import awaited
from app.services.llm_errors import describe
from app.services.quiz_material import (
    CANDIDATES,
    join_chunks,
    key_candidates,
    pick_keys,
    pick_list,
    unfit_reason,
    untested_items,
)
from app.services.quiz_parsers import (
    DROP_ENTAILED,
    DROP_TRUE_ELSEWHERE,
    OPTION_COUNT,
    REFUSE_DUPLICATE,
    REFUSE_GUESSABLE,
    REFUSE_NOT_ANSWERABLE,
    REFUSE_OFF_KEY,
    REFUSE_TOO_FEW_WRONG,
    RIGHT_COUNTS,
    SPARE_WRONG,
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
from app.services.quiz_prompts import (
    QUIZ_SYSTEM,
    answer_prompt,
    question_prompt,
    slot_codes,
    wrong_prompt,
)
from app.types import QuizKind, QuizLevel, QuizScopeType

logger = logging.getLogger(__name__)

# Chunks of one section are joined in reading order up to the ceiling, which a 4B model reads
# whole. The floor is three sentences: enough for one right claim and three that are not it.
_MIN_PASSAGE_CHARS = 300
_MAX_PASSAGE_CHARS = 2400

# Passages tried per question, each on fresh material, since the passage itself can be the cause.
CALLS_PER_QUESTION = 3

# Two options this close say the same thing. Above the closest distinct pair measured (0.837,
# a wrong option against its right one); no real near-duplicate has yet bracketed it from above.
DUPLICATE_COSINE = 0.95

# Chunks of the whole document searched for a wrong answer stated somewhere else in it.
_ELSEWHERE_CHUNKS = 5

# A test-wise guess: the question shown without its material, this many orders. Right every time
# means the wrong answers give themselves away. Gated above easy; measured at easy.
_GUESSES = 3


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
    text = join_chunks([c.text or "" for c in run])
    if len(text) < _MIN_PASSAGE_CHARS:
        return None
    unfit = unfit_reason(text)
    if unfit:
        llm_output_stats.record_quiz_drop(f"passage_{unfit}")
        return None
    return Window(run[0].section_id, tuple(c.id for c in run), text)


def windows(chunks: Sequence[ChunkModel]) -> list[Window]:
    """Runs of consecutive chunks within one section, each between the passage bounds and none
    a contents page, licence or collection of quotations."""
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


async def measure_options(item: ParsedItem) -> list[float | None]:
    """Each wrong option's cosine to its nearest right option (None for right options). Refuses
    near-duplicate options."""
    sims = await asyncio.to_thread(_cosines, [o.text for o in item.options])
    for i, j in itertools.combinations(range(sims.shape[0]), 2):
        if sims[i, j] >= DUPLICATE_COSINE:
            raise QuizRefusal(
                REFUSE_DUPLICATE,
                f"options {i + 1} and {j + 1} say the same thing ({sims[i, j]:.3f})",
            )
    right = [i for i, o in enumerate(item.options) if o.correct]
    return [
        None if option.correct else float(max(sims[i, j] for j in right))
        for i, option in enumerate(item.options)
    ]


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


@dataclass
class _Writer:
    """One question's calls: the writing model, and the separate judge when there is one."""

    llm: object
    model: str | None
    document_id: str

    async def ask(self, prompt: str, model: str | None = None) -> str:
        try:
            with awaited():
                return await self.llm.generate(  # type: ignore[attr-defined]
                    prompt,
                    system=QUIZ_SYSTEM,
                    model=model or self.model,
                    stream=False,
                    background=True,
                    response_format={"type": "json_object"},
                    temperature=0 if model else None,
                )
        except Exception as exc:  # noqa: BLE001 -- every failure to reach the model is one case
            raise ModelUnavailable(describe(exc)[1]) from exc

    async def elsewhere(self, text: str) -> list[str]:
        """The document's chunks nearest *text*, in three-sentence windows."""
        from app.services.retriever import get_retriever  # noqa: PLC0415

        hits = await asyncio.to_thread(
            get_retriever().vector_search, text, [self.document_id], _ELSEWHERE_CHUNKS
        )
        return [w for hit in hits for w in quiz_nli.windows(hit.text)]


async def _closeness(texts: list[str], summary: str | None) -> list[float] | None:
    """Each text's cosine to the section summary; None without a summary."""
    if not summary or not texts:
        return None
    sims = await asyncio.to_thread(_cosines, [summary, *texts])
    return [float(v) for v in sims[0, 1:]]


async def _take(
    candidates: list[Window], kind: QuizKind, summaries: dict[str, str]
) -> tuple[Window, list[str], str] | None:
    """The first passage that can carry a *kind* question, taken off *candidates*, with its key
    sentences and, for a multi-answer question, the line that introduces its list."""
    n_right = random.choice(RIGHT_COUNTS[kind])  # noqa: S311 -- not a secret
    for i, window in enumerate(candidates):
        if kind == "multi":
            listed = pick_list(window.text, n_right)
            if listed:
                return candidates.pop(i), listed[1], listed[0]
            continue
        options = key_candidates(window.text)[:CANDIDATES]
        closeness = await _closeness(options, summaries.get(window.section_id or ""))
        keys = pick_keys(window.text, 1, set(), closeness)
        if keys:
            return candidates.pop(i), keys, ""
    return None


async def _summaries(session: AsyncSession, document_id: str) -> dict[str, str]:
    from app.repos.summary_repo import SummaryRepo  # noqa: PLC0415

    joined: dict[str, list[str]] = {}
    for row in await SummaryRepo(session).section_summaries(document_id):
        if row.section_id:
            joined.setdefault(row.section_id, []).append(row.content)
    return {k: " ".join(v)[:_MAX_PASSAGE_CHARS] for k, v in joined.items()}


async def _wrong_answers(
    writer: _Writer,
    window: Window,
    stem: str,
    rights: list[str],
    level: QuizLevel,
    need: int,
    untested: list[str],
) -> list[ParsedOption]:
    """*need* wrong answers that pass every check, from one call that asks for spares."""
    slots = slot_codes(level, need + SPARE_WRONG)
    raw = await writer.ask(wrong_prompt(window.text, stem, rights, level, len(slots)))
    passage_windows = quiz_nli.windows(window.text)
    passed: list[ParsedOption] = []
    for option in distinct(parse_wrong(raw, slots), rights):
        reason = drop_reason(option, rights, window.text, stem=stem, untested=untested)
        if (
            reason is None
            and await quiz_nli.entailment(passage_windows, option.text) >= quiz_nli.ENTAILED
        ):
            reason = DROP_ENTAILED
        if reason is None:
            elsewhere = await writer.elsewhere(option.text)
            if not elsewhere:
                # No vectors for the document: the check passes nothing it searched, so count it.
                llm_output_stats.record_quiz_drop("elsewhere_unsearched")
            elif await quiz_nli.entailment(elsewhere, option.text) >= quiz_nli.ENTAILED:
                reason = DROP_TRUE_ELSEWHERE
        if reason:
            llm_output_stats.record_quiz_drop(reason)
            logger.info("quiz: dropped a wrong answer (%s): %s", reason, option.text[:80])
            continue
        passed.append(option)
    if len(passed) < need:
        raise QuizRefusal(REFUSE_TOO_FEW_WRONG, f"{len(passed)} of {need} wrong answers passed")
    # The ones nearest the right answers' length, so no option stands out by its length.
    mean = sum(len(r) for r in rights) / len(rights)
    return sorted(passed, key=lambda o: abs(len(o.text) - mean))[:need]


def _shown(item: ParsedItem, rng: random.Random) -> tuple[list[str], set[int]]:
    order = list(range(len(item.options)))
    rng.shuffle(order)
    return [item.options[i].text for i in order], {
        pos for pos, i in enumerate(order) if item.options[i].correct
    }


async def _judge(writer: _Writer, item: ParsedItem, passage: str) -> str:
    """`supported` when a separate judge, given the material, picks exactly the right answers;
    `unchecked` when there is no judge or it is the writer. Raises when it picks otherwise."""
    checker = factuality_model()
    if not checker or is_self_judging(checker, effective_generation_model()):
        return "unchecked"
    texts, right = _shown(item, random.Random(item.stem))  # noqa: S311 -- an order, not a secret
    raw = await writer.ask(answer_prompt(item.stem, texts, len(right), passage), model=checker)
    picked = parse_letters(raw, len(texts))
    if picked != right:
        raise QuizRefusal(
            REFUSE_NOT_ANSWERABLE,
            f"the judge chose {sorted(picked)}, not {sorted(right)}",
        )
    return "supported"


async def _guessed(writer: _Writer, item: ParsedItem) -> bool:
    """Whether the guessing model finds the right answers without the material, in every order."""
    guesser = get_settings().QUIZ_GUESS_MODEL or model_router.resolve("background").model
    rng = random.Random(len(item.stem))  # noqa: S311 -- an order, not a secret
    for _ in range(_GUESSES):
        texts, right = _shown(item, rng)
        raw = await writer.ask(answer_prompt(item.stem, texts, len(right), None), model=guesser)
        if parse_letters(raw, len(texts)) != right:
            return False
    return True


async def _check_keys(answers: Sequence[str], keys: Sequence[str]) -> None:
    """Each answer says what one key sentence says: entailed by it, a different key each."""
    entailed = [
        {
            j
            for j, key in enumerate(keys)
            if await quiz_nli.entailment([key], a) >= quiz_nli.ENTAILED
        }
        for a in answers
    ]
    if not any(
        all(j in entailed[i] for i, j in enumerate(order))
        for order in itertools.permutations(range(len(keys)))
    ):
        missing = next((a for a, e in zip(answers, entailed, strict=True) if not e), answers[0])
        raise QuizRefusal(REFUSE_OFF_KEY, f"{missing[:60]!r} does not say what a key sentence says")


async def _asked(
    writer: _Writer, window: Window, keys: list[str], lead_in: str, refused: str
) -> tuple[str, list[str]]:
    raw = await writer.ask(question_prompt(window.text, keys, lead_in, refused))
    stem, answers = parse_question(raw, len(keys))
    check_question(stem, answers, keys, window.text)
    await _check_keys(answers, keys)
    return stem, answers


async def _question(
    writer: _Writer, window: Window, keys: list[str], lead_in: str
) -> tuple[str, list[str]]:
    """The question and its answers, asked again once with the reason a first one was refused."""
    try:
        return await _asked(writer, window, keys, lead_in, "")
    except QuizRefusal as refusal:
        llm_output_stats.record_quiz_drop(f"retried_{refusal.kind}")
        return await _asked(writer, window, keys, lead_in, refusal.message)


async def _compose(
    writer: _Writer,
    window: Window,
    keys: list[str],
    lead_in: str,
    level: QuizLevel,
    kind: QuizKind,
) -> tuple[ParsedItem, list[float | None], str]:
    stem, answers = await _question(writer, window, keys, lead_in)
    need = OPTION_COUNT[kind] - len(keys)
    untested = untested_items(window.text, keys) if kind == "multi" else []
    wrong = await _wrong_answers(writer, window, stem, answers, level, need, untested)
    right = [
        ParsedOption(text=a, correct=True, quote=k) for a, k in zip(answers, keys, strict=True)
    ]
    item = ParsedItem(stem=stem, options=right + wrong)
    check_lengths(item, kind)
    similarities = await measure_options(item)
    support = await _judge(writer, item, window.text)
    if await _guessed(writer, item):
        if level != "easy":
            raise QuizRefusal(REFUSE_GUESSABLE, "answered right without the material every time")
        llm_output_stats.record_quiz_drop("easy_guessable")
    return item, similarities, support


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
    """One item from the first passage that yields a clean one, within the attempt budget. Each
    passage tried is taken off *candidates*, so none is asked about twice in a quiz. *model* is
    None unless the user chose one, so the LLM service keeps routing it (and its offline
    reroute); the item records the model that actually wrote it."""
    cards = await QuizRepo(session).grounded_cards(document_id)
    writer = _Writer(llm=llm, model=model, document_id=document_id)
    summaries = await _summaries(session, document_id)
    for _ in range(CALLS_PER_QUESTION):
        taken = await _take(candidates, kind, summaries)
        if taken is None and kind == "multi":
            # No list left in scope: a single-answer question, never one over scattered sentences.
            kind = "single"
            taken = await _take(candidates, kind, summaries)
        if taken is None:
            break
        window, keys, lead_in = taken
        try:
            item, similarities, support = await _compose(writer, window, keys, lead_in, level, kind)
        except ModelNotDownloaded as exc:
            # Without the entailment model no wrong answer can be shown false: no question at all.
            raise ModelUnavailable(str(exc)) from exc
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
            model=model or effective_generation_model() or None,
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
