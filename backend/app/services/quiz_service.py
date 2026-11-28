"""A quiz from request to results: build in the background, score each answer, write misses to
the learner record, and summarise. The router holds only the endpoints."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.exceptions import Conflict, InvalidInput
from app.models import (
    ChunkModel,
    FlashcardModel,
    MisconceptionModel,
    QuizAttemptModel,
    QuizItemModel,
    QuizModel,
    QuizOptionModel,
    QuizQuestionModel,
    ReviewEventModel,
    StudySessionModel,
)
from app.repos.document_repo import DocumentRepo
from app.repos.flashcard_repo import FlashcardRepo
from app.repos.quiz_repo import QuizRepo
from app.schemas.quiz import (
    QuizAnswerRequest,
    QuizAnswerResponse,
    QuizAnswerView,
    QuizCalibration,
    QuizCreateRequest,
    QuizItemCardResponse,
    QuizOption,
    QuizQuestion,
    QuizResponse,
    QuizResults,
    QuizRevisit,
    QuizTrapStat,
)
from app.services import quiz_builder
from app.services.background import fire_and_forget, task_registry
from app.services.flashcard_parsers import card_rejection, excerpt_is_verbatim, grounding_state
from app.services.flashcard_units import bare_passage
from app.services.fsrs_service import get_fsrs_service
from app.services.quiz_scoring import ADAPTIVE_START, next_level, score_answer, shuffled
from app.types import CARD_ARCHIVED, QuizKind, QuizKinds, QuizLevel

logger = logging.getLogger(__name__)

_background_tasks = task_registry(__name__)
# One build at a time: each holds the model for its whole run, and SQLite takes one writer.
_build_lock = asyncio.Lock()

_CONFIDENCES = ("sure", "think", "guess")
# "Which of these is true...?" asks about options a card does not show.
_POINTS_AT_OPTIONS = re.compile(
    r"\b(?:of|among) (?:these|those|the following|the options|the statements)\b", re.IGNORECASE
)


def kind_for(kinds: QuizKinds, position: int) -> QuizKind:
    """Mixed quizzes ask every third question with several right answers."""
    if kinds == "mixed":
        return "multi" if position % 3 == 1 else "single"
    return kinds


async def create(session: AsyncSession, req: QuizCreateRequest) -> QuizResponse:
    doc = await DocumentRepo(session).get_or_404(req.document_id)
    scope_ref = doc.id if req.scope_type == "document" else (req.scope_ref or "")
    # Resolved now, so a scope that names nothing in the document fails the request (I-70).
    await quiz_builder.scope_sections(session, doc.id, req.scope_type, scope_ref)

    study_session = StudySessionModel(id=str(uuid.uuid4()), document_id=doc.id, mode="quiz")
    quiz = QuizModel(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        scope_type=req.scope_type,
        scope_ref=scope_ref,
        difficulty=req.difficulty,
        mode=req.mode,
        question_count=req.question_count,
        question_kinds=req.question_kinds,
        status="building",
        session_id=study_session.id,
    )
    session.add_all([study_session, quiz])
    await session.commit()
    _start_build(quiz.id)
    return await view(session, quiz.id)


def _start_build(quiz_id: str) -> None:
    fire_and_forget(_build(quiz_id), _background_tasks, label="quiz build")


async def _build(quiz_id: str) -> None:
    """Write the questions a quiz still needs: all of them at a fixed level, or the next one when
    it adapts, since that level depends on the answer before it. Opens its own session (I-1)."""
    async with _build_lock, get_session_factory()() as session:
        try:
            await _build_in(session, quiz_id)
        except Exception as exc:
            logger.exception("quiz %s: build failed", quiz_id)
            await session.rollback()
            quiz = await session.get(QuizModel, quiz_id)
            if quiz is not None and quiz.status == "building":
                quiz.status, quiz.error = "error", f"The quiz could not be built: {exc}"
                await session.commit()


@dataclass
class _Build:
    """One build run's working state: the passages left, what the quiz already holds, and
    whether the model is still reachable."""

    session: AsyncSession
    quiz: QuizModel
    sections: list[str] | None
    candidates: list[quiz_builder.Window]
    level: QuizLevel
    in_quiz: set[str] = field(default_factory=set)
    used_cards: set[str] = field(default_factory=set)
    unavailable: str | None = None
    budget: int = 0
    spent: int = 0

    async def write(self, kind: QuizKind) -> QuizItemModel | None:
        """A new item from the model, or None when it refused this round or cannot be reached."""
        from app.services.flashcard_generators import _generation_model  # noqa: PLC0415
        from app.services.llm import get_llm_service  # noqa: PLC0415

        before = len(self.candidates)
        try:
            return await quiz_builder.write_item(
                self.session,
                document_id=self.quiz.document_id,
                candidates=self.candidates,
                level=self.level,
                kind=kind,
                llm=get_llm_service(),
                model=_generation_model(),
            )
        except quiz_builder.ModelUnavailable as exc:
            self.unavailable = str(exc)
            logger.warning("quiz %s: model unavailable, building from cards: %s", self.quiz.id, exc)
            return None
        finally:
            self.spent += before - len(self.candidates)

    def can_write(self) -> bool:
        return self.unavailable is None and bool(self.candidates) and self.spent < self.budget

    async def next_item(self, position: int) -> QuizItemModel | None:
        """An unanswered bank item, else a new one; a refused write moves on to fresh passages
        until material, the model or the call budget runs out."""
        kind = kind_for(self.quiz.question_kinds, position)  # type: ignore[arg-type]
        repo = QuizRepo(self.session)
        bank = await repo.unseen_items(
            self.quiz.document_id, self.sections, self.level, kind, self.in_quiz, 1
        )
        if bank:
            return bank[0]
        while self.can_write():
            item = await self.write(kind)
            if item is not None:
                return item
        if self.unavailable is None:
            return None
        return await quiz_builder.item_from_cards(
            self.session,
            document_id=self.quiz.document_id,
            section_ids=self.sections,
            exclude_cards=self.used_cards,
        )

    async def ask(self, position: int, item: QuizItemModel) -> None:
        await self.session.flush()
        options = (await QuizRepo(self.session).options_by_item([item.id]))[item.id]
        self.session.add(
            QuizQuestionModel(
                quiz_id=self.quiz.id,
                position=position,
                item_id=item.id,
                option_order=shuffled([o.id for o in options]),
            )
        )
        self.in_quiz.add(item.id)
        if item.flashcard_id:
            self.used_cards.add(item.flashcard_id)
        await self.session.commit()


async def _build_in(session: AsyncSession, quiz_id: str) -> None:
    repo = QuizRepo(session)
    quiz = await session.get(QuizModel, quiz_id)
    if quiz is None or quiz.status != "building":
        return
    questions = await repo.questions(quiz_id)
    items = await repo.items({q.item_id for q in questions})
    if quiz.difficulty == "adaptive":
        level = await _adaptive_level(session, quiz_id, questions, items)
        wanted = min(1, quiz.question_count - len(questions))
    else:
        level = quiz.difficulty  # type: ignore[assignment]
        wanted = quiz.question_count - len(questions)
    build = await _start(session, quiz, level, items)
    build.budget = 2 * quiz_builder.CALLS_PER_QUESTION * wanted

    for position in range(len(questions), len(questions) + wanted):
        item = await build.next_item(position)
        await session.refresh(quiz)
        if item is None or quiz.status != "building":
            break
        await build.ask(position, item)

    if quiz.status == "building":
        await _settle(session, quiz, len(questions) + wanted, build.unavailable)


async def _start(
    session: AsyncSession, quiz: QuizModel, level: QuizLevel, items: dict[str, QuizItemModel]
) -> _Build:
    """The scope's passages, unwritten and weakest first, and what the quiz already holds."""
    repo = QuizRepo(session)
    sections = await quiz_builder.scope_sections(
        session,
        quiz.document_id,
        quiz.scope_type,  # type: ignore[arg-type]
        quiz.scope_ref,
    )
    weakness = Counter(await repo.missed_by_section(quiz.document_id))
    weakness.update(await repo.lapses_by_section(quiz.document_id))
    candidates = quiz_builder.order_windows(
        quiz_builder.windows(await quiz_builder.scope_chunks(session, quiz.document_id, sections)),
        await repo.used_chunk_ids(quiz.document_id),
        weakness,
    )
    return _Build(
        session=session,
        quiz=quiz,
        sections=sections,
        candidates=candidates,
        level=level,
        in_quiz=set(items),
        used_cards={i.flashcard_id for i in items.values() if i.flashcard_id},
    )


