"""Study session endpoints.

Routes:
  GET  /study/due                    — flashcards due for review (due_date <= now)
  POST /study/sessions/start         — create a new study session
  POST /study/sessions/{id}/end      — close a session and return summary
  GET  /study/gaps/{document_id}     — weak flashcard areas grouped by section
  POST /study/teachback              — LLM evaluation of user's teach-back explanation (sync)
  POST /study/teachback/async        — submit teach-back for background evaluation
  GET  /study/teachback/results      — batch-poll teach-back results by IDs
  GET  /study/stats/{document_id}    — progress stats: mastery, retention, streak
  GET  /study/history                — daily study activity for the last N days
  GET  /study/struggling             — cards with >= N 'again' ratings in last M days
"""

import asyncio
import json
import logging
import math
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db, get_session_factory
from app.models import (
    ChunkModel,
    CollectionMemberModel,
    CollectionModel,
    DocumentModel,
    FlashcardModel,
    MisconceptionModel,
    NoteModel,
    NoteTagIndexModel,
    ReviewEventModel,
    SectionModel,
    StudyEventModel,
    StudySessionModel,
    TeachbackResultModel,
)
from app.repos.flashcard_repo import FlashcardRepo
from app.repos.study_repo import StudyRepo, get_study_repo
from app.routers.flashcards import FlashcardResponse, _to_response
from app.schemas.study import (
    AppendSessionCardsRequest,
    AppendSessionCardsResponse,
    AssemblePreview,
    AssembleRequest,
    AssembleResponse,
    CalibrationStatsResponse,
    CalibrationWeekItem,
    CardStabilityItem,
    CollectionSource,
    CollectionSubCollection,
    CollectionTopic,
    DailyHistoryItem,
    DecayDebtItem,
    DecayDebtResponse,
    DocumentTopicsResponse,
    DueCountResponse,
    GapResult,
    MisconceptionStatsResponse,
    RubricCompletenessResponse,
    RubricDimensionResponse,
    SectionHeatmapItem,
    SectionHeatmapResponse,
    SectionStabilityItem,
    SessionCardDetail,
    SessionCardResponse,
    SessionListItem,
    SessionListResponse,
    SessionPlanItem,
    SessionPlanResponse,
    SessionRemainingResponse,
    SessionResponse,
    SessionReviewRequest,
    SessionReviewResponse,
    SessionStartResponse,
    SessionSummary,
    StartConceptItemResponse,
    StartConceptsAPIResponse,
    StartSessionRequest,
    StrugglingCardItem,
    StudyCollectionDashboardResponse,
    StudyPathAPIResponse,
    StudyPathItemResponse,
    StudyStatsResponse,
    TeachbackRequest,
    TeachbackResponse,
    TeachbackResultItem,
    TeachbackResultsBatchResponse,
    TeachbackRubricResponse,
    TeachbackSubmitResponse,
    TopicItem,
)
from app.services import study_assembler
from app.services.background import fire_and_forget, task_registry
from app.services.flashcard_search import _sync_flashcard_fts
from app.services.fsrs_service import get_fsrs_service
from app.services.llm import get_llm_service
from app.services.llm_json import parse_llm_json_object
from app.services.mastery_service import get_mastery_service
from app.services.misconceptions import (
    PASSING_TEACHBACK_SCORE,
    resolve_for_flashcard,
)
from app.services.misconceptions import (
    get_stats as get_misconception_stats,
)
from app.services.study_path_service import StudyPathService
from app.services.study_session_service import (
    build_session_plan as _build_session_plan,
)
from app.services.study_session_service import (
    compute_gaps as _compute_gaps,
)
from app.services.study_session_service import (
    compute_section_heatmap as _compute_section_heatmap,
)
from app.services.topic_service import get_topic_service

logger = logging.getLogger(__name__)

# Back-compat re-exports for tests and feynman.py that import these here.
__all__ = [
    "SectionHeatmapItem",
    "SessionPlanItem",
    "_build_session_plan",
    "_compute_gaps",
    "_compute_section_heatmap",
    "router",
]

router = APIRouter(prefix="/study", tags=["study"])

# Gap-detection thresholds live in repos/study_repo.py.

# Background task set -- strong refs prevent GC (same pattern as feynman_service.py)
_background_tasks = task_registry(__name__)


def _fire_and_forget(coro) -> None:  # type: ignore[no-untyped-def]
    fire_and_forget(coro, _background_tasks, label="study background task")



# Serialize background teachback evaluations to avoid SQLite "database is locked"
# when multiple concurrent tasks try to write (invariant I-1).
_teachback_eval_sem = asyncio.Semaphore(1)


# Teach-back grades what the learner wrote against the material, and it had two
# defects the flashcard path already paid for.
#
# It never saw the source. The evaluator was given the card's answer and the
# student's explanation, so it graded against a reference that may itself be
# ungrounded -- measured on a real library, 26% of cards quoting anything quoted
# text absent from their document. `source_chunk_ids` makes the passage
# recoverable, so the passage is what the explanation is graded against and the
# card's answer is context rather than truth.
#
# And the axis was undefined: "score 0 to 100" with nothing anchoring it. An
# undefined axis is answered with whatever is agreeable -- that is what returned
# `atomicity 1.0000` on a set that was two thirds multi-point answers. The bands
# below say what each score means, and the evaluator has to quote the passage for
# its accuracy claim, which is the one thing it cannot produce from memory.
#
# Two more, found on a real run (2026-09-09):
#
# It never saw the question. The template interpolated passage, card answer and
# explanation, so `completeness` -- "how much of what the passage covers the
# student said" -- was measured against the whole passage rather than against
# what was asked. On a card asking why personal context matters, the stored
# missing_points were "creating a personalized workflow definition (agents.md)"
# and "demonstrating the iterative checking process with /skeptical": two topics
# the question did not raise. Completeness 10/100. The question is in the prompt
# now and both `completeness` and `missing_points` are scoped to it.
#
# And `score` was a fourth integer asked for alongside the three dimensions,
# with nothing relating them. Real rows: score 0 against completeness 50, and
# score 60 against accuracy 40. The learner reads the headline and the breakdown
# as one judgment; they were two. The model is no longer asked for a score --
# `_score_from_dimensions` computes it, so the breakdown always explains it.
_TEACHBACK_SYSTEM = (
    "You grade a student's explanation against a source passage. "
    "Judge only against the passage: not against what you know about the subject. "
    "Output a JSON object with no preamble or markdown."
)

_TEACHBACK_USER_TMPL = (
    "PASSAGE (the source material):\n{source}\n\n"
    "The QUESTION the student was asked: {question}\n\n"
    "The card's answer, for reference: {answer}\n\n"
    "The student explained:\n{explanation}\n\n"
    "Judge the explanation against the passage, as an answer to that question.\n\n"
    "correct_points: what the student got right, as short phrases.\n"
    "missing_points: what the passage says IN ANSWER TO THE QUESTION and the "
    "explanation does not. Empty if the explanation covers it. Never list "
    "material the question did not ask about.\n"
    "misconceptions: claims that contradict the passage. Empty if there are none "
    "-- do not invent one to seem thorough.\n"
    "evidence: one sentence copied word for word from the PASSAGE that supports "
    "your accuracy score. Copy it exactly; do not paraphrase.\n"
    "accuracy -- how much of what the student said the passage supports:\n"
    "  90-100  every claim is in the passage\n"
    "  70-89   the substance is in the passage, with one unsupported aside\n"
    "  40-69   partly supported, with a claim the passage does not back\n"
    "  1-39    mostly unsupported, or reverses what the passage says\n"
    "  0       unrelated to the passage, empty, or unintelligible\n"
    "completeness -- how much of the passage's answer TO THAT QUESTION the "
    "student gave. Material the passage covers that the question did not ask "
    "about is not missing:\n"
    "  90-100  nothing the question asked for is left out\n"
    "  70-89   the main point is there, a supporting detail is not\n"
    "  40-69   about half of what the question asked for\n"
    "  1-39    a fragment of it\n"
    "  0       nothing the question asked for\n"
    "clarity: 0-100, how clearly it was put.\n\n"
    'Output JSON: {{"correct_points": [str], '
    '"missing_points": [str], "misconceptions": [str], "evidence": str, '
    '"accuracy": int, "completeness": int, "clarity": int}}'
)

# The three dimensions above are integers, and deliberately not a fourth free-text
# field. A `clarity_comment` string asked for after them was measured emitting
# malformed JSON on the local model in 3 of 6 failures -- the model dropped the
# opening quote and wrote `"clarity_comment": The explanation is clear...`, which
# fails the whole parse and costs the learner their score. Numbers after prose are
# safe; prose after numbers is not. Do not add a free-text field to this call
# without re-running the parse-rate arm of the measurement -- which is also why
# the three integers stay last in the output shape even though the score is now
# derived from two of them.

# A passage for a *prompt*, not for a substring search. `passage_for_card` falls
# back to the whole document when a card predates `source_chunk_ids`, which is
# right for the grounding audit -- it searches the text -- and catastrophic here:
# a 700,000-character book in the evaluation prompt overruns the context window,
# and the model returns something unparseable. Measured: 2 of 4 teach-back calls
# came back HTTP 503 "unreadable evaluation" until this was bounded.
_TEACHBACK_PASSAGE_CHARS = 6000


# A discontinuous passage presented as a continuous one invites the evaluator to
# read across the join. The generation prompt already marks its seams this way;
# `passage_for_card` does not, because the grounding audit substring-searches its
# output and a marker would break a quote spanning a seam. So the marker is added
# here, where the text is only ever read by a model.
_PASSAGE_SEAM = "\n\n[...]\n\n"


async def _card_scope_passage(card: FlashcardModel, session: AsyncSession) -> str:
    """The recorded chunks narrowed to the ones this card was written from.

    `source_chunk_ids` is the whole *batch's* passage: every card produced by one
    generation call records the same list (`flashcard_generators.py`), and over
    `_CHUNK_CHAR_LIMIT` that list is windows sampled from across the document.
    Measured on this library on 2026-09-09, over the 171 cards whose quote can be
    located: a recorded passage is 6.5 chunks and the card's own run of them is
    3.7, so **38% of the text called "the passage" is material the card was not
    written from**, and 41% of those passages jump across the document.
    Completeness is scored against that text, so a learner who answered the
    question fully was marked down for not also explaining two unrelated topics.

    (81% by a stricter reading that counts only the single chunk holding the
    quote as the card's. That is not the number this removes: the chunks either
    side of a quote are its context, and a run keeps them.)

    The card's own quote locates it, and the generation gate has already checked
    that quote is verbatim: 171 of the 173 cards carrying recorded chunks name a
    sentence that is really inside one contiguous run of them. Runs rather than
    single chunks, because a quote spanning a seam is real.

    Returns "" only when the recorded chunks are already one continuous run, in
    which case the caller's fallback produces the same text. When the quote
    locates nothing, the whole recorded passage is returned with its seams
    marked: grading against too much beats grading against nothing, but the
    evaluator may not read across a gap it cannot see.
    """
    from app.services.flashcard_grounding import (  # noqa: PLC0415
        contiguous_runs,
        run_containing,
    )

    ids = [c for c in (card.source_chunk_ids or []) if isinstance(c, str)]
    # A card with no quote cannot be narrowed, but its recorded chunks are just
    # as discontinuous, so it still needs its seams marked.
    excerpt = (card.source_excerpt or "").strip()
    if len(ids) < 2:
        return ""
    rows = await session.execute(
        select(ChunkModel).where(ChunkModel.id.in_(ids))
    )
    runs = contiguous_runs(list(rows.scalars().all()))
    if len(runs) < 2:
        return ""
    matched = run_containing(runs, excerpt)
    if matched is not None:
        return _run_text(matched)
    # The quote is in none of the runs, or in more than one, so there is no
    # narrowing to do. Keep everything -- grading against too much beats grading
    # against nothing -- but stop presenting four places in a document as one
    # continuous passage.
    return _PASSAGE_SEAM.join(_run_text(run) for run in runs)


def _run_text(run: Sequence[ChunkModel]) -> str:
    return "\n\n".join(c.text for c in run if c.text)


