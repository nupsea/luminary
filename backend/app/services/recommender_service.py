import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RecommendationFeedbackModel
from app.repos.recommendation_repo import RecommendationRepo
from app.schemas.home import Recommendation, RecommendationReason, TodayAction

logger = logging.getLogger(__name__)

RECOMMENDATION_LIMIT = 4

# scoring weights -- deliberately module constants, not settings; tune via tests
# and real use (docs/recommender-spec.md)
_W_URGENCY = 0.40
_W_IMPACT = 0.35
_W_RECENCY = 0.25
_W_FATIGUE = 0.15

_MASTERY_FLOOR = 0.5
_BAD_REVIEW_DAYS = 14
_MIN_BAD_REVIEWS = 2
_CALIBRATION_DAYS = 30
_MIN_OVERCONFIDENT = 2
_STALLED_MIN_DAYS = 7
_STALLED_MAX_DAYS = 45
_FATIGUE_SATURATION_SHOWS = 5
# cap per generator so one signal family cannot flood the whole stack
_MAX_PER_KIND = 2

_ERROR_TYPE_IMPACT = {
    "misconception": 1.0,
    "incomplete": 0.7,
    "memory_lapse": 0.5,
    "unrelated": 0.3,
}

_TODAY_KIND = {
    "overdue_reviews": "review_cards",
    "stalled_reading": "continue_reading",
    "weak_concept": "drill_concept",
    "open_misconception": "fix_misconception",
    "calibration_blind_spot": "confidence_check",
}


@dataclass
class _Candidate:
    kind: str
    target_type: str
    target_ref: str
    label: str
    urgency: float
    impact: float
    recency: float
    reasons: list[RecommendationReason] = field(default_factory=list)
    # newest event backing this candidate; evidence newer than a dismissal re-arms it
    evidence_at: datetime | None = None
    count: int | None = None
    document_id: str | None = None
    concept_slug: str | None = None


def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _as_naive(value) -> datetime | None:
    # raw text() rows return DATETIME expressions as ISO strings on aiosqlite
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=None) if value.tzinfo else value


def _age_days(dt: datetime | None) -> float:
    if dt is None:
        return 0.0
    return max(0.0, (_naive_now() - dt).total_seconds() / 86400)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


async def _overdue_reviews(session: AsyncSession) -> list[_Candidate]:
    row = await RecommendationRepo(session).due_cards()
    count = int(row[0] or 0) if row else 0
    if count == 0:
        return []
    oldest_days = int(_age_days(_as_naive(row[1])))
    detail = f"{count} {'card' if count == 1 else 'cards'} due"
    if oldest_days > 0:
        detail += f", oldest {oldest_days} {'day' if oldest_days == 1 else 'days'} overdue"
    return [
        _Candidate(
            kind="overdue_reviews",
            target_type="study",
            target_ref="daily",
            label=f"Review {count} {'card' if count == 1 else 'cards'} due",
            urgency=_clamp(0.5 + oldest_days / 7),
            impact=_clamp(count / 20),
            recency=1.0,
            reasons=[RecommendationReason(signal="due_cards", detail=detail)],
            evidence_at=_as_naive(row[2]),
            count=count,
        )
    ]


async def _weak_concepts(session: AsyncSession) -> list[_Candidate]:
    rows = await RecommendationRepo(session).weak_concepts(
        _BAD_REVIEW_DAYS, _MASTERY_FLOOR, _MIN_BAD_REVIEWS, _MAX_PER_KIND
    )
    out: list[_Candidate] = []
    for slug, label, mastery, bad_count, last_bad in rows:
        last_bad_dt = _as_naive(last_bad)
        out.append(
            _Candidate(
                kind="weak_concept",
                target_type="concept",
                target_ref=slug,
                label=f"Shore up: {label}",
                urgency=_clamp(bad_count / 5),
                impact=_clamp(1.0 - float(mastery or 0.0)),
                recency=_clamp(1.0 - _age_days(last_bad_dt) / _BAD_REVIEW_DAYS),
                reasons=[
                    RecommendationReason(
                        signal="struggling_reviews",
                        detail=(
                            f"{bad_count} {'review' if bad_count == 1 else 'reviews'} rated "
                            f"again/hard in the last {_BAD_REVIEW_DAYS} days; "
                            f"mastery {int(float(mastery or 0.0) * 100)}%"
                        ),
                    )
                ],
                evidence_at=last_bad_dt,
                concept_slug=slug,
            )
        )
    return out