async def _settle(
    session: AsyncSession, quiz: QuizModel, goal: int, unavailable: str | None
) -> None:
    """Ready, or an error with its reason; a quiz that ran out of material ends where its
    questions do."""
    built = len(await QuizRepo(session).questions(quiz.id))
    quiz.question_count = min(quiz.question_count, built) if built < goal else quiz.question_count
    if built == 0:
        quiz.status = "error"
        quiz.error = unavailable or "No question could be written from this part of the document."
    else:
        quiz.status = "ready"
    await session.commit()


async def _adaptive_level(
    session: AsyncSession,
    quiz_id: str,
    questions: Sequence[QuizQuestionModel],
    items: dict[str, QuizItemModel],
) -> QuizLevel:
    if not questions:
        return ADAPTIVE_START
    attempts = await QuizRepo(session).attempts(quiz_id)
    outcomes = [attempts[q.position].outcome for q in questions if q.position in attempts]
    current = items[questions[-1].item_id].difficulty
    return next_level(current, outcomes)  # type: ignore[arg-type]


def needs_retake(outcome: str, confidence: str | None) -> bool:
    """Missed, partly right, or right on a guess: asked again in the retake round."""
    return outcome != "correct" or confidence == "guess"


def _option_view(option: QuizOptionModel, revealed: bool) -> QuizOption:
    if not revealed:
        return QuizOption(id=option.id, text=option.text)
    return QuizOption(
        id=option.id,
        text=option.text,
        is_correct=option.is_correct,
        explanation=option.explanation,
        quote=option.evidence_quote,
        trap=option.trap,
    )