async def _source_passage(card: FlashcardModel, session: AsyncSession) -> str:
    """The passage this card was written from, bounded for use in a prompt.

    A card with recorded chunks gets exactly those. A card without gets a window
    of its document centred on the quote it claims, which is the best available
    guess at where it came from -- and far better than grading the learner
    against the card's own answer, which is what this replaced.

    Never raises: a teach-back that cannot find its source still scores, it just
    scores against less.
    """
    from app.services.flashcard_grounding import passage_for_card  # noqa: PLC0415
    from app.services.flashcard_parsers import _normalise_for_match  # noqa: PLC0415

    try:
        text = await _card_scope_passage(card, session) or await passage_for_card(
            card, session
        )
    except Exception:  # noqa: BLE001
        logger.warning("teachback: could not rebuild the passage for card %s", card.id)
        return ""
    if len(text) <= _TEACHBACK_PASSAGE_CHARS:
        return text

    # Centre the window on the card's own quote rather than taking the opening
    # of the document, which is unlikely to be where the card came from.
    excerpt = _normalise_for_match(card.source_excerpt or "")[:80]
    haystack = _normalise_for_match(text)
    found = haystack.find(excerpt) if excerpt else -1
    if found < 0:
        return text[:_TEACHBACK_PASSAGE_CHARS]
    # Offsets shift under normalisation, so scale back into the raw string.
    middle = int(found * len(text) / max(len(haystack), 1))
    half = _TEACHBACK_PASSAGE_CHARS // 2
    return text[max(0, middle - half) : middle + half]


def _verified_evidence(parsed: dict, source: str) -> str:
    """The evaluator's quote, kept only when it is really in the passage.

    It is asked to copy a sentence rather than paraphrase, which is the one part
    of its answer it cannot produce from memory. An unverifiable quote is dropped
    rather than shown: presenting it would be the product vouching for a sentence
    it could not find.
    """
    from app.services.flashcard_parsers import excerpt_is_verbatim  # noqa: PLC0415

    evidence = str(parsed.get("evidence") or "").strip()
    if not evidence or not source:
        return ""
    return evidence if excerpt_is_verbatim(evidence, source) else ""


# What the headline score is made of. Accuracy leads because a teach-back that
# states something the passage does not support is worse than one that stops
# short: the learner is being asked to say what is true, not to say everything.
#
# Clarity carries no weight. It is the one dimension with no passage behind it --
# nothing grounds it, and it scored 6/100 on an explanation whose own
# correct_points named two right concepts. A number the evaluator produces out of
# taste may describe an answer; it may not grade one. It is still shown.
_SCORE_WEIGHTS: dict[str, float] = {"accuracy": 0.6, "completeness": 0.4}

# Below this, a dimension is not a partial answer but a missing one, and no
# weighted mean may carry it to a pass. The two cases that bracket the floor:
# accuracy 100 with completeness 20 -- everything the student said was right and
# it was a fifth of the answer, which must not pass -- and accuracy 70 with
# completeness 50, the substance with a supporting detail missing, which must.
# The mean alone passes both (68 and 62); the floor is what separates them.
_DIMENSION_FLOOR = 40


def _score_from_dimensions(parsed: dict) -> int | None:
    """The headline score, computed from the dimensions the learner is shown.

    It used to be a fourth integer asked for beside them, and nothing related the
    four. Across the 90 stored verdicts carrying a breakdown, 24 of them (27%)
    have a headline **outside the range their own two dimensions bracket** --
    `score` 85 under 95/90, `score` 75 over 60/50 -- which no weighting of the
    two can produce, so the disagreement is not a matter of the weights chosen
    here. Five of those told the learner "Good explanation!" and scheduled the
    card as known while both dimensions failed. The panel prints the breakdown
    directly beneath the headline, so a reader takes one for the explanation of
    the other; they were two opinions.

    None when a dimension is missing or out of range, which fails the parse and
    costs the reply a retry. A score assembled from numbers nobody produced is a
    measurement that did not happen; the same rule `_rubric_from_evaluation`
    follows for the breakdown.
    """
    scores: dict[str, int] = {}
    for key in _SCORE_WEIGHTS:
        value = parsed.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        if not 0 <= value <= 100:
            return None
        scores[key] = value
    weighted = round(sum(scores[k] * w for k, w in _SCORE_WEIGHTS.items()))
    if min(scores.values()) < _DIMENSION_FLOOR:
        return min(weighted, PASSING_TEACHBACK_SCORE - 1)
    return weighted


def _rubric_from_evaluation(parsed: dict, evidence: str) -> dict | None:
    """The three-dimension rubric, read off the one grounded judgment above.

    Two of these three produce the headline score (`_score_from_dimensions`);
    clarity is shown and does not.

    It used to be a second LLM call, and that call was handed the card's answer
    as its source material -- so the rubric the learner reads graded them
    against the card rather than against the document, which is the defect the
    evaluation prompt was rewritten to fix. Asking one call for both costs one
    round trip where a teach-back used to cost two, and leaves the learner one
    judgment to disagree with instead of two that can contradict each other.

    Returns None rather than a filled-in default when a dimension is missing or
    out of range: a rubric assembled from numbers nobody produced is a
    measurement that did not happen. The null case already renders
    (InlineTeachbackFeedback.tsx) and says the rubric is unavailable.
    """
    scores: dict[str, int] = {}
    for key in ("accuracy", "completeness", "clarity"):
        value = parsed.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        if not 0 <= value <= 100:
            return None
        scores[key] = value
    missed = parsed.get("missing_points")
    return {
        # The verified quote, never the raw one: an unverifiable sentence is
        # dropped by _verified_evidence rather than shown as the reason for a score.
        "accuracy": {"score": scores["accuracy"], "evidence": evidence},
        "completeness": {
            "score": scores["completeness"],
            "missed_points": missed if isinstance(missed, list) else [],
        },
        # No comment: the evaluator is asked for a number here and nothing else,
        # for the reason recorded next to the prompt. An empty string says "no
        # remark", which is what happened -- never a sentence assembled here.
        "clarity": {"score": scores["clarity"], "evidence": ""},
    }


_CORRECTION_SYSTEM = (
    "You are a flashcard generator creating a targeted correction card. "
    "Output a JSON object with no markdown."
)

# This asked for a `source_excerpt` while supplying no source, so every quote it
# produced was necessarily invented -- the same defect as `fill_gaps`, which wrote
# cards from a section heading. The passage is supplied now and the card goes
# through the same grounding gate as every other card.
_CORRECTION_USER_TMPL = (
    "PASSAGE (the source material):\n{source}\n\n"
    "The student has this misconception: {misconception}\n"
    'The card\'s answer to "{question}" is: {answer}\n\n'
    "Write one correction flashcard addressing that misconception, using only "
    "what the passage says. The answer is a single sentence. "
    "source_excerpt is copied word for word from the PASSAGE -- copy it exactly, "
    "do not paraphrase, and do not write one if the passage does not support the "
    "card.\n"
    'Output JSON: {{"question": str, "answer": str, "source_excerpt": str}}'
)

_RATING_INT_MAP: dict[int, str] = {1: "again", 2: "hard", 3: "good", 4: "easy"}


