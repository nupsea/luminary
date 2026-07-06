from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import (
    ConceptModel,
    ContentActivityModel,
    DocumentModel,
    FlashcardModel,
    MisconceptionModel,
    ReadingProgressModel,
    RecommendationFeedbackModel,
    ReviewEventModel,
    SectionModel,
)
from app.services import recommender_service as svc


@pytest.fixture
async def session_factory():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _naive(days_ago: float = 0.0) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)


def _card(card_id: str, *, slug: str | None = None, due_days_ago: float | None = None):
    return FlashcardModel(
        id=card_id,
        question="q",
        answer="a",
        source_excerpt="s",
        concept_slug=slug,
        due_date=_naive(due_days_ago) if due_days_ago is not None else None,
        document_id="doc-1",
    )


def _concept(slug: str, mastery: float, *, status: str = "confirmed", kind: str = "concept"):
    return ConceptModel(
        id=str(uuid.uuid4()), slug=slug, label=slug.replace("-", " "),
        mastery=mastery, status=status, kind=kind,
    )


def _review(card_id: str, rating: str, *, days_ago: float = 1.0, predicted: str | None = None):
    return ReviewEventModel(
        id=str(uuid.uuid4()),
        session_id="sess-1",
        flashcard_id=card_id,
        rating=rating,
        is_correct=rating != "again",
        reviewed_at=_naive(days_ago),
        predicted_rating=predicted,
    )


def _misconception(card_id: str, *, days_ago: float = 3.0, status: str = "open"):
    return MisconceptionModel(
        id=str(uuid.uuid4()),
        document_id="doc-1",
        flashcard_id=card_id,
        user_answer="wrong",
        error_type="misconception",
        correction_note="actually it works the other way",
        detected_at=_naive(days_ago),
        status=status,
    )


def _stalled_doc(doc_id: str, *, days_ago: float, read: int, total: int):
    rows = [
        DocumentModel(id=doc_id, title="Stalled Book", format="txt",
                      content_type="book", file_path="/x"),
        ContentActivityModel(member_type="document", member_id=doc_id,
                             last_meaningful_at=_naive(days_ago)),
    ]
    rows += [
        SectionModel(id=f"{doc_id}-s{i}", document_id=doc_id, heading=f"h{i}",
                     level=1, section_order=i)
        for i in range(total)
    ]
    rows += [
        ReadingProgressModel(id=f"{doc_id}-rp{i}", document_id=doc_id,
                             section_id=f"{doc_id}-s{i}")
        for i in range(read)
    ]
    return rows


@pytest.mark.asyncio
async def test_overdue_reviews_candidate(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card("c1", due_days_ago=3))
        session.add(_card("c2", due_days_ago=0.5))
        await session.commit()

        recs = await svc.get_recommendations(session)
        assert [r.kind for r in recs] == ["overdue_reviews"]
        assert recs[0].count == 2
        assert recs[0].target_type == "study"
        assert "2 cards due" in recs[0].reasons[0].detail


@pytest.mark.asyncio
async def test_weak_concept_needs_recent_bad_reviews_and_low_mastery(session_factory) -> None:
    async with session_factory() as session:
        session.add(_concept("btree-splits", 0.2))
        session.add(_concept("mastered-thing", 0.9))
        session.add(_card("c1", slug="btree-splits"))
        session.add(_card("c2", slug="mastered-thing"))
        session.add_all([_review("c1", "again"), _review("c1", "hard")])
        session.add_all([_review("c2", "again"), _review("c2", "again")])
        await session.commit()

        recs = await svc.get_recommendations(session)
        kinds = {(r.kind, r.target_ref) for r in recs}
        assert ("weak_concept", "btree-splits") in kinds
        assert ("weak_concept", "mastered-thing") not in kinds
        weak = next(r for r in recs if r.kind == "weak_concept")
        assert "2 reviews rated again/hard" in weak.reasons[0].detail
        assert "mastery 20%" in weak.reasons[0].detail


@pytest.mark.asyncio
async def test_weak_concept_ignores_junk_and_single_lapse(session_factory) -> None:
    async with session_factory() as session:
        session.add(_concept("junk-thing", 0.1, status="candidate"))
        session.add(_concept("one-lapse", 0.1))
        session.add(_card("c1", slug="junk-thing"))
        session.add(_card("c2", slug="one-lapse"))
        session.add_all([_review("c1", "again"), _review("c1", "again")])
        session.add(_review("c2", "again"))
        await session.commit()

        recs = await svc.get_recommendations(session)
        assert all(r.kind != "weak_concept" for r in recs)