def _answer_view(attempt: QuizAttemptModel | None) -> QuizAnswerView | None:
    if attempt is None:
        return None
    return QuizAnswerView(
        selected_option_ids=list(attempt.selected_option_ids),
        confidence=attempt.confidence,  # type: ignore[arg-type]
        outcome=attempt.outcome,  # type: ignore[arg-type]
        score=attempt.score,
    )


def _select_count(item: QuizItemModel, options: Sequence[QuizOptionModel]) -> int | None:
    """How many to pick; withheld on a hard multi-answer question."""
    if item.kind == "multi" and item.difficulty == "hard":
        return None
    return sum(1 for o in options if o.is_correct)


def _question_view(
    quiz: QuizModel,
    question: QuizQuestionModel,
    item: QuizItemModel,
    options: Sequence[QuizOptionModel],
    attempt: QuizAttemptModel | None,
) -> QuizQuestion:
    revealed = quiz.status == "complete" or (quiz.mode == "practice" and attempt is not None)
    by_id = {o.id: o for o in options}
    return QuizQuestion(
        position=question.position,
        item_id=item.id,
        kind=item.kind,  # type: ignore[arg-type]
        level=item.difficulty,  # type: ignore[arg-type]
        stem=item.stem,
        select_count=_select_count(item, options),
        origin=item.origin,
        support_check=item.support_check,
        section_id=item.section_id,
        revealed=revealed,
        options=[_option_view(by_id[i], revealed) for i in question.option_order if i in by_id],
        answer=_answer_view(attempt),
    )