@router.get("/due-count", response_model=DueCountResponse)
async def get_due_count(
    collection_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    document_ids: list[str] | None = Query(default=None),
    note_ids: list[str] | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> DueCountResponse:
    """Return the count of flashcards whose due_date is today or in the past."""
    now = datetime.now(UTC)
    stmt = select(func.count()).select_from(FlashcardModel).where(FlashcardModel.due_date <= now)

    # Apply filters
    if document_ids:
        stmt = stmt.where(FlashcardModel.document_id.in_(document_ids))
    if note_ids:
        stmt = stmt.where(FlashcardModel.note_id.in_(note_ids))

    # Combined collection logic -- inline queries resolve the collection hierarchy and
    # tag membership before the main count. The filter set is determined at request
    # time so the queries cannot be pre-built in a repo method.
    if collection_id and not (document_ids or note_ids):
        # Resolve all doc/note IDs in hierarchy
        c_doc_ids, c_note_ids = await _resolve_collection_members(collection_id, session)

        if tag:
            # Topic filter within collection
            from app.routers.documents import _safe_tags

            all_c_docs = (
                await session.execute(
                    select(DocumentModel.id, DocumentModel.tags).where(
                        DocumentModel.id.in_(c_doc_ids)
                    )
                )
            ).all()
            matching_doc_ids = [did for did, dtags in all_c_docs if tag in _safe_tags(dtags)]

            tag_notes_stmt = (
                select(NoteTagIndexModel.note_id)
                .where(NoteTagIndexModel.note_id.in_(c_note_ids))
                .where(NoteTagIndexModel.tag_full == tag)
            )
            matching_note_ids = (await session.execute(tag_notes_stmt)).scalars().all()

            stmt = stmt.where(
                or_(
                    FlashcardModel.document_id.in_(matching_doc_ids) if matching_doc_ids else False,
                    FlashcardModel.note_id.in_(matching_note_ids) if matching_note_ids else False,
                )
            )
        else:
            # All in collection
            stmt = stmt.where(
                or_(
                    FlashcardModel.document_id.in_(c_doc_ids) if c_doc_ids else False,
                    FlashcardModel.note_id.in_(c_note_ids) if c_note_ids else False,
                )
            )
    elif tag:
        # Global tag filter (no collection scope)
        all_docs_with_tag = (
            await session.execute(select(DocumentModel.id, DocumentModel.tags))
        ).all()
        from app.routers.documents import _safe_tags

        matching_doc_ids = [did for did, dtags in all_docs_with_tag if tag in _safe_tags(dtags)]

        stmt = (
            stmt.join(NoteModel, FlashcardModel.note_id == NoteModel.id, isouter=True)
            .join(NoteTagIndexModel, NoteModel.id == NoteTagIndexModel.note_id, isouter=True)
            .where(
                or_(
                    FlashcardModel.document_id.in_(matching_doc_ids) if matching_doc_ids else False,
                    NoteTagIndexModel.tag_full == tag,
                )
            )
        )

    result = await session.execute(stmt)
    count = result.scalar_one()
    logger.debug("due-count: %d cards due", count)
    return DueCountResponse(due_today=count)


@router.get("/due", response_model=list[FlashcardResponse])
async def get_due_cards(
    document_id: str | None = None,
    collection_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    document_ids: list[str] | None = Query(default=None),
    note_ids: list[str] | None = Query(default=None),
    section_id: str | None = Query(default=None),
    limit: int = 20,
    session: AsyncSession = Depends(get_db),
) -> list[FlashcardResponse]:
    """Return flashcards whose due_date is now or in the past."""
    now = datetime.now(UTC)
    stmt = select(FlashcardModel).where(FlashcardModel.due_date <= now)

    # section scope: cards whose source chunk belongs to this section (study a coherent unit)
    if section_id:
        stmt = stmt.where(
            FlashcardModel.chunk_id.in_(
                select(ChunkModel.id).where(ChunkModel.section_id == section_id)
            )
        )

    # Apply filters
    used_document_ids = document_ids or ([document_id] if document_id else [])
    if used_document_ids:
        stmt = stmt.where(FlashcardModel.document_id.in_(used_document_ids))
    if note_ids:
        stmt = stmt.where(FlashcardModel.note_id.in_(note_ids))

    # Collection/tag filter branches -- inline for the same reason as get_due_count.
    if collection_id and not (used_document_ids or note_ids):
        # Resolve all doc/note IDs in hierarchy
        c_doc_ids, c_note_ids = await _resolve_collection_members(collection_id, session)

        if tag:
            from app.routers.documents import _safe_tags

            all_c_docs = (
                await session.execute(
                    select(DocumentModel.id, DocumentModel.tags).where(
                        DocumentModel.id.in_(c_doc_ids)
                    )
                )
            ).all()
            matching_doc_ids = [did for did, dtags in all_c_docs if tag in _safe_tags(dtags)]

            tag_notes_stmt = (
                select(NoteTagIndexModel.note_id)
                .where(NoteTagIndexModel.note_id.in_(c_note_ids))
                .where(NoteTagIndexModel.tag_full == tag)
            )
            matching_note_ids = (await session.execute(tag_notes_stmt)).scalars().all()

            stmt = stmt.where(
                or_(
                    FlashcardModel.document_id.in_(matching_doc_ids) if matching_doc_ids else False,
                    FlashcardModel.note_id.in_(matching_note_ids) if matching_note_ids else False,
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    FlashcardModel.document_id.in_(c_doc_ids) if c_doc_ids else False,
                    FlashcardModel.note_id.in_(c_note_ids) if c_note_ids else False,
                )
            )
    elif tag:
        all_docs_with_tag = (
            await session.execute(select(DocumentModel.id, DocumentModel.tags))
        ).all()
        from app.routers.documents import _safe_tags

        matching_doc_ids = [did for did, dtags in all_docs_with_tag if tag in _safe_tags(dtags)]

        stmt = (
            stmt.join(NoteModel, FlashcardModel.note_id == NoteModel.id, isouter=True)
            .join(NoteTagIndexModel, NoteModel.id == NoteTagIndexModel.note_id, isouter=True)
            .where(
                or_(
                    FlashcardModel.document_id.in_(matching_doc_ids) if matching_doc_ids else False,
                    NoteTagIndexModel.tag_full == tag,
                )
            )
        )

    stmt = stmt.order_by(FlashcardModel.due_date.asc()).limit(limit)
    result = await session.execute(stmt)
    cards = list(result.scalars().all())

    # Build chunk_id -> section_id map for SourcePanel
    repo = StudyRepo(session)
    chunk_to_section = await repo.chunk_section_id_map(
        [c.chunk_id for c in cards if c.chunk_id]
    )

    return [_to_response(c, section_id=chunk_to_section.get(c.chunk_id or "")) for c in cards]


@router.post("/assemble", response_model=AssembleResponse, status_code=201)
async def assemble_study(
    req: AssembleRequest,
    session: AsyncSession = Depends(get_db),
) -> AssembleResponse:
    """Study Launcher backend: resolve a scope -> a valid Study Event (docs/study-launcher.md).

    Returns the assembled due-card set + an honest preview, and records a StudyEvent row.
    Mode-aware: teachback_available reflects the feynman surface (full mode only). Model-down still
    yields due cards (generation is a separate seam).
    """
    result = await study_assembler.assemble(
        session,
        req.scope_type,
        req.scope_ref,
        length_min=req.length_min,
        want_generated=req.want_generated,
        # actually generate only on Start (commit), not on live preview
        do_generate=req.commit and req.want_generated,
    )

    event_id = ""
    if req.commit:
        event_id = uuid.uuid4().hex
        session.add(
            StudyEventModel(
                id=event_id,
                kind=req.mode,
                scope_type=req.scope_type,
                scope_ref=req.scope_ref,
            )
        )
        await session.commit()

    repo = StudyRepo(session)
    chunk_to_section = await repo.chunk_section_id_map(
        [c.chunk_id for c in result.cards if c.chunk_id]
    )
    cards = [
        _to_response(c, section_id=chunk_to_section.get(c.chunk_id or "")) for c in result.cards
    ]
    teachback_available = get_settings().LUMINARY_MODE == "full"

    return AssembleResponse(
        event_id=event_id,
        scope_type=req.scope_type,
        scope_ref=req.scope_ref,
        mode=req.mode,
        concept_ids=result.concept_ids,
        cards=cards,
        preview=AssemblePreview(
            due_count=result.preview.due_count,
            generated_count=result.preview.generated_count,
            mapped_count=result.preview.mapped_count,
            unmapped_count=result.preview.unmapped_count,
            topic_mix=result.preview.topic_mix,
            thin_scope_warning=result.preview.thin_scope_warning,
        ),
        teachback_available=teachback_available,
    )


@router.get("/session-plan", response_model=SessionPlanResponse)
async def get_session_plan(
    minutes: int = Query(default=20, ge=5, le=120),
    session: AsyncSession = Depends(get_db),
    repo: StudyRepo = Depends(get_study_repo),
) -> SessionPlanResponse:
    """Return a prioritized study agenda for the given time budget.

    DB-only -- no LLM. Due count, gap areas, and recent docs assembled
    and passed to the pure _build_session_plan() function.
    """
    now = datetime.now(UTC)

    # (a) Count all due flashcards (no document filter). Inline because
    # this is a single-purpose count -- no shared shape with /due-count.
    due_stmt = select(func.count()).select_from(FlashcardModel).where(
        FlashcardModel.due_date <= now
    )
    due_count = (await session.execute(due_stmt)).scalar_one()

    # (b) Gap area titles across all documents (max 2 distinct non-null headings)
    weak_cards = list(await repo.list_weak_flashcards())
    gap_area_titles: list[str] = []
    if weak_cards:
        chunk_to_section = await repo.chunk_section_headings(
            [c.chunk_id for c in weak_cards if c.chunk_id]
        )
        seen: set[str] = set()
        for heading in chunk_to_section.values():
            if heading and heading not in seen and len(gap_area_titles) < 2:
                seen.add(heading)
                gap_area_titles.append(heading)

    # (c) Fetch recently accessed complete documents. Inline -- this select
    # shape isn't reused; no value in a repo method for one caller.
    docs_stmt = (
        select(DocumentModel)
        .where(DocumentModel.stage == "complete")
        .order_by(DocumentModel.last_accessed_at.desc())
        .limit(3)
    )
    docs_result = await session.execute(docs_stmt)
    docs = docs_result.scalars().all()
    recent_docs = [(d.id, d.title) for d in docs]

    items = _build_session_plan(due_count, gap_area_titles, recent_docs, minutes)
    logger.debug(
        "session-plan assembled: due=%d gaps=%d docs=%d items=%d",
        due_count,
        len(gap_area_titles),
        len(recent_docs),
        len(items),
    )
    return SessionPlanResponse(total_minutes=minutes, items=items)


@router.get("/gaps/{document_id}", response_model=list[GapResult])
async def get_gaps(
    document_id: str,
    repo: StudyRepo = Depends(get_study_repo),
) -> list[GapResult]:
    """Return sections with weak (seen but fragile) flashcards, ordered by avg stability."""
    weak_cards = list(await repo.list_weak_flashcards(document_id=document_id))
    if not weak_cards:
        return []
    chunk_to_section = await repo.chunk_section_headings(
        [c.chunk_id for c in weak_cards if c.chunk_id]
    )
    return _compute_gaps(weak_cards, chunk_to_section)


@router.get("/sessions/open", response_model=SessionResponse)
async def get_open_session(
    mode: str,
    document_id: str | None = None,
    collection_id: str | None = None,
    repo: StudyRepo = Depends(get_study_repo),
) -> SessionResponse:
    """Return the most recent still-open session matching this scope.

    Used by the hook to auto-resume an in-progress session instead of creating
    a duplicate when the user clicks Start. Scope match is exact: a null
    document_id only matches sessions with null document_id.
    """
    sess = await repo.find_open_session(
        mode=mode,
        document_id=document_id,
        collection_id=collection_id,
    )
    if sess is None:
        raise HTTPException(status_code=404, detail="No open session")
    return SessionResponse.model_validate(sess)


@router.post("/sessions/start", response_model=SessionResponse, status_code=201)
async def start_session(
    req: StartSessionRequest,
    repo: StudyRepo = Depends(get_study_repo),
) -> SessionResponse:
    """Create a new study session row and return its ID."""
    sess = await repo.create_session(
        document_id=req.document_id,
        collection_id=req.collection_id,
        mode=req.mode,
        planned_card_ids=req.planned_card_ids,
    )
    logger.info(
        "Study session started",
        extra={
            "session_id": sess.id,
            "document_id": req.document_id,
            "collection_id": req.collection_id,
            "mode": req.mode,
        },
    )
    return SessionResponse.model_validate(sess)


async def _write_back_concept_mastery(
    session: AsyncSession, events: list[ReviewEventModel]
) -> None:
    """Recompute + store mastery for the concepts whose cards were reviewed this session."""
    card_ids = list({e.flashcard_id for e in events})
    if not card_ids:
        return
    rows = (
        await session.execute(
            select(FlashcardModel.concept_id).where(
                FlashcardModel.id.in_(card_ids), FlashcardModel.concept_id.is_not(None)
            )
        )
    ).scalars().all()
    concept_ids = [c for c in rows if c]
    if not concept_ids:
        return
    await get_mastery_service().recompute_for_concepts(session, concept_ids)
    await session.commit()


@router.post("/sessions/{session_id}/end", response_model=SessionSummary)
async def end_session(
    session_id: str,
    repo: StudyRepo = Depends(get_study_repo),
) -> SessionSummary:
    """Close a study session, tally review events, and return the summary."""
    sess = await repo.get_session_or_404(session_id)
    events = await repo.list_review_events(session_id)

    # Pull all teach-back rows (pending + complete). Pending rows mean the
    # background evaluator has not yet scored the answer -- we still count them
    # toward cards_reviewed (the user did answer) but leave accuracy provisional
    # until the last evaluation lands. _evaluate_teachback_bg finalizes the
    # tally when the last pending row flips to "complete".
    tb_rows = await repo.list_teachback_results(session_id)
    tb_pending_count = 0

    if tb_rows:
        # Latest attempt per card, not per submission: see _latest_attempt_per_card.
        cards_reviewed, cards_correct, accuracy_pct, tb_pending_count = _teachback_tally(
            tb_rows
        )
    else:
        # Latest event per card, for the same reason the teach-back arm reads its
        # latest attempt: a card graded twice in one sitting is one card
        # reviewed. `len(events)` counted the grades, which is the defect that
        # reached a learner as "30 of 15 reviewed" on the other arm (I-46).
        latest = _latest_event_per_card(events)
        cards_reviewed = len(latest)
        cards_correct = sum(1 for e in latest if e.is_correct)
        accuracy_pct: float | None = (
            round(cards_correct / cards_reviewed * 100, 1) if cards_reviewed > 0 else 0.0
        )

    ended_at = datetime.now(UTC)
    sess.ended_at = ended_at
    sess.cards_reviewed = cards_reviewed
    sess.cards_correct = cards_correct
    sess.accuracy_pct = accuracy_pct
    await repo.commit_session(sess)

    # Write-back: the assessment pipeline writes the grounded mastery to the concepts
    # touched this session (I-19). Best-effort -- a concepts hiccup never fails the end.
    try:
        await _write_back_concept_mastery(repo.session, events)
    except Exception:
        logger.warning("end_session: concept mastery write-back failed", exc_info=True)

    logger.info(
        "Study session ended",
        extra={
            "session_id": session_id,
            "cards_reviewed": cards_reviewed,
            "cards_correct": cards_correct,
            "accuracy_pct": accuracy_pct,
            "pending_evaluations": tb_pending_count,
        },
    )
    return SessionSummary(
        session_id=sess.id,
        cards_reviewed=cards_reviewed,
        cards_correct=cards_correct,
        accuracy_pct=accuracy_pct if accuracy_pct is not None else 0.0,
        ended_at=ended_at,
    )


@router.post("/sessions/{session_id}/reopen", status_code=204)
async def reopen_session(
    session_id: str,
    repo: StudyRepo = Depends(get_study_repo),
) -> None:
    """Clear ended_at on a session so the user can Continue adding answers.

    Tallies are reset; _finalize_session_tally_if_ready recomputes them the
    next time the session is ended and all evaluations are complete.
    """
    sess = await repo.get_session_or_404(session_id)
    sess.ended_at = None
    sess.cards_correct = 0
    sess.accuracy_pct = None
    await repo.commit_session(sess)
    logger.info("Study session reopened", extra={"session_id": session_id})


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    repo: StudyRepo = Depends(get_study_repo),
) -> None:
    """Delete a study session and all associated review events and teachback results."""
    await repo.delete_session_cascade(session_id)
    logger.info("Study session deleted", extra={"session_id": session_id})


async def _resolve_collection_members(
    collection_id: str, session: AsyncSession
) -> tuple[list[str], list[str]]:
    """Recursively identify all document and note IDs in a collection hierarchy."""
    # 1. Resolve all collection IDs in the hierarchy
    all_coll_ids = {collection_id}
    to_process = [collection_id]

    while to_process:
        curr_id = to_process.pop()
        children_stmt = select(CollectionModel.id).where(
            CollectionModel.parent_collection_id == curr_id
        )
        children = (await session.execute(children_stmt)).scalars().all()
        for child_id in children:
            if child_id not in all_coll_ids:
                all_coll_ids.add(child_id)
                to_process.append(child_id)

    # 2. Get members of all identified collections
    members_stmt = select(CollectionMemberModel.member_id, CollectionMemberModel.member_type).where(
        CollectionMemberModel.collection_id.in_(list(all_coll_ids))
    )
    members_rows = (await session.execute(members_stmt)).all()

    doc_ids = list({m[0] for m in members_rows if m[1] == "document"})
    note_ids = list({m[0] for m in members_rows if m[1] == "note"})
    return doc_ids, note_ids