async def _open_misconceptions(session: AsyncSession) -> list[_Candidate]:
    rows = await RecommendationRepo(session).open_misconceptions(10)
    out: list[_Candidate] = []
    seen: set[str] = set()
    for card_id, error_type, note, detected_at, slug, doc_id, question, concept_label in rows:
        if card_id in seen:
            continue
        seen.add(card_id)
        detected_dt = _as_naive(detected_at)
        age = int(_age_days(detected_dt))
        topic = concept_label or (question or "")[:60]
        out.append(
            _Candidate(
                kind="open_misconception",
                target_type="flashcard",
                target_ref=card_id,
                label=f"Fix a misconception: {topic}",
                urgency=_clamp(age / 14),
                impact=_ERROR_TYPE_IMPACT.get(error_type, 0.7),
                recency=0.5,
                reasons=[
                    RecommendationReason(
                        signal="open_misconception",
                        detail=(
                            f"{error_type} recorded "
                            f"{age} {'day' if age == 1 else 'days'} ago: "
                            f'"{(note or "").strip()[:90]}"'
                        ),
                    )
                ],
                evidence_at=detected_dt,
                document_id=doc_id,
                concept_slug=slug,
            )
        )
        if len(out) >= _MAX_PER_KIND:
            break
    return out


async def _calibration_blind_spots(session: AsyncSession) -> list[_Candidate]:
    rows = await RecommendationRepo(session).overconfident_concepts(
        _CALIBRATION_DAYS, _MIN_OVERCONFIDENT, _MAX_PER_KIND
    )
    out: list[_Candidate] = []
    for slug, label, n, last_evt in rows:
        last_evt_dt = _as_naive(last_evt)
        out.append(
            _Candidate(
                kind="calibration_blind_spot",
                target_type="concept",
                target_ref=slug,
                label=f"Confidence check: {label}",
                urgency=_clamp(n / 4),
                impact=0.8,
                recency=_clamp(1.0 - _age_days(last_evt_dt) / _CALIBRATION_DAYS),
                reasons=[
                    RecommendationReason(
                        signal="overconfidence",
                        detail=(
                            f"predicted good/easy but rated again {n} times "
                            f"in the last {_CALIBRATION_DAYS} days"
                        ),
                    )
                ],
                evidence_at=last_evt_dt,
                concept_slug=slug,
            )
        )
    return out


async def _stalled_reading(session: AsyncSession) -> list[_Candidate]:
    rows = await RecommendationRepo(session).stalled_documents(
        _STALLED_MIN_DAYS, _STALLED_MAX_DAYS, 10
    )
    out: list[_Candidate] = []
    for doc_id, title, last_at, total_raw, read_raw in rows:
        total = int(total_raw or 0)
        read = int(read_raw or 0)
        if total <= 0 or read <= 0 or read >= total:
            continue
        last_at_dt = _as_naive(last_at)
        days = int(_age_days(last_at_dt))
        pct = read / total
        out.append(
            _Candidate(
                kind="stalled_reading",
                target_type="document",
                target_ref=doc_id,
                label=f"Pick back up: {title or '(untitled)'}",
                urgency=_clamp(days / 21),
                impact=_clamp(pct),
                recency=_clamp(1.0 - days / _STALLED_MAX_DAYS),
                reasons=[
                    RecommendationReason(
                        signal="stalled_reading",
                        detail=f"{int(pct * 100)}% read, untouched for {days} days",
                    )
                ],
                evidence_at=last_at_dt,
                document_id=doc_id,
            )
        )
        if len(out) >= _MAX_PER_KIND:
            break
    return out