async def view(session: AsyncSession, quiz_id: str) -> QuizResponse:
    repo = QuizRepo(session)
    quiz = await repo.get_or_404(quiz_id)
    questions = await repo.questions(quiz_id)
    items = await repo.items([q.item_id for q in questions])
    options = await repo.options_by_item(items.keys())
    attempts = await repo.attempts(quiz_id)
    results = None
    if quiz.status == "complete":
        headings = await repo.section_headings(
            {items[q.item_id].section_id for q in questions if items[q.item_id].section_id}  # type: ignore[misc]
        )
        results = summarise(questions, items, options, attempts, headings)
    return QuizResponse(
        id=quiz.id,
        document_id=quiz.document_id,
        scope_type=quiz.scope_type,  # type: ignore[arg-type]
        scope_ref=quiz.scope_ref,
        difficulty=quiz.difficulty,  # type: ignore[arg-type]
        mode=quiz.mode,  # type: ignore[arg-type]
        question_count=quiz.question_count,
        question_kinds=quiz.question_kinds,  # type: ignore[arg-type]
        status=quiz.status,
        error=quiz.error,
        retake_of=quiz.retake_of,
        created_at=quiz.created_at,
        completed_at=quiz.completed_at,
        questions=[
            _question_view(quiz, q, items[q.item_id], options[q.item_id], attempts.get(q.position))
            for q in questions
        ],
        results=results,
    )


async def _answerable(
    repo: QuizRepo, quiz: QuizModel, req: QuizAnswerRequest
) -> tuple[dict[int, QuizQuestionModel], QuizItemModel, list[QuizOptionModel]]:
    """The question being answered, if it may be: written, unanswered, in an open quiz, and
    answered only with its own options."""
    if quiz.status in ("complete", "error"):
        raise Conflict(f"This quiz is {quiz.status}; it takes no more answers.")
    questions = {q.position: q for q in await repo.questions(quiz.id)}
    question = questions.get(req.position)
    if question is None:
        raise InvalidInput(f"Question {req.position} has not been written yet.")
    if req.position in await repo.attempts(quiz.id):
        raise Conflict(f"Question {req.position} is already answered.")
    item = (await repo.items([question.item_id]))[question.item_id]
    options = (await repo.options_by_item([item.id]))[item.id]
    if not set(req.selected_option_ids) <= {o.id for o in options}:
        raise InvalidInput("An answer names an option this question does not have.")
    return questions, item, options


async def answer(session: AsyncSession, quiz_id: str, req: QuizAnswerRequest) -> QuizAnswerResponse:
    repo = QuizRepo(session)
    quiz = await repo.get_or_404(quiz_id)
    questions, item, options = await _answerable(repo, quiz, req)
    outcome, score = score_answer(
        item.kind,  # type: ignore[arg-type]
        [o.id for o in options if o.is_correct],
        req.selected_option_ids,
    )
    attempt = QuizAttemptModel(
        id=str(uuid.uuid4()),
        quiz_id=quiz_id,
        position=req.position,
        item_id=item.id,
        selected_option_ids=list(dict.fromkeys(req.selected_option_ids)),
        confidence=req.confidence,
        outcome=outcome,
        score=score,
        time_ms=req.time_ms,
    )
    session.add(attempt)
    card_reset = await _record_miss(session, quiz, item, options, req, outcome)
    await session.commit()

    # An adaptive quiz writes its next question only now, at the level this answer set.
    last = req.position == max(questions)
    if quiz.difficulty == "adaptive" and last and len(questions) < quiz.question_count:
        quiz.status = "building"
        await session.commit()
        _start_build(quiz_id)

    return QuizAnswerResponse(
        outcome=outcome,
        score=score,
        retake=needs_retake(outcome, req.confidence),
        card_reset=card_reset,
        question=_question_view(quiz, questions[req.position], item, options, attempt),
    )


async def _live_card(session: AsyncSession, item: QuizItemModel) -> FlashcardModel | None:
    if not item.flashcard_id:
        return None
    card = await FlashcardRepo(session).find(item.flashcard_id)
    return None if card is None or card.fsrs_state == CARD_ARCHIVED else card