@pytest.mark.asyncio
async def test_open_misconception_candidate_and_resolved_excluded(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card("c1"))
        session.add(_card("c2"))
        session.add(_misconception("c1", days_ago=5))
        session.add(_misconception("c2", status="resolved"))
        await session.commit()

        recs = await svc.get_recommendations(session)
        miscon = [r for r in recs if r.kind == "open_misconception"]
        assert [r.target_ref for r in miscon] == ["c1"]
        assert miscon[0].document_id == "doc-1"
        assert "actually it works the other way" in miscon[0].reasons[0].detail


@pytest.mark.asyncio
async def test_calibration_blind_spot_requires_confident_misses(session_factory) -> None:
    async with session_factory() as session:
        session.add(_concept("raft-elections", 0.7))
        session.add(_card("c1", slug="raft-elections"))
        session.add_all(
            [
                _review("c1", "again", predicted="good"),
                _review("c1", "again", predicted="easy"),
                _review("c1", "again", predicted="hard"),
            ]
        )
        await session.commit()

        recs = await svc.get_recommendations(session)
        cal = [r for r in recs if r.kind == "calibration_blind_spot"]
        assert [r.target_ref for r in cal] == ["raft-elections"]
        assert "2 times" in cal[0].reasons[0].detail


@pytest.mark.asyncio
async def test_stalled_reading_candidate(session_factory) -> None:
    async with session_factory() as session:
        session.add_all(_stalled_doc("doc-stall", days_ago=10, read=4, total=10))
        session.add_all(_stalled_doc("doc-warm", days_ago=2, read=4, total=10))
        session.add_all(_stalled_doc("doc-done", days_ago=10, read=5, total=5))
        await session.commit()

        recs = await svc.get_recommendations(session)
        stalled = [r for r in recs if r.kind == "stalled_reading"]
        assert [r.target_ref for r in stalled] == ["doc-stall"]
        assert "40% read" in stalled[0].reasons[0].detail


@pytest.mark.asyncio
async def test_overdue_outranks_stalled_reading(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card("c1", due_days_ago=5))
        session.add_all(_stalled_doc("doc-stall", days_ago=10, read=2, total=10))
        await session.commit()

        recs = await svc.get_recommendations(session)
        assert recs[0].kind == "overdue_reviews"
        assert {r.kind for r in recs} == {"overdue_reviews", "stalled_reading"}


@pytest.mark.asyncio
async def test_shown_feedback_upserted_and_incremented(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card("c1", due_days_ago=1))
        await session.commit()

        first = await svc.get_recommendations(session)
        second = await svc.get_recommendations(session)
        assert first[0].id == second[0].id

        rows = (await session.execute(select(RecommendationFeedbackModel))).scalars().all()
        assert len(rows) == 1
        assert rows[0].shown_count == 2
        assert rows[0].last_shown_at is not None


@pytest.mark.asyncio
async def test_dismissal_hides_until_new_evidence(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card("c1", due_days_ago=1))
        await session.commit()

        recs = await svc.get_recommendations(session)
        assert await svc.mark_dismissed(session, recs[0].id)
        assert await svc.get_recommendations(session) == []

        # evidence newer than the dismissal re-arms the candidate: backdate the
        # dismissal so the standing due-card evidence postdates it
        fb = await session.get(RecommendationFeedbackModel, recs[0].id)
        fb.dismissed_at = _naive(days_ago=2)
        await session.commit()
        rearmed = await svc.get_recommendations(session)
        assert [r.kind for r in rearmed] == ["overdue_reviews"]


@pytest.mark.asyncio
async def test_fatigue_penalizes_repeatedly_ignored(session_factory) -> None:
    async with session_factory() as session:
        session.add(_card("c1", due_days_ago=1))
        await session.commit()

        baseline = (await svc.get_recommendations(session))[0].score
        for _ in range(5):
            await svc.get_recommendations(session)
        fatigued = (await svc.get_recommendations(session))[0].score
        assert fatigued < baseline

        # acting on it clears the fatigue penalty
        rec_id = (await svc.get_recommendations(session))[0].id
        assert await svc.mark_acted(session, rec_id)
        after_acted = (await svc.get_recommendations(session))[0].score
        assert after_acted > fatigued


@pytest.mark.asyncio
async def test_to_today_action_mapping(session_factory) -> None:
    async with session_factory() as session:
        session.add(_concept("btree-splits", 0.2))
        session.add(_card("c1", slug="btree-splits"))
        session.add_all([_review("c1", "again"), _review("c1", "hard")])
        await session.commit()

        recs = await svc.get_recommendations(session)
        action = svc.to_today_action(recs[0])
        assert action.kind == "drill_concept"
        assert action.target_id == "btree-splits"
        assert action.recommendation_id == recs[0].id
        assert action.reasons == recs[0].reasons


@pytest.mark.asyncio
async def test_empty_database_yields_no_recommendations(session_factory) -> None:
    async with session_factory() as session:
        assert await svc.get_recommendations(session) == []