_GENERATORS = (
    _overdue_reviews,
    _weak_concepts,
    _open_misconceptions,
    _calibration_blind_spots,
    _stalled_reading,
)


async def _load_feedback(
    session: AsyncSession,
) -> dict[tuple[str, str, str], RecommendationFeedbackModel]:
    rows = await RecommendationRepo(session).feedback()
    return {(r.kind, r.target_type, r.target_ref): r for r in rows}


def _score(cand: _Candidate, fb: RecommendationFeedbackModel | None) -> float:
    fatigue = 0.0
    if fb is not None and fb.acted_at is None:
        fatigue = _clamp((fb.shown_count or 0) / _FATIGUE_SATURATION_SHOWS)
    return (
        _W_URGENCY * cand.urgency
        + _W_IMPACT * cand.impact
        + _W_RECENCY * cand.recency
        - _W_FATIGUE * fatigue
    )


def _dismissal_active(cand: _Candidate, fb: RecommendationFeedbackModel | None) -> bool:
    if fb is None or fb.dismissed_at is None:
        return False
    if cand.evidence_at is None:
        return True
    return _as_naive(fb.dismissed_at) >= cand.evidence_at


async def get_recommendations(
    session: AsyncSession, limit: int = RECOMMENDATION_LIMIT
) -> list[Recommendation]:
    candidates: list[_Candidate] = []
    # sequential on the one request session (I-1) -- never asyncio.gather here
    for gen in _GENERATORS:
        try:
            candidates.extend(await gen(session))
        except Exception:  # noqa: BLE001 -- one bad generator must not blank the hub
            logger.warning("recommendation generator %s failed", gen.__name__, exc_info=True)
    if not candidates:
        return []

    feedback = await _load_feedback(session)
    scored = [
        (_score(c, feedback.get((c.kind, c.target_type, c.target_ref))), c)
        for c in candidates
        if not _dismissal_active(c, feedback.get((c.kind, c.target_type, c.target_ref)))
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    now = _naive_now()
    out: list[Recommendation] = []
    for score, cand in scored[:limit]:
        fb = feedback.get((cand.kind, cand.target_type, cand.target_ref))
        if fb is None:
            fb = RecommendationFeedbackModel(
                id=str(uuid.uuid4()),
                kind=cand.kind,
                target_type=cand.target_type,
                target_ref=cand.target_ref,
            )
            session.add(fb)
        fb.shown_count = (fb.shown_count or 0) + 1
        fb.last_shown_at = now
        out.append(
            Recommendation(
                id=fb.id,
                kind=cand.kind,
                target_type=cand.target_type,
                target_ref=cand.target_ref,
                label=cand.label,
                score=round(score, 4),
                reasons=cand.reasons,
                count=cand.count,
                document_id=cand.document_id,
                concept_slug=cand.concept_slug,
            )
        )
    await session.commit()
    return out


def to_today_action(rec: Recommendation) -> TodayAction:
    kind = _TODAY_KIND[rec.kind]
    if kind == "continue_reading":
        target_id = rec.document_id or rec.target_ref
    elif kind == "fix_misconception":
        target_id = rec.concept_slug
    else:
        target_id = rec.target_ref
    return TodayAction(
        kind=kind,
        target_id=target_id,
        label=rec.label,
        count=rec.count,
        reasons=rec.reasons,
        recommendation_id=rec.id,
        document_id=rec.document_id,
    )


async def mark_dismissed(session: AsyncSession, feedback_id: str) -> bool:
    row = await session.get(RecommendationFeedbackModel, feedback_id)
    if row is None:
        return False
    row.dismissed_at = _naive_now()
    await session.commit()
    return True


async def mark_acted(session: AsyncSession, feedback_id: str) -> bool:
    row = await session.get(RecommendationFeedbackModel, feedback_id)
    if row is None:
        return False
    row.acted_at = _naive_now()
    await session.commit()
    return True