def _misconception(
    item: QuizItemModel, card_id: str, options: Sequence[QuizOptionModel], picked: Sequence[str]
) -> MisconceptionModel:
    by_id = {o.id: o for o in options}
    return MisconceptionModel(
        id=str(uuid.uuid4()),
        document_id=item.document_id,
        flashcard_id=card_id,
        user_answer=" / ".join(by_id[i].text for i in picked),
        error_type="misconception",
        correction_note=" / ".join(o.text for o in options if o.is_correct),
    )


async def _record_miss(
    session: AsyncSession,
    quiz: QuizModel,
    item: QuizItemModel,
    options: Sequence[QuizOptionModel],
    req: QuizAnswerRequest,
    outcome: str,
) -> bool:
    """A miss on an item tied to a card resets the card; a right answer never touches it, since
    recognising an answer is not recalling it (I-84). A confident miss opens a misconception."""
    card = None if outcome == "correct" else await _live_card(session, item)
    if card is None:
        return False
    session.add(
        ReviewEventModel(
            id=str(uuid.uuid4()),
            session_id=quiz.session_id or quiz.id,
            flashcard_id=card.id,
            rating="again",
            is_correct=False,
        )
    )
    if req.confidence == "sure":
        session.add(_misconception(item, card.id, options, req.selected_option_ids))
    await get_fsrs_service().schedule(card.id, "again", session)
    return True


def _calibration(answered: Sequence[QuizAttemptModel]) -> list[QuizCalibration]:
    return [
        QuizCalibration(
            confidence=c,  # type: ignore[arg-type]
            answered=sum(1 for a in answered if a.confidence == c),
            correct=sum(1 for a in answered if a.confidence == c and a.outcome == "correct"),
        )
        for c in _CONFIDENCES
    ]


def _score_pct(answered: Sequence[QuizAttemptModel]) -> float | None:
    if not answered:
        return None
    return round(100 * sum(a.score for a in answered) / len(answered), 1)


def summarise(
    questions: Sequence[QuizQuestionModel],
    items: dict[str, QuizItemModel],
    options: dict[str, list[QuizOptionModel]],
    attempts: dict[int, QuizAttemptModel],
    headings: dict[str, str],
) -> QuizResults:
    answered = [attempts[q.position] for q in questions if q.position in attempts]
    return QuizResults(
        answered=len(answered),
        total=len(questions),
        correct=sum(1 for a in answered if a.outcome == "correct"),
        score_pct=_score_pct(answered),
        calibration=_calibration(answered),
        traps=_traps(answered, options),
        revisit=_revisit(answered, items, headings),
        retake_count=sum(1 for a in answered if needs_retake(a.outcome, a.confidence)),
    )


def _revisit(
    answered: Sequence[QuizAttemptModel], items: dict[str, QuizItemModel], headings: dict[str, str]
) -> list[QuizRevisit]:
    """Sections with an answer that was not fully right, most missed first."""
    missed = Counter(
        section
        for a in answered
        if a.outcome != "correct" and (section := items[a.item_id].section_id)
    )
    return [
        QuizRevisit(section_id=s, heading=headings.get(s, ""), missed=n)
        for s, n in missed.most_common()
    ]


def _traps(
    answered: Sequence[QuizAttemptModel], options: dict[str, list[QuizOptionModel]]
) -> list[QuizTrapStat]:
    """Per trap, how often a wrong option of that kind was shown and how often it was picked."""
    shown: Counter[str] = Counter()
    picked: Counter[str] = Counter()
    for attempt in answered:
        selected = set(attempt.selected_option_ids)
        for option in options[attempt.item_id]:
            if option.trap:
                shown[option.trap] += 1
                picked[option.trap] += option.id in selected
    return [QuizTrapStat(trap=t, shown=n, picked=picked[t]) for t, n in shown.most_common()]