@router.get(
    "/collections/{collection_id}/dashboard", response_model=StudyCollectionDashboardResponse
)
async def get_collection_study_dashboard(
    collection_id: str,
    session: AsyncSession = Depends(get_db),
) -> StudyCollectionDashboardResponse:
    """Return a summary of study status for all material in a collection

    Rewritten to use SQL aggregates and a small fixed number of queries regardless
    of tag count, sub-enclave count, or tree depth. Previously this endpoint could
    issue 20+ sequential queries per click.
    """
    from collections import defaultdict

    from app.routers.documents import _safe_tags

    # All queries in this endpoint share a session; the comment above the function
    # explains why the selects are inline (bespoke aggregation, flat query count).
    coll_result = await session.execute(
        select(CollectionModel.name).where(CollectionModel.id == collection_id)
    )
    coll_name = coll_result.scalar_one_or_none()
    if not coll_name:
        raise HTTPException(status_code=404, detail="Collection not found")

    # 2. Load the collection tree once and build parent->children adjacency in Python.
    # Collections are small (typically < 200 rows) so this beats recursive CTEs for
    # clarity and keeps query count flat regardless of tree depth.
    all_colls_rows = (
        await session.execute(
            select(CollectionModel.id, CollectionModel.parent_collection_id)
        )
    ).all()
    children_of: dict[str | None, list[str]] = defaultdict(list)
    for cid, pid in all_colls_rows:
        children_of[pid].append(cid)

    def _descendants(root: str) -> set[str]:
        out = {root}
        stack = [root]
        while stack:
            cur = stack.pop()
            for child in children_of.get(cur, ()):
                if child not in out:
                    out.add(child)
                    stack.append(child)
        return out

    hierarchy_ids = _descendants(collection_id)
    direct_children = children_of.get(collection_id, [])

    # For sub-enclave counts: compute each direct child's full descendant set and
    # track which descendants roll up to which sub-enclave root.
    descendants_by_child: dict[str, set[str]] = {
        child_id: _descendants(child_id) for child_id in direct_children
    }

    # 3. Fetch all members (docs + notes) of every collection in the hierarchy,
    # plus every direct-child subtree. One query.
    all_relevant_coll_ids = set(hierarchy_ids)
    for desc in descendants_by_child.values():
        all_relevant_coll_ids.update(desc)

    members_rows = (
        await session.execute(
            select(
                CollectionMemberModel.collection_id,
                CollectionMemberModel.member_id,
                CollectionMemberModel.member_type,
            ).where(CollectionMemberModel.collection_id.in_(list(all_relevant_coll_ids)))
        )
    ).all()

    # Bucket by hierarchy membership.
    doc_ids: set[str] = set()
    note_ids: set[str] = set()
    for coll_id, member_id, member_type in members_rows:
        if coll_id in hierarchy_ids:
            if member_type == "document":
                doc_ids.add(member_id)
            elif member_type == "note":
                note_ids.add(member_id)

    # 4. Flashcard aggregate stats -- one query, no rows pulled into memory.
    now = datetime.now(UTC)
    where_clauses = []
    if doc_ids:
        where_clauses.append(FlashcardModel.document_id.in_(list(doc_ids)))
    if note_ids:
        where_clauses.append(FlashcardModel.note_id.in_(list(note_ids)))

    if where_clauses:
        stats_row = (
            await session.execute(
                select(
                    func.count(FlashcardModel.id).label("total"),
                    func.sum(
                        case(
                            (
                                (FlashcardModel.due_date.is_not(None))
                                & (FlashcardModel.due_date <= now),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("due_today"),
                    func.sum(
                        case((FlashcardModel.fsrs_state == "new", 1), else_=0)
                    ).label("new_today"),
                    func.sum(
                        case((FlashcardModel.fsrs_stability > 30.0, 1), else_=0)
                    ).label("mastered"),
                ).where(or_(*where_clauses))
            )
        ).one()
        total = int(stats_row.total or 0)
        due_today = int(stats_row.due_today or 0)
        new_today = int(stats_row.new_today or 0)
        mastered = int(stats_row.mastered or 0)
    else:
        total = due_today = new_today = mastered = 0

    mastery_pct = round(mastered / total * 100, 1) if total else 0.0

    # 5. Topics: build tag->docs/notes maps, then a single aggregate query for card
    # counts per doc and per note. Replaces the old N+1 count loop.
    tag_to_docs: dict[str, set[str]] = defaultdict(set)
    tag_to_notes: dict[str, set[str]] = defaultdict(set)

    if doc_ids:
        docs_tag_rows = (
            await session.execute(
                select(DocumentModel.id, DocumentModel.tags).where(
                    DocumentModel.id.in_(list(doc_ids))
                )
            )
        ).all()
        for did, dtags in docs_tag_rows:
            for t in _safe_tags(dtags):
                tag_to_docs[t].add(did)

    if note_ids:
        note_tag_rows = (
            await session.execute(
                select(NoteTagIndexModel.tag_full, NoteTagIndexModel.note_id).where(
                    NoteTagIndexModel.note_id.in_(list(note_ids))
                )
            )
        ).all()
        for t, nid in note_tag_rows:
            tag_to_notes[t].add(nid)

    # Count cards per document and per note in ONE query each (two queries total).
    cards_per_doc: dict[str, int] = {}
    if doc_ids:
        rows = (
            await session.execute(
                select(
                    FlashcardModel.document_id,
                    func.count(FlashcardModel.id),
                )
                .where(FlashcardModel.document_id.in_(list(doc_ids)))
                .group_by(FlashcardModel.document_id)
            )
        ).all()
        cards_per_doc = {did: int(cnt) for did, cnt in rows}

    cards_per_note: dict[str, int] = {}
    if note_ids:
        rows = (
            await session.execute(
                select(
                    FlashcardModel.note_id,
                    func.count(FlashcardModel.id),
                )
                .where(FlashcardModel.note_id.in_(list(note_ids)))
                .group_by(FlashcardModel.note_id)
            )
        ).all()
        cards_per_note = {nid: int(cnt) for nid, cnt in rows}

    all_tags = set(tag_to_docs.keys()) | set(tag_to_notes.keys())
    topics: list[CollectionTopic] = []
    for t in all_tags:
        card_count = sum(cards_per_doc.get(d, 0) for d in tag_to_docs.get(t, ())) + sum(
            cards_per_note.get(n, 0) for n in tag_to_notes.get(t, ())
        )
        note_count = len(tag_to_notes.get(t, ()))
        if card_count > 0 or note_count > 0:
            topics.append(
                CollectionTopic(tag=t, card_count=card_count, note_count=note_count)
            )
    topics.sort(key=lambda x: (x.card_count, x.note_count), reverse=True)
    topics = topics[:10]

    # 6. Sources list. SUBSTR on note.content avoids streaming large note bodies
    # over the wire only to slice the first line.
    sources: list[CollectionSource] = []
    if doc_ids:
        # Weight documents by CHUNK COUNT, not word_count: word_count is 0 on many
        # large imported books (e.g. DDIA), which would starve the biggest source
        # to zero cards when splitting a collection-wide generation total.
        chunk_count_subq = (
            select(func.count(ChunkModel.id))
            .where(ChunkModel.document_id == DocumentModel.id)
            .scalar_subquery()
        )
        doc_rows = (
            await session.execute(
                select(
                    DocumentModel.id, DocumentModel.title, chunk_count_subq.label("chunks")
                ).where(DocumentModel.id.in_(list(doc_ids)))
            )
        ).all()
        for did, dtitle, dchunks in doc_rows:
            sources.append(
                CollectionSource(
                    id=did, title=dtitle, type="document", weight=int(dchunks or 0)
                )
            )
    if note_ids:
        note_snippet_rows = (
            await session.execute(
                select(
                    NoteModel.id,
                    func.substr(NoteModel.content, 1, 120).label("snippet"),
                    func.length(NoteModel.content).label("chars"),
                ).where(NoteModel.id.in_(list(note_ids)))
            )
        ).all()
        for nid, snippet, chars in note_snippet_rows:
            ntitle = (snippet or "").split("\n")[0][:60] or "Untitled Note"
            # express note size in chunk-equivalents (~1500 chars/chunk) so notes
            # share a unit with documents; never 0 for a non-empty note.
            note_weight = max(1, int((chars or 0) / 1500)) if chars else 0
            sources.append(
                CollectionSource(id=nid, title=ntitle, type="note", weight=note_weight)
            )

    # 7. Sub-enclaves: for each direct child we already know its full descendant set.
    # Map descendant collection ID -> sub-enclave root, then bucket the members rows
    # we already fetched. One pass, zero extra queries.
    desc_to_root: dict[str, str] = {}
    for child_id, desc_set in descendants_by_child.items():
        for d in desc_set:
            desc_to_root.setdefault(d, child_id)

    sub_doc_ids: dict[str, set[str]] = defaultdict(set)
    sub_note_ids: dict[str, set[str]] = defaultdict(set)
    for coll_id, member_id, member_type in members_rows:
        root = desc_to_root.get(coll_id)
        if root is None:
            continue
        if member_type == "document":
            sub_doc_ids[root].add(member_id)
        elif member_type == "note":
            sub_note_ids[root].add(member_id)

    # Child card counts reuse cards_per_doc / cards_per_note -- but those only cover
    # hierarchy_ids members. Sub-enclave members can include docs/notes outside the
    # parent hierarchy (when a child enclave directly holds an item the parent does
    # not). Top up with one extra pair of queries for any missing IDs.
    missing_doc_ids = (
        set().union(*sub_doc_ids.values()) if sub_doc_ids else set()
    ) - doc_ids
    missing_note_ids = (
        set().union(*sub_note_ids.values()) if sub_note_ids else set()
    ) - note_ids
    if missing_doc_ids:
        rows = (
            await session.execute(
                select(
                    FlashcardModel.document_id,
                    func.count(FlashcardModel.id),
                )
                .where(FlashcardModel.document_id.in_(list(missing_doc_ids)))
                .group_by(FlashcardModel.document_id)
            )
        ).all()
        for did, cnt in rows:
            cards_per_doc[did] = int(cnt)
    if missing_note_ids:
        rows = (
            await session.execute(
                select(
                    FlashcardModel.note_id,
                    func.count(FlashcardModel.id),
                )
                .where(FlashcardModel.note_id.in_(list(missing_note_ids)))
                .group_by(FlashcardModel.note_id)
            )
        ).all()
        for nid, cnt in rows:
            cards_per_note[nid] = int(cnt)

    child_name_map: dict[str, str] = {}
    if direct_children:
        name_rows = (
            await session.execute(
                select(CollectionModel.id, CollectionModel.name).where(
                    CollectionModel.id.in_(direct_children)
                )
            )
        ).all()
        child_name_map = dict(name_rows)

    sub_collections: list[CollectionSubCollection] = []
    for child_id in direct_children:
        count = sum(cards_per_doc.get(d, 0) for d in sub_doc_ids.get(child_id, ())) + sum(
            cards_per_note.get(n, 0) for n in sub_note_ids.get(child_id, ())
        )
        sub_collections.append(
            CollectionSubCollection(
                id=child_id,
                name=child_name_map.get(child_id, ""),
                card_count=count,
            )
        )

    return StudyCollectionDashboardResponse(
        collection_id=collection_id,
        collection_name=coll_name,
        due_today=due_today,
        new_today=new_today,
        mastery_pct=mastery_pct,
        topics=topics,
        sources=sources,
        sub_collections=sub_collections,
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    document_id: str | None = None,
    collection_id: str | None = Query(
        default=None, description="Filter sessions to a specific collection/enclave"
    ),
    mode: str | None = Query(default=None, description="Filter by mode: flashcard, teachback"),
    status: str | None = Query(
        default=None, description="Filter by status: incomplete (no ended_at), complete"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    """Return a paginated list of study sessions sorted by started_at desc."""
    base_stmt = select(StudySessionModel)
    if document_id:
        base_stmt = base_stmt.where(StudySessionModel.document_id == document_id)
    if collection_id:
        base_stmt = base_stmt.where(StudySessionModel.collection_id == collection_id)
    if mode:
        base_stmt = base_stmt.where(StudySessionModel.mode == mode)
    if status == "incomplete":
        base_stmt = base_stmt.where(StudySessionModel.ended_at.is_(None))
    elif status == "complete":
        base_stmt = base_stmt.where(StudySessionModel.ended_at.is_not(None))

    count_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    sessions_result = await db.execute(
        base_stmt.order_by(StudySessionModel.started_at.desc()).offset(offset).limit(page_size)
    )
    sessions = sessions_result.scalars().all()

    # Collect unique doc IDs to fetch titles in one query
    doc_ids = {s.document_id for s in sessions if s.document_id}
    doc_titles: dict[str, str] = {}
    if doc_ids:
        docs_result = await db.execute(select(DocumentModel).where(DocumentModel.id.in_(doc_ids)))
        for doc in docs_result.scalars().all():
            doc_titles[doc.id] = doc.title

    coll_ids = {s.collection_id for s in sessions if s.collection_id}
    coll_names: dict[str, str] = {}
    if coll_ids:
        colls_result = await db.execute(
            select(CollectionModel).where(CollectionModel.id.in_(coll_ids))
        )
        for coll in colls_result.scalars().all():
            coll_names[coll.id] = coll.name

    # Map session_id -> pending teach-back count so the UI knows which rows
    # still need polling. Single grouped query beats N+1.
    session_ids = [s.id for s in sessions]
    pending_by_session: dict[str, int] = {}
    if session_ids:
        pending_result = await db.execute(
            select(
                TeachbackResultModel.session_id,
                func.count().label("n"),
            )
            .where(
                TeachbackResultModel.session_id.in_(session_ids),
                TeachbackResultModel.status == "pending",
            )
            .group_by(TeachbackResultModel.session_id)
        )
        pending_by_session = {
            sid: n for sid, n in pending_result.all() if sid is not None
        }

    items: list[SessionListItem] = []
    for sess in sessions:
        duration: float | None = None
        if sess.ended_at:
            duration = round((sess.ended_at - sess.started_at).total_seconds() / 60, 2)
        items.append(
            SessionListItem(
                id=sess.id,
                started_at=sess.started_at,
                ended_at=sess.ended_at,
                duration_minutes=duration,
                cards_reviewed=sess.cards_reviewed,
                cards_correct=sess.cards_correct,
                accuracy_pct=sess.accuracy_pct,
                document_id=sess.document_id,
                document_title=doc_titles.get(sess.document_id) if sess.document_id else None,
                collection_id=sess.collection_id,
                collection_name=coll_names.get(sess.collection_id) if sess.collection_id else None,
                mode=sess.mode,
                has_pending_evaluations=pending_by_session.get(sess.id, 0) > 0,
            )
        )

    logger.debug("list_sessions: page=%d page_size=%d total=%d", page, page_size, total)
    return SessionListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/sessions/{session_id}/cards", response_model=list[SessionCardDetail])
async def get_session_cards(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[SessionCardDetail]:
    """Return per-card rating and correctness for a given session."""
    sess_result = await db.execute(
        select(StudySessionModel).where(StudySessionModel.id == session_id)
    )
    if sess_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Session not found")

    events_result = await db.execute(
        select(ReviewEventModel, FlashcardModel)
        .join(FlashcardModel, ReviewEventModel.flashcard_id == FlashcardModel.id)
        .where(ReviewEventModel.session_id == session_id)
        .order_by(ReviewEventModel.reviewed_at)
    )
    rows = events_result.all()

    return [
        SessionCardDetail(
            flashcard_id=event.flashcard_id,
            question=card.question,
            rating=event.rating,
            is_correct=event.is_correct,
            reviewed_at=event.reviewed_at,
        )
        for event, card in rows
    ]




@router.post(
    "/sessions/{session_id}/cards",
    response_model=AppendSessionCardsResponse,
)
async def append_session_cards(
    session_id: str,
    req: AppendSessionCardsRequest,
    repo: StudyRepo = Depends(get_study_repo),
) -> AppendSessionCardsResponse:
    """Add cards to an open session's planned queue.

    A run is reconstructed from `planned_card_ids` on every resume, so cards
    generated mid-run have to join the queue here and not only in the client's
    memory -- otherwise the reader adds five questions, answers two, closes the
    tab, and comes back to a run that never heard of them.

    Ids that are not real cards are dropped rather than queued: a planned id
    with no row behind it makes `remaining-cards` return a shorter queue than
    `planned_count` promises, which reads as a run stuck short of its own total.
    """
    sess = await repo.get_session_or_404(session_id)
    live_ids = set(await FlashcardRepo(repo.session).list_existing_ids_in(req.card_ids))
    added = repo.append_planned_cards(
        sess, [cid for cid in req.card_ids if cid in live_ids]
    )
    if added:
        await repo.commit_session(sess)
    planned_count = len(sess.planned_card_ids or [])
    logger.info(
        "Study session cards appended",
        extra={
            "session_id": session_id,
            "requested": len(req.card_ids),
            "added": added,
            "planned_count": planned_count,
        },
    )
    return AppendSessionCardsResponse(
        session_id=session_id, added=added, planned_count=planned_count
    )


@router.get(
    "/sessions/{session_id}/remaining-cards",
    response_model=SessionRemainingResponse,
)
async def get_session_remaining_cards(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> SessionRemainingResponse:
    """Return the unanswered flashcards from this session's planned queue.

    Used by resume so the queue reflects what was originally planned, not the
    set of cards currently due for the scope. Also returns the count of already-
    answered cards so the hook can restore the progress indicator on resume.

    Both counts are over the planned cards that STILL EXIST: a deck replaced
    under an open run deletes cards it planned, and those are neither progress
    nor work outstanding (I-47).
    """
    sess_result = await db.execute(
        select(StudySessionModel).where(StudySessionModel.id == session_id)
    )
    sess = sess_result.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")

    planned_ids: list[str] = list(sess.planned_card_ids or [])
    if not planned_ids:
        logger.warning(
            "remaining-cards: session has empty planned_card_ids",
            extra={"session_id": session_id, "ended_at": str(sess.ended_at)},
        )
        return SessionRemainingResponse(
            answered_count=0, planned_count=0, cards=[]
        )

    # A card is "answered" if it has a teach-back result OR a review event for this session.
    tb_result = await db.execute(
        select(TeachbackResultModel.flashcard_id).where(
            TeachbackResultModel.session_id == session_id
        )
    )
    answered: set[str] = {row[0] for row in tb_result.all()}
    rev_result = await db.execute(
        select(ReviewEventModel.flashcard_id).where(
            ReviewEventModel.session_id == session_id
        )
    )
    answered.update(row[0] for row in rev_result.all())

    # Planned means planned AND still there. Replacing a deck deletes the cards
    # an open run planned, and counting the dead ids made the header read "7 of 8
    # reviewed" over a deck of three: five of the seven were cards no learner
    # could be shown again. A deleted card leaves BOTH sides of the ratio -- it is
    # not progress, and it is not work outstanding either. The client cannot
    # repair this downstream, because dropping the dead ids from `cards` alone
    # keeps answered + remaining == planned and the inflation stays invisible.
    cards_result = await db.execute(
        select(FlashcardModel).where(FlashcardModel.id.in_(planned_ids))
    )
    live_by_id = {c.id: c for c in cards_result.scalars().all()}
    # Preserve the original planned order.
    live_planned = [cid for cid in planned_ids if cid in live_by_id]

    answered_in_planned = answered & set(live_planned)
    remaining_ids = [cid for cid in live_planned if cid not in answered_in_planned]
    return SessionRemainingResponse(
        answered_count=len(answered_in_planned),
        planned_count=len(live_planned),
        cards=[_to_response(live_by_id[cid]) for cid in remaining_ids],
    )


@router.post("/teachback", response_model=TeachbackResponse)
async def teachback(
    req: TeachbackRequest,
    session: AsyncSession = Depends(get_db),
) -> TeachbackResponse:
    """Evaluate a student's teach-back explanation with LLM. Tracks misconceptions."""
    # Flashcard lookup; shares session with the persist writes below so all
    # teachback artifacts (result row, misconceptions, correction card) commit together.
    card_result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.id == req.flashcard_id)
    )
    card = card_result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    # Call LLM to evaluate explanation
    source = await _source_passage(card, session)
    prompt = _TEACHBACK_USER_TMPL.format(
        source=source or "(the source passage could not be recovered)",
        question=card.question,
        answer=card.answer,
        explanation=req.user_explanation,
    )
    parsed = await _evaluate_teachback_llm(prompt)
    if parsed is None:
        raise HTTPException(
            status_code=503,
            detail="The model returned an unreadable evaluation. Please try again.",
        )
    score = parsed.get("score", 0)
    correct_points: list[str] = parsed.get("correct_points", [])
    missing_points: list[str] = parsed.get("missing_points", [])
    misconceptions: list[str] = parsed.get("misconceptions", [])

    # The rubric comes out of the call above, not a second one of its own. See
    # _rubric_from_evaluation for what that call was grading against before.
    rubric_dict = _rubric_from_evaluation(parsed, _verified_evidence(parsed, source))

    # Persist all teachback artifacts (result + optional misconceptions) atomically;
    # the correction card is generated mid-session so it must land in the same tx.
    tb_result = TeachbackResultModel(
        id=str(uuid.uuid4()),
        flashcard_id=card.id,
        user_explanation=req.user_explanation,
        score=score,
        correct_points=correct_points,
        missing_points=missing_points,
        misconceptions=misconceptions,
        rubric_json=rubric_dict,
    )
    session.add(tb_result)

    correction_card_id: str | None = None

    # If score < 60 and there are misconceptions, create MisconceptionModel rows
    # and a correction flashcard
    if score < 60 and misconceptions:
        # Only persist misconceptions when document_id is set;
        # note-sourced flashcards have document_id=None.
        if card.document_id:
            for m_text in misconceptions:
                misconception = MisconceptionModel(
                    id=str(uuid.uuid4()),
                    document_id=card.document_id,
                    flashcard_id=card.id,
                    user_answer=req.user_explanation,
                    error_type="misconception",
                    correction_note=m_text,
                )
                session.add(misconception)

        # Generate a correction flashcard targeting the first misconception
        correction_card_id = await _generate_correction_flashcard(
            card=card,
            misconception=misconceptions[0],
            session=session,
        )

    # this legacy path skips FSRS scheduling, so the resolve-on-good-review hook
    # in fsrs_service never fires here -- resolve passing scores explicitly
    if score >= PASSING_TEACHBACK_SCORE:
        await resolve_for_flashcard(session, card.id)

    await session.commit()
    logger.info(
        "Teachback evaluated",
        extra={"flashcard_id": card.id, "score": score, "misconceptions": len(misconceptions)},
    )

    # Build rubric response
    rubric_response: TeachbackRubricResponse | None = None
    if rubric_dict is not None:
        try:
            rubric_response = TeachbackRubricResponse(
                accuracy=RubricDimensionResponse(**rubric_dict["accuracy"]),
                completeness=RubricCompletenessResponse(**rubric_dict["completeness"]),
                clarity=RubricDimensionResponse(**rubric_dict["clarity"]),
            )
        except (KeyError, TypeError, ValueError):
            rubric_response = None

    return TeachbackResponse(
        score=score,
        correct_points=correct_points,
        missing_points=missing_points,
        misconceptions=misconceptions,
        correction_flashcard_id=correction_card_id,
        rubric=rubric_response,
    )


# Async teach-back: submit + background evaluate + batch poll


def _score_to_rating(score: int) -> str:
    """Map teach-back score (0-100) to FSRS rating for spaced repetition."""
    if score >= 80:
        return "good"
    if score >= 60:
        return "hard"
    return "again"


def _latest_attempt_per_card(
    rows: Sequence[TeachbackResultModel],
) -> list[TeachbackResultModel]:
    """One row per card: the latest attempt, which is the verdict that stands.

    A card can be answered more than once in a run -- that is the whole point of
    "Answer this one again". Counting every attempt made the same question
    appear twice in the summary and averaged a score the learner had already
    replaced into the one they are shown: a 10 improved to a 45 read as two
    cards averaging 27.5, and the run's card count exceeded the cards in it.

    The earlier attempts are kept, never deleted. They are the record of how the
    learner got there; they are just not the verdict.
    """
    latest: dict[str, TeachbackResultModel] = {}
    for row in sorted(rows, key=lambda r: (r.created_at, r.id)):
        latest[row.flashcard_id] = row
    return list(latest.values())


def _latest_event_per_card(
    events: Sequence[ReviewEventModel],
) -> list[ReviewEventModel]:
    """One review event per card: the latest, which is the grade that stands.

    The recall arm's twin of `_latest_attempt_per_card`. A card can be graded
    more than once in a sitting, and the summary counts cards, not grades.
    """
    latest: dict[str, ReviewEventModel] = {}
    for event in sorted(events, key=lambda e: (e.reviewed_at, e.id)):
        latest[event.flashcard_id] = event
    return list(latest.values())


def _teachback_tally(
    rows: Sequence[TeachbackResultModel],
) -> tuple[int, int, float | None, int]:
    """(cards_reviewed, cards_correct, accuracy_pct, pending) over latest attempts.

    accuracy_pct is None while any card's standing attempt is still being
    scored: a mean over the ones that happen to have finished is a number for a
    run that is not over. It is never defaulted to 0.0 -- an unscored card is
    unscored, not a zero (see `_parse_teachback_response`).
    """
    latest = _latest_attempt_per_card(rows)
    pending = sum(1 for tb in latest if tb.status == "pending")
    scores = [tb.score for tb in latest if tb.status == "complete" and tb.score is not None]
    accuracy = None if pending else (round(sum(scores) / len(scores), 1) if scores else 0.0)
    return len(latest), sum(1 for sc in scores if sc >= 60), accuracy, pending


async def _is_first_attempt(
    session: AsyncSession,
    tb_row: TeachbackResultModel,
) -> bool:
    """True when no earlier attempt on this card exists in this session."""
    if tb_row.session_id is None:
        return True
    earlier = await session.execute(
        select(TeachbackResultModel.id)
        .where(
            TeachbackResultModel.session_id == tb_row.session_id,
            TeachbackResultModel.flashcard_id == tb_row.flashcard_id,
            TeachbackResultModel.created_at < tb_row.created_at,
        )
        .limit(1)
    )
    return earlier.scalar_one_or_none() is None


async def _finalize_session_tally_if_ready(
    session: AsyncSession,
    session_id: str,
) -> None:
    """Recompute session tally once the last pending teach-back completes.

    Called from the background evaluator after writing a teach-back result.
    No-op if the session hasn't been ended yet, or if there are still pending
    evaluations (they will trigger the final update themselves).
    """
    sess_result = await session.execute(
        select(StudySessionModel).where(StudySessionModel.id == session_id)
    )
    sess = sess_result.scalar_one_or_none()
    if sess is None or sess.ended_at is None:
        return

    tb_result = await session.execute(
        select(TeachbackResultModel).where(
            TeachbackResultModel.session_id == session_id,
        )
    )
    tb_rows = tb_result.scalars().all()
    if not tb_rows:
        return
    if any(tb.status == "pending" for tb in tb_rows):
        return

    reviewed, correct, accuracy, _pending = _teachback_tally(tb_rows)
    sess.cards_reviewed = reviewed
    sess.cards_correct = correct
    sess.accuracy_pct = accuracy
    logger.info(
        "Study session tally finalized",
        extra={
            "session_id": session_id,
            "cards_reviewed": sess.cards_reviewed,
            "cards_correct": sess.cards_correct,
            "accuracy_pct": sess.accuracy_pct,
        },
    )


async def _evaluate_teachback_bg(
    tb_id: str,
    card_id: str,
    card_answer: str,
    card_document_id: str,
    card_question: str,
    user_explanation: str,
    session_id: str | None = None,
) -> None:
    """Background coroutine: evaluate teach-back and update the row.

    Uses its own DB session (invariant I-1: no shared AsyncSession across tasks).
    After scoring, creates an FSRS review + ReviewEventModel so teach-back
    results feed into spaced repetition and session progress stats.

    Exactly one LLM call stands between the learner submitting and the verdict
    appearing. It used to be two, and three on a card scored under 60 -- which
    is the card a learner most wants an answer on -- all of them serial and all
    of them finishing before the row flipped to "complete". The rubric is now
    read off this call (`_rubric_from_evaluation`) and the correction card is
    written afterwards by `_teachback_correction_bg`, because the learner never
    sees that card during the run they are waiting in. Ollama yields at the
    granularity of one completed call (I-31), so the only lever on this wait is
    how many calls it contains.
    """
    logger.info("Teachback bg task started for %s", tb_id)

    # The passage, read in its own short-lived session before the LLM work: this
    # coroutine must not share a session with its caller (I-1), and holding one
    # across an LLM call starves concurrent writers.
    source = ""
    factory = get_session_factory()
    async with factory() as read_session:
        card_row = (
            await read_session.execute(
                select(FlashcardModel).where(FlashcardModel.id == card_id)
            )
        ).scalar_one_or_none()
        if card_row is not None:
            source = await _source_passage(card_row, read_session)

    # The one call on the critical path. The rubric comes out of it rather than
    # out of a second call of its own.
    prompt = _TEACHBACK_USER_TMPL.format(
        source=source or "(the source passage could not be recovered)",
        question=card_question,
        answer=card_answer,
        explanation=user_explanation,
    )
    parsed = await _evaluate_teachback_llm(prompt)
    if parsed is None:
        await _mark_teachback_error(tb_id)
        return
    score = parsed.get("score", 0)
    correct_points: list[str] = parsed.get("correct_points", [])
    missing_points: list[str] = parsed.get("missing_points", [])
    misconceptions: list[str] = parsed.get("misconceptions", [])

    # A correction card asserts the student is wrong about something. The
    # evaluator has to have quoted the passage before the product will say that:
    # if it could not produce a sentence that is really there, its misconception
    # list is not grounded in anything, and the card it seeds would carry an
    # invented quote of its own.
    evidence = _verified_evidence(parsed, source)
    rubric_dict = _rubric_from_evaluation(parsed, evidence)
    rating = _score_to_rating(score)

    # Serialize DB writes to avoid SQLite "database is locked" (invariant I-1)
    async with _teachback_eval_sem:
        session_factory = get_session_factory()
        async with session_factory() as session:
            try:
                # Update the pending row
                result = await session.execute(
                    select(TeachbackResultModel).where(
                        TeachbackResultModel.id == tb_id
                    )
                )
                tb_row = result.scalar_one_or_none()
                if tb_row is None:
                    logger.error("Teachback row %s disappeared", tb_id)
                    return

                tb_row.score = score
                tb_row.correct_points = correct_points
                tb_row.missing_points = missing_points
                tb_row.misconceptions = misconceptions
                tb_row.rubric_json = rubric_dict
                tb_row.status = "complete"

                # FSRS is scheduled by the FIRST attempt on this card in this
                # session, and by no later one. A re-answer is written after the
                # panel has shown the expected answer and the points that were
                # missed, so what the learner says the second time is partly the
                # product's own text handed back -- scheduling on it would let
                # material we supplied set the retention interval. The later
                # attempt is still stored, still scored, and still what the
                # summary reads; it just does not move the card's schedule.
                first_attempt = await _is_first_attempt(session, tb_row)
                if first_attempt:
                    fsrs = get_fsrs_service()
                    await fsrs.schedule(card_id, rating, session)

                    # ReviewEventModel so end_session tallies include this card.
                    # One event per card per session, for the same reason.
                    if session_id:
                        event = ReviewEventModel(
                            id=str(uuid.uuid4()),
                            session_id=session_id,
                            flashcard_id=card_id,
                            rating=rating,
                            is_correct=rating != "again",
                        )
                        session.add(event)

                # Self-heal session tally: if the parent session has already
                # been ended by the user (e.g. they navigated away mid-eval)
                # and this was the last pending evaluation, recompute
                # cards_correct / accuracy_pct on the session row so session
                # history reflects the final scores.
                if session_id:
                    await _finalize_session_tally_if_ready(session, session_id)

                await session.commit()
                logger.info(
                    "Teachback bg evaluated",
                    extra={
                        "teachback_id": tb_id,
                        "score": score,
                        "fsrs_rating": rating,
                        "rescheduled": first_attempt,
                        "rubric": rubric_dict is not None,
                    },
                )

            except Exception:
                logger.exception(
                    "Teachback background evaluation failed for %s", tb_id
                )
                try:
                    await session.rollback()
                    result = await session.execute(
                        select(TeachbackResultModel).where(
                            TeachbackResultModel.id == tb_id
                        )
                    )
                    tb_row = result.scalar_one_or_none()
                    if tb_row:
                        tb_row.status = "error"
                        await session.commit()
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Failed to mark teachback %s as error", tb_id
                    )
                return

    # The verdict is on screen by here. What follows costs another LLM call and
    # produces a card the learner meets in a later run, so it is not something
    # they should wait on.
    if score < 60 and misconceptions:
        if evidence:
            _fire_and_forget(
                _teachback_correction_bg(
                    tb_id=tb_id,
                    card_id=card_id,
                    card_document_id=card_document_id,
                    user_explanation=user_explanation,
                    misconceptions=misconceptions,
                    source=source,
                )
            )
        else:
            logger.info(
                "teachback %s: misconceptions reported without a verifiable quote; "
                "no correction card",
                tb_id,
            )


async def _teachback_correction_bg(
    tb_id: str,
    card_id: str,
    card_document_id: str,
    user_explanation: str,
    misconceptions: list[str],
    source: str,
) -> None:
    """Record the misconceptions and seed a correction card, after the verdict.

    Split out of `_evaluate_teachback_bg` because it was the third serial LLM
    call in front of a learner watching a spinner, for a card that only appears
    in a later run. Failing here costs the correction card and nothing else --
    the teach-back row is already complete and committed.
    """
    factory = get_session_factory()
    async with factory() as read_session:
        correction_card = (
            await read_session.execute(
                select(FlashcardModel).where(FlashcardModel.id == card_id)
            )
        ).scalar_one_or_none()
    if correction_card is None:
        return

    # Background: the verdict is already on screen, so nobody is waiting for
    # this. Unmarked, it held the runtime's only slot after the run ended and
    # blocked the next interactive call -- saving a note awaits the tagger
    # (notes.py), so a learner who finished practising and typed a note watched
    # it hang on "Saving..." behind a card they will not see for days.
    payload = await _llm_correction_card_payload(
        card=correction_card,
        misconception=misconceptions[0],
        source=source,
        background=True,
    )

    # Serialize DB writes to avoid SQLite "database is locked" (invariant I-1)
    async with _teachback_eval_sem:
        async with factory() as session:
            try:
                if card_document_id:
                    for m_text in misconceptions:
                        session.add(
                            MisconceptionModel(
                                id=str(uuid.uuid4()),
                                document_id=card_document_id,
                                flashcard_id=card_id,
                                user_answer=user_explanation,
                                error_type="misconception",
                                correction_note=m_text,
                            )
                        )
                if payload is not None:
                    await _insert_correction_flashcard(
                        card=correction_card,
                        payload=payload,
                        session=session,
                        source=source,
                    )
                await session.commit()
            except Exception:
                logger.exception(
                    "Teachback correction card failed for %s", tb_id
                )
                await session.rollback()


@router.post("/teachback/async", response_model=TeachbackSubmitResponse)
async def teachback_async(
    req: TeachbackRequest,
    session: AsyncSession = Depends(get_db),
) -> TeachbackSubmitResponse:
    """Submit teach-back for background evaluation. Returns immediately."""
    # Existence check + pending row persist share one session; the bg evaluator
    # opens its own session (invariant I-1).
    card_result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.id == req.flashcard_id)
    )
    card = card_result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    # Ensure the study session is marked as teachback mode
    if req.session_id:
        sess_result = await session.execute(
            select(StudySessionModel).where(
                StudySessionModel.id == req.session_id
            )
        )
        study_sess = sess_result.scalar_one_or_none()
        if study_sess and study_sess.mode != "teachback":
            study_sess.mode = "teachback"

    # Persist pending row
    tb_id = str(uuid.uuid4())
    tb_row = TeachbackResultModel(
        id=tb_id,
        flashcard_id=card.id,
        user_explanation=req.user_explanation,
        score=0,
        correct_points=[],
        missing_points=[],
        misconceptions=[],
        status="pending",
        session_id=req.session_id,
    )
    session.add(tb_row)
    await session.commit()
    logger.info("Teachback async submitted: id=%s flashcard=%s", tb_id, card.id)

    # Fire background evaluation
    _fire_and_forget(
        _evaluate_teachback_bg(
            tb_id=tb_id,
            card_id=card.id,
            card_answer=card.answer,
            card_document_id=card.document_id,
            card_question=card.question,
            user_explanation=req.user_explanation,
            session_id=req.session_id,
        )
    )

    return TeachbackSubmitResponse(id=tb_id)


@router.get("/teachback/results", response_model=TeachbackResultsBatchResponse)
async def get_teachback_results(
    ids: str = Query(..., description="Comma-separated teachback result IDs"),
    session: AsyncSession = Depends(get_db),
) -> TeachbackResultsBatchResponse:
    """Batch-poll teach-back results by IDs."""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        return TeachbackResultsBatchResponse(results=[])

    # Cross-table join (TeachbackResultModel + FlashcardModel) for question/answer text;
    # no repo owns both tables, so the join lives in the router.
    stmt = (
        select(TeachbackResultModel, FlashcardModel.question, FlashcardModel.answer)
        .join(
            FlashcardModel,
            TeachbackResultModel.flashcard_id == FlashcardModel.id,
            isouter=True,
        )
        .where(TeachbackResultModel.id.in_(id_list))
    )
    rows = (await session.execute(stmt)).all()

    items: list[TeachbackResultItem] = []
    for tb, question, expected_answer in rows:
        rubric_response: TeachbackRubricResponse | None = None
        if tb.status == "complete" and tb.rubric_json is not None:
            try:
                rubric_response = TeachbackRubricResponse(
                    accuracy=RubricDimensionResponse(**tb.rubric_json["accuracy"]),
                    completeness=RubricCompletenessResponse(
                        **tb.rubric_json["completeness"]
                    ),
                    clarity=RubricDimensionResponse(**tb.rubric_json["clarity"]),
                )
            except (KeyError, TypeError, ValueError):
                rubric_response = None

        items.append(
            TeachbackResultItem(
                id=tb.id,
                status=tb.status,
                flashcard_id=tb.flashcard_id,
                question=question or "",
                expected_answer=expected_answer or "",
                score=tb.score if tb.status == "complete" else None,
                correct_points=tb.correct_points if tb.status == "complete" else [],
                missing_points=tb.missing_points if tb.status == "complete" else [],
                misconceptions=tb.misconceptions if tb.status == "complete" else [],
                rubric=rubric_response,
                user_explanation=tb.user_explanation if tb.status == "complete" else None,
            )
        )

    return TeachbackResultsBatchResponse(results=items)


@router.get(
    "/sessions/{session_id}/teachback-results",
    response_model=TeachbackResultsBatchResponse,
)
async def get_session_teachback_results(
    session_id: str,
    session: AsyncSession = Depends(get_db),
) -> TeachbackResultsBatchResponse:
    """Get all teach-back results for a study session."""
    # Cross-table join for question/answer text; same pattern as get_teachback_results.
    stmt = (
        select(TeachbackResultModel, FlashcardModel.question, FlashcardModel.answer)
        .join(
            FlashcardModel,
            TeachbackResultModel.flashcard_id == FlashcardModel.id,
            isouter=True,
        )
        .where(TeachbackResultModel.session_id == session_id)
        .order_by(TeachbackResultModel.created_at)
    )
    rows = (await session.execute(stmt)).all()

    items: list[TeachbackResultItem] = []
    for tb, question, expected_answer in rows:
        rubric_response: TeachbackRubricResponse | None = None
        if tb.status == "complete" and tb.rubric_json is not None:
            try:
                rubric_response = TeachbackRubricResponse(
                    accuracy=RubricDimensionResponse(**tb.rubric_json["accuracy"]),
                    completeness=RubricCompletenessResponse(
                        **tb.rubric_json["completeness"]
                    ),
                    clarity=RubricDimensionResponse(**tb.rubric_json["clarity"]),
                )
            except (KeyError, TypeError, ValueError):
                rubric_response = None

        items.append(
            TeachbackResultItem(
                id=tb.id,
                status=tb.status,
                flashcard_id=tb.flashcard_id,
                question=question or "",
                expected_answer=expected_answer or "",
                score=tb.score if tb.status == "complete" else None,
                correct_points=tb.correct_points if tb.status == "complete" else [],
                missing_points=tb.missing_points if tb.status == "complete" else [],
                misconceptions=tb.misconceptions if tb.status == "complete" else [],
                rubric=rubric_response,
                user_explanation=tb.user_explanation if tb.status == "complete" else None,
            )
        )

    return TeachbackResultsBatchResponse(results=items)


@router.get("/stats/{document_id}", response_model=StudyStatsResponse)
async def get_study_stats(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> StudyStatsResponse:
    """Return progress statistics for a document."""
    now = datetime.now(UTC)

    # --- All flashcards for the document ---
    cards_result = await db.execute(
        select(FlashcardModel).where(FlashcardModel.document_id == document_id)
    )
    all_cards = cards_result.scalars().all()
    total_cards = len(all_cards)

    # --- Mastered cards ---
    cards_mastered = sum(
        1 for c in all_cards if c.fsrs_state == "review" and c.fsrs_stability > 30.0
    )
    mastery_pct = round(cards_mastered / total_cards * 100, 1) if total_cards > 0 else 0.0

    # --- Due and New counts ---
    due_today = sum(1 for c in all_cards if c.due_date and c.due_date.replace(tzinfo=UTC) <= now)
    new_today = sum(1 for c in all_cards if c.fsrs_state == "new")

    # --- Average retention: e^(-t/S) for reviewed cards ---
    retention_values: list[float] = []
    for c in all_cards:
        if c.last_review and c.fsrs_stability > 0:
            last_review_aware = c.last_review.replace(tzinfo=UTC)
            days_since = (now - last_review_aware).total_seconds() / 86400
            retention_values.append(math.exp(-days_since / c.fsrs_stability))
    avg_retention = (
        round(sum(retention_values) / len(retention_values), 4) if retention_values else 0.0
    )

    # --- Study sessions for this document ---
    sessions_result = await db.execute(
        select(StudySessionModel).where(StudySessionModel.document_id == document_id)
    )
    sessions = sessions_result.scalars().all()

    # --- Total study time (minutes) ---
    total_study_time_minutes = sum(
        (s.ended_at.replace(tzinfo=UTC) - s.started_at.replace(tzinfo=UTC)).total_seconds() / 60
        for s in sessions
        if s.ended_at
    )

    # --- Current streak (consecutive days with a session, ending today/yesterday) ---
    completed_dates: set[date] = {s.started_at.date() for s in sessions}
    streak = 0
    check_date = now.date()
    # Allow streak if today or yesterday has a session
    if check_date not in completed_dates:
        check_date = check_date - timedelta(days=1)
    while check_date in completed_dates:
        streak += 1
        check_date -= timedelta(days=1)
    current_streak = streak

    # --- Per-section stability ---
    chunk_ids = [c.chunk_id for c in all_cards]
    per_section: list[SectionStabilityItem] = []
    if chunk_ids:
        chunk_stmt = (
            select(ChunkModel, SectionModel.heading)
            .outerjoin(SectionModel, ChunkModel.section_id == SectionModel.id)
            .where(ChunkModel.id.in_(chunk_ids))
        )
        chunk_rows = await db.execute(chunk_stmt)
        chunk_to_heading: dict[str, str | None] = {}
        for chunk, heading in chunk_rows:
            chunk_to_heading[chunk.id] = heading

        section_groups: dict[str | None, list[FlashcardModel]] = {}
        for c in all_cards:
            heading = chunk_to_heading.get(c.chunk_id)
            section_groups.setdefault(heading, []).append(c)

        for heading, group in section_groups.items():
            avg_stab = sum(c.fsrs_stability for c in group) / len(group)
            per_section.append(
                SectionStabilityItem(
                    section_heading=heading,
                    avg_stability=round(avg_stab, 4),
                    card_count=len(group),
                )
            )
        per_section.sort(key=lambda x: x.avg_stability)

    # --- All card stabilities ---
    all_card_stabilities = [
        CardStabilityItem(
            card_id=c.id,
            stability=round(c.fsrs_stability, 4),
            due_date=c.due_date.isoformat() if c.due_date else None,
        )
        for c in all_cards
    ]

    return StudyStatsResponse(
        total_cards=total_cards,
        cards_mastered=cards_mastered,
        avg_retention=avg_retention,
        current_streak=current_streak,
        total_study_time_minutes=round(total_study_time_minutes, 2),
        due_today=due_today,
        new_today=new_today,
        mastery_pct=mastery_pct,
        per_section_stability=per_section,
        all_card_stabilities=all_card_stabilities,
    )


@router.get("/history", response_model=list[DailyHistoryItem])
async def get_study_history(
    document_id: str | None = None,
    days: int = 90,
    tz_offset_minutes: int = Query(
        default=0,
        description=(
            "Client's timezone offset from UTC in minutes, matching JS "
            "`Date.getTimezoneOffset()` (positive west of UTC; PDT=420). "
            "Sessions are bucketed by the user's local date so a study "
            "session at 11pm local doesn't appear on the next day."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> list[DailyHistoryItem]:
    """Return daily study activity for the last N days, bucketed in local time."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    stmt = select(StudySessionModel).where(
        StudySessionModel.started_at >= cutoff,
        StudySessionModel.ended_at.is_not(None),
    )
    if document_id:
        stmt = stmt.where(StudySessionModel.document_id == document_id)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Group by local date: shift UTC -> client-local before taking .date()
    local_shift = timedelta(minutes=-tz_offset_minutes)
    daily: dict[date, dict] = {}
    for s in sessions:
        if not s.ended_at:
            continue
        d = (s.started_at + local_shift).date()
        if d not in daily:
            daily[d] = {"cards_reviewed": 0, "study_time_minutes": 0.0}
        daily[d]["cards_reviewed"] += s.cards_reviewed
        daily[d]["study_time_minutes"] += (s.ended_at - s.started_at).total_seconds() / 60

    return [
        DailyHistoryItem(
            date=d.isoformat(),
            cards_reviewed=v["cards_reviewed"],
            study_time_minutes=round(v["study_time_minutes"], 2),
        )
        for d, v in sorted(daily.items())
    ]


@router.get("/struggling", response_model=list[StrugglingCardItem])
async def get_struggling_cards(
    document_id: str | None = None,
    again_threshold: int = Query(default=3, ge=1),
    days: int = Query(default=14, ge=1, le=365),
    session: AsyncSession = Depends(get_db),
) -> list[StrugglingCardItem]:
    """Return flashcards rated 'again' at least again_threshold times in the last N days."""
    fsrs_svc = get_fsrs_service()
    rows = await fsrs_svc.get_struggling_cards(
        session=session,
        document_id=document_id,
        again_threshold=again_threshold,
        days=days,
    )
    return [StrugglingCardItem(**r) for r in rows]


_DECAY_DEBT_RETENTION_THRESHOLD = 0.80
_DECAY_DEBT_WINDOW_DAYS = 7
_DECAY_DEBT_LIMIT = 10


@router.get("/decay-debt", response_model=DecayDebtResponse)
async def get_decay_debt(
    limit: int = Query(default=_DECAY_DEBT_LIMIT, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> DecayDebtResponse:
    """Return documents whose flashcards are approaching the forgetting threshold.

    A card is 'at risk' when its estimated current retention R = e^(-t/S)
    drops below _DECAY_DEBT_RETENTION_THRESHOLD within the next
    _DECAY_DEBT_WINDOW_DAYS days. Results are grouped by document and sorted
    by avg_retention ascending (weakest first).
    """
    now = datetime.now(UTC)
    # Fetch all reviewed cards with enough data to compute retention.
    cards_result = await session.execute(
        select(
            FlashcardModel.id,
            FlashcardModel.document_id,
            FlashcardModel.fsrs_stability,
            FlashcardModel.due_date,
        ).where(
            FlashcardModel.document_id.is_not(None),
            FlashcardModel.fsrs_stability > 0,
            FlashcardModel.due_date.is_not(None),
        )
    )
    cards = cards_result.all()

    if not cards:
        return DecayDebtResponse(items=[], total_at_risk=0)

    # Collect at-risk card IDs grouped by document.
    doc_ids: list[str] = list({c[1] for c in cards})
    docs_result = await session.execute(
        select(DocumentModel.id, DocumentModel.title).where(
            DocumentModel.id.in_(doc_ids)
        )
    )
    doc_title_map: dict[str, str] = {r[0]: r[1] for r in docs_result.all()}

    # Group at-risk cards by document.
    from collections import defaultdict
    doc_cards: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for _card_id, doc_id, stability, due_date in cards:
        # days elapsed since the scheduled due date (positive = overdue)
        due_aware = due_date.replace(tzinfo=UTC) if due_date.tzinfo is None else due_date
        days_since_due = (now - due_aware).total_seconds() / 86400
        # stability is measured in days; retention at 'days_since_due' days past due
        current_retention = math.exp(-max(0.0, days_since_due) / stability)
        # R_target = e^(-t/S)  =>  t = -S * ln(R_target)
        days_to_threshold = (
            -stability * math.log(_DECAY_DEBT_RETENTION_THRESHOLD)
            - max(0.0, days_since_due)
        )
        at_risk = (
            current_retention < _DECAY_DEBT_RETENTION_THRESHOLD
            or days_to_threshold <= _DECAY_DEBT_WINDOW_DAYS
        )
        if at_risk:
            doc_cards[doc_id].append((current_retention, int(max(0, days_to_threshold))))

    if not doc_cards:
        return DecayDebtResponse(items=[], total_at_risk=0)

    items: list[DecayDebtItem] = []
    for doc_id, at_risk in doc_cards.items():
        avg_ret = sum(r for r, _ in at_risk) / len(at_risk)
        min_days = min(d for _, d in at_risk)
        items.append(
            DecayDebtItem(
                document_id=doc_id,
                document_title=doc_title_map.get(doc_id, "(unknown)"),
                card_count=len(at_risk),
                avg_retention=round(avg_ret, 3),
                due_within_days=min_days,
            )
        )

    items.sort(key=lambda x: x.avg_retention)
    total_at_risk = sum(i.card_count for i in items)
    return DecayDebtResponse(items=items[:limit], total_at_risk=total_at_risk)


@router.get("/misconception-stats", response_model=MisconceptionStatsResponse)
async def misconception_stats(
    session: AsyncSession = Depends(get_db),
) -> MisconceptionStatsResponse:
    return MisconceptionStatsResponse(**await get_misconception_stats(session))


@router.get("/calibration-stats", response_model=CalibrationStatsResponse)
async def get_calibration_stats(
    days: int = Query(default=30, ge=7, le=90),
    session: AsyncSession = Depends(get_db),
) -> CalibrationStatsResponse:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                ReviewEventModel.predicted_rating,
                ReviewEventModel.rating,
                ReviewEventModel.reviewed_at,
            ).where(
                ReviewEventModel.predicted_rating.is_not(None),
                ReviewEventModel.reviewed_at >= cutoff,
            )
        )
    ).all()

    if not rows:
        return CalibrationStatsResponse(overall_match_rate=None, total_predictions=0, weeks=[])

    from collections import defaultdict

    week_buckets: dict[str, list[bool]] = defaultdict(list)
    for predicted, actual, reviewed_at in rows:
        aware = reviewed_at.replace(tzinfo=UTC) if reviewed_at.tzinfo is None else reviewed_at
        monday = (aware - timedelta(days=aware.weekday())).date().isoformat()
        week_buckets[monday].append(predicted == actual)

    weeks: list[CalibrationWeekItem] = []
    for week_start in sorted(week_buckets):
        matches = week_buckets[week_start]
        matched = sum(matches)
        weeks.append(
            CalibrationWeekItem(
                week_start=week_start,
                total=len(matches),
                matched=matched,
                match_rate=round(matched / len(matches), 3),
            )
        )

    total = len(rows)
    overall_matched = sum(1 for p, a, _ in rows if p == a)
    return CalibrationStatsResponse(
        overall_match_rate=round(overall_matched / total, 3),
        total_predictions=total,
        weeks=weeks,
    )


@router.get("/section-heatmap", response_model=SectionHeatmapResponse)
async def get_section_heatmap(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> SectionHeatmapResponse:
    """Return per-section FSRS fragility scores for a document.

    fragility_score ranges from 0.0 (well-retained) to 1.0 (completely forgotten).
    Sections with no flashcards are absent from the heatmap dict.
    """
    # Two sequential reads: cards first (to get chunk_ids), then chunk→section mapping.
    # The chunk_ids set is only known after the card query, so the second read follows here.
    cards_result = await session.execute(
        select(FlashcardModel).where(FlashcardModel.document_id == document_id)
    )
    cards = list(cards_result.scalars().all())

    if not cards:
        return SectionHeatmapResponse(heatmap={})

    chunk_ids = [c.chunk_id for c in cards if c.chunk_id]
    chunk_to_section: dict[str, str | None] = {}
    if chunk_ids:
        chunk_rows = await session.execute(
            select(ChunkModel.id, ChunkModel.section_id).where(ChunkModel.id.in_(chunk_ids))
        )
        for chunk_id, section_id in chunk_rows:
            chunk_to_section[chunk_id] = section_id

    now = datetime.now(UTC)
    heatmap = _compute_section_heatmap(cards, chunk_to_section, now)
    logger.info(
        "section-heatmap: document_id=%s sections_with_cards=%d",
        document_id,
        len(heatmap),
    )
    return SectionHeatmapResponse(heatmap=heatmap)


# Study path endpoints




@router.get("/path", response_model=StudyPathAPIResponse)
async def get_study_path(
    document_id: str = Query(...),
    concept: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> StudyPathAPIResponse:
    """Return FSRS-aware prerequisite study path for a concept in a document.

    Path is ordered from earliest prerequisite to the requested concept.
    Each item includes mastery (0-1), skip flag (avg_stability >= 14 days),
    and reason string.

    Returns empty path (not 404) when the concept has no PREREQUISITE_OF edges.
    """
    svc = StudyPathService()
    result = await svc.get_study_path(document_id, concept, session)
    return StudyPathAPIResponse(
        concept=result["concept"],
        document_id=result["document_id"],
        path=[StudyPathItemResponse(**vars(item)) for item in result["path"]],
    )


@router.get("/start", response_model=StartConceptsAPIResponse)
async def get_start_concepts(
    document_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> StartConceptsAPIResponse:
    """Return up to 3 entry-point concepts for a document with highest learning ROI.

    Entry-point concepts are those with no unsatisfied prerequisites.
    Returns empty concepts list (not 404) when no PREREQUISITE_OF edges exist.
    """
    svc = StudyPathService()
    result = await svc.get_start_concepts(document_id, session)
    return StartConceptsAPIResponse(
        document_id=result["document_id"],
        concepts=[StartConceptItemResponse(**vars(item)) for item in result["concepts"]],
    )


async def _mark_teachback_error(tb_id: str) -> None:
    """Flag a teachback row as failed so the UI offers a retry."""
    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(TeachbackResultModel).where(TeachbackResultModel.id == tb_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.status = "error"
                await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to mark teachback %s as error", tb_id)


async def _evaluate_teachback_llm(prompt: str) -> dict | None:
    """Run the teachback evaluation, retrying once on an unparseable reply.

    Local models drop a malformed object often enough that a single bad
    completion should not cost the learner their score.
    """
    llm = get_llm_service()
    for attempt in (1, 2):
        raw = await llm.generate(prompt=prompt, system=_TEACHBACK_SYSTEM)
        parsed = _parse_teachback_response(raw)
        if parsed is not None:
            return parsed
        logger.warning("Teachback evaluation unparseable (attempt %d/2)", attempt)
    return None


def _string_list(value: object) -> list[str]:
    """Whatever the model put in a list-of-strings field, as a list of strings.

    Local models nest these: `misconceptions` came back as `[["a", "b"]]` on a
    real card, and nothing downstream survived it. The row's JSON column stored
    the nested list, and then `TeachbackResultItem` -- which declares
    `list[str]` -- failed validation, so GET /teachback/results answered 500.
    That is not one card losing its verdict: the panel polls every card of the
    run in one batch, so a single nested list took out the whole run's feedback.
    The misconception rows failed to insert separately, SQLite refusing to bind
    a list as `correction_note`.

    One level of nesting is flattened and scalars are stringified, because that
    is what the model meant. Empty strings are dropped. Nothing is invented: a
    field that holds nothing usable yields an empty list, which is what an
    evaluator that named no misconceptions is saying.
    """
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, list):
            out.extend(s for s in (str(i).strip() for i in item) if s)
        elif item is not None and not isinstance(item, dict):
            text = str(item).strip()
            if text:
                out.append(text)
    return out


def _parse_teachback_response(raw: str) -> dict | None:
    """Parse the teachback rubric from an LLM completion. None when unparseable.

    Never substitute a zero for a failed parse: the learner reads that as "you
    got nothing right", it drags the session average down, and _score_to_rating
    feeds it to FSRS as a failed card.

    The list fields are normalised here rather than at each use: this is the one
    place the model's output enters the system, and everything downstream --
    the response schema, the JSON columns, the misconception rows -- is typed
    for `list[str]`. See `_string_list`.
    """
    parsed = parse_llm_json_object(raw)
    if parsed is None:
        logger.warning("Failed to parse teachback JSON", extra={"raw": raw[:200]})
        return None
    # Overwrites any `score` the model volunteered unasked, which is the point:
    # the headline has to be a function of the breakdown printed under it.
    score = _score_from_dimensions(parsed)
    if score is None:
        logger.warning(
            "Teachback reply carried no usable dimensions", extra={"raw": raw[:200]}
        )
        return None
    parsed["score"] = score
    for field in ("correct_points", "missing_points", "misconceptions"):
        parsed[field] = _string_list(parsed.get(field))
    return parsed


async def _llm_correction_card_payload(
    card: FlashcardModel,
    misconception: str,
    source: str = "",
    *,
    background: bool = False,
) -> dict | None:
    """Run the LLM call for a correction flashcard -- no DB I/O.

    Split out from _generate_correction_flashcard so the LLM round-trip can
    happen OUTSIDE the SQLite write transaction. Holding the write lock during
    an LLM call starves concurrent HTTP inserts past the busy_timeout.

    `background` marks the call as work nobody is waiting for, which is true
    once the teach-back verdict is already on screen. The runtime serves one
    call at a time, so an unmarked call here holds the only slot against
    whatever the learner does next -- and what they do next may itself be
    waiting on the model. The sync /teachback endpoint passes False, because
    there the learner is holding an open request for this exact card.
    """
    llm = get_llm_service()
    prompt = _CORRECTION_USER_TMPL.format(
        source=source or "(the source passage could not be recovered)",
        misconception=misconception,
        question=card.question,
        answer=card.answer,
    )
    raw = await llm.generate(
        prompt=prompt, system=_CORRECTION_SYSTEM, background=background
    )
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse correction flashcard JSON")
        return None

    if not isinstance(data, dict):
        return None
    return data


async def _insert_correction_flashcard(
    card: FlashcardModel,
    payload: dict,
    session: AsyncSession,
    source: str = "",
) -> str | None:
    """Insert a correction flashcard row -- caller must have the LLM payload.

    Returns None when the card fails the same grounding gate every other card
    passes. This path used to ask for a `source_excerpt` while supplying no
    source, so the quote was invented by construction and went into the deck
    under a "Source" heading.
    """
    from app.services.flashcard_parsers import card_rejection, grounding_state  # noqa: PLC0415

    question = payload.get("question") or f"Correction: {card.question}"
    answer = payload.get("answer") or card.answer
    excerpt = str(payload.get("source_excerpt") or "").strip()
    verdict = card_rejection(question, answer, excerpt, source)
    if verdict:
        logger.info("teachback: dropped correction card (%s): %r", verdict[1], question[:80])
        return None

    new_id = str(uuid.uuid4())
    correction = FlashcardModel(
        id=new_id,
        document_id=card.document_id,
        chunk_id=card.chunk_id,
        question=question,
        answer=answer,
        source_excerpt=excerpt,
        grounding=grounding_state(excerpt, source),
        source_chunk_ids=card.source_chunk_ids,
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        due_date=datetime.now(UTC),
        reps=0,
        lapses=0,
    )
    # correction card persisted in caller's session; commit is caller's responsibility
    session.add(correction)
    # Without this the card exists but cannot be found: flashcard search reads the
    # FTS index, and a card that never enters it is invisible to every query.
    await _sync_flashcard_fts(correction, session)
    return new_id


async def _generate_correction_flashcard(
    card: FlashcardModel,
    misconception: str,
    session: AsyncSession,
) -> str | None:
    """LLM-generate and persist a correction flashcard.

    Kept for the sync /teachback endpoint which already runs outside the
    background semaphore path. New code should call the split helpers so the
    LLM call happens outside the DB transaction.
    """
    source = await _source_passage(card, session)
    payload = await _llm_correction_card_payload(card, misconception, source)
    if payload is None:
        return None
    return await _insert_correction_flashcard(card, payload, session, source)


# Lightweight session API (stateless start + review)


async def _get_due_for_session(document_id: str, session: AsyncSession) -> list[FlashcardModel]:
    """Return all due-or-new flashcards for a document, ordered by due_date."""
    now = datetime.now(UTC)
    stmt = (
        select(FlashcardModel)
        .where(
            FlashcardModel.document_id == document_id,
            or_(FlashcardModel.due_date <= now, FlashcardModel.due_date.is_(None)),
        )
        .order_by(FlashcardModel.due_date.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("/session/{document_id}/start", response_model=SessionStartResponse)
async def session_start(
    document_id: str,
    session: AsyncSession = Depends(get_db),
) -> SessionStartResponse:
    """Return the first due/new flashcard for a document and the total remaining count."""
    cards = await _get_due_for_session(document_id, session)
    if not cards:
        raise HTTPException(status_code=404, detail="No flashcards due for this document")
    first = cards[0]
    return SessionStartResponse(
        card_id=first.id,
        question=first.question,
        answer=first.answer,
        cards_remaining=len(cards),
    )


@router.post("/session/{document_id}/review", response_model=SessionReviewResponse)
async def session_review(
    document_id: str,
    req: SessionReviewRequest,
    session: AsyncSession = Depends(get_db),
) -> SessionReviewResponse:
    """Apply FSRS rating to a card, then return the next due card or done=true."""
    if req.rating not in _RATING_INT_MAP:
        raise HTTPException(status_code=422, detail="rating must be 1–4")
    rating_str = _RATING_INT_MAP[req.rating]

    fsrs_svc = get_fsrs_service()
    try:
        await fsrs_svc.schedule(req.card_id, rating_str, session)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    remaining = await _get_due_for_session(document_id, session)
    if not remaining:
        return SessionReviewResponse(done=True)
    first = remaining[0]
    return SessionReviewResponse(
        done=False,
        next_card=SessionCardResponse(
            card_id=first.id,
            question=first.question,
            answer=first.answer,
            cards_remaining=len(remaining),
        ),
    )


@router.get("/topics/{document_id}", response_model=DocumentTopicsResponse)
async def get_document_topics(
    document_id: str, session: AsyncSession = Depends(get_db)
) -> DocumentTopicsResponse:
    """A document's study topics from its authored structure (top-level headings, front/back-matter
    filtered out) -- or an LLM outline when heading detection is messy. Never an INDEX or publisher
    boilerplate."""
    data = await get_topic_service().document_topics(session, document_id)
    if data is None:
        raise HTTPException(status_code=404, detail="document not found")
    return DocumentTopicsResponse(**data)


@router.get("/sections/{document_id}", response_model=list[TopicItem])
async def get_document_sections(
    document_id: str,
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
) -> list[TopicItem]:
    """All real sub-sections of a document (junk filtered, searchable) for drill-down."""
    rows = await get_topic_service().document_sections(session, document_id, q=q, limit=limit)
    return [TopicItem(**r) for r in rows]