async def finish(session: AsyncSession, quiz_id: str) -> QuizResponse:
    repo = QuizRepo(session)
    quiz = await repo.get_or_404(quiz_id)
    if quiz.status != "complete":
        attempts = await repo.attempts(quiz_id)
        now = datetime.now(UTC)
        quiz.status, quiz.completed_at = "complete", now
        study = await session.get(StudySessionModel, quiz.session_id) if quiz.session_id else None
        if study is not None:
            correct = sum(1 for a in attempts.values() if a.outcome == "correct")
            study.ended_at = now
            study.cards_reviewed = len(attempts)
            study.cards_correct = correct
            study.accuracy_pct = round(100 * correct / len(attempts), 1) if attempts else None
        await session.commit()
    return await view(session, quiz_id)


async def retake(session: AsyncSession, quiz_id: str) -> QuizResponse:
    """A new quiz of the questions missed, partly right or guessed, in a fresh order."""
    repo = QuizRepo(session)
    source = await repo.get_or_404(quiz_id)
    attempts = await repo.attempts(quiz_id)
    again = [
        a.item_id for _, a in sorted(attempts.items()) if needs_retake(a.outcome, a.confidence)
    ]
    if not again:
        raise InvalidInput("Nothing to retake: every answer was right and none was a guess.")
    options = await repo.options_by_item(again)
    study_session = StudySessionModel(
        id=str(uuid.uuid4()), document_id=source.document_id, mode="quiz"
    )
    quiz = QuizModel(
        id=str(uuid.uuid4()),
        document_id=source.document_id,
        scope_type=source.scope_type,
        scope_ref=source.scope_ref,
        difficulty=source.difficulty,
        mode=source.mode,
        question_count=len(again),
        question_kinds=source.question_kinds,
        status="ready",
        session_id=study_session.id,
        retake_of=source.id,
    )
    session.add_all([study_session, quiz])
    session.add_all(
        QuizQuestionModel(
            quiz_id=quiz.id,
            position=i,
            item_id=item_id,
            option_order=shuffled([o.id for o in options[item_id]]),
        )
        for i, item_id in enumerate(again)
    )
    await session.commit()
    return await view(session, quiz.id)


async def _card_source(
    repo: QuizRepo, item: QuizItemModel
) -> tuple[QuizOptionModel, list[ChunkModel], str]:
    """The right option and the passage a card from *item* would quote, if it can make one."""
    if item.kind != "single":
        raise InvalidInput("A card holds one answer, and this question has several.")
    if item.flashcard_id:
        raise Conflict("This question already has a card.", flashcard_id=item.flashcard_id)
    if _POINTS_AT_OPTIONS.search(item.stem):
        raise InvalidInput("This question needs its options in view, so it cannot be a card.")
    right = next(o for o in (await repo.options_by_item([item.id]))[item.id] if o.is_correct)
    chunks = await repo.chunks(item.source_chunk_ids)
    passage = bare_passage([c.text or "" for c in chunks])
    rejection = card_rejection(item.stem, right.text, right.evidence_quote or "", passage)
    if rejection:
        raise InvalidInput(f"This question does not make a good card: {rejection[1]}.")
    return right, chunks, passage


async def item_to_card(session: AsyncSession, item_id: str) -> QuizItemCardResponse:
    """A grounded card from a single-answer item: its stem, its right option and that option's
    quote, held to the same gate as a generated card."""
    repo = QuizRepo(session)
    item = await repo.item_or_404(item_id)
    right, chunks, passage = await _card_source(repo, item)
    quote = right.evidence_quote or ""
    home = next((c for c in chunks if excerpt_is_verbatim(quote, c.text or "")), None)
    card = FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=item.document_id,
        chunk_id=(home or chunks[0]).id if chunks else None,
        question=item.stem,
        answer=right.text,
        source_excerpt=quote,
        grounding=grounding_state(quote, passage),
        source_chunk_ids=list(item.source_chunk_ids),
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        due_date=datetime.now(UTC),
        reps=0,
        lapses=0,
    )
    session.add(card)
    await session.flush()
    item.flashcard_id = card.id
    await FlashcardRepo(session).sync_fts(card)
    await session.commit()
    return QuizItemCardResponse(flashcard_id=card.id, question=card.question, answer=card.answer)
