"""GET /progress/summary -- every number defends itself, or reports that it cannot.

The reported defect: a fresh install with one 10-card session showed "90% mastery".
The page averaged `accuracy_pct` over recent sessions, so one session WAS the score.
`test_one_good_session_is_not_a_mastered_library` pins that scenario.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, FlashcardModel, ReviewEventModel


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory
    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _card(stability: float = 0.0, reps: int = 0, state: str = "new") -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=None,
        chunk_id=None,
        question="q",
        answer="a",
        source_excerpt="e",
        fsrs_stability=stability,
        fsrs_state=state,
        reps=reps,
    )


def _review(card_id: str, correct: bool, days_ago: int = 0) -> ReviewEventModel:
    return ReviewEventModel(
        id=str(uuid.uuid4()),
        session_id="s1",
        flashcard_id=card_id,
        rating="good" if correct else "again",
        is_correct=correct,
        reviewed_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago),
    )


async def _summary() -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/progress/summary")
        assert r.status_code == 200, r.text
        return r.json()


@pytest.mark.anyio
async def test_empty_library_reports_absent_not_zero(test_db):
    """The distinction the old page could not make: nothing measured vs measured zero."""
    body = await _summary()

    assert body["retention_30d"]["value"] is None
    assert body["mastery"]["value"] is None
    assert body["mature_cards"]["value"] is None
    # Counts of things that exist are genuinely zero, and say so.
    assert body["documents"]["value"] == 0
    assert body["notes"]["value"] == 0
    assert body["due_today"]["value"] == 0

    # Every absent metric explains itself rather than rendering a bare dash.
    for key in ("retention_30d", "mastery", "mature_cards"):
        assert body[key]["basis"], f"{key} gave no reason for being absent"
        assert body[key]["definition"]


@pytest.mark.anyio
async def test_one_good_session_is_not_a_mastered_library(test_db):
    """The reported bug. One 10-card session at 90% must not read as 90% mastery.

    Ten cards reviewed once sit at a day or two of FSRS stability, so mastery is
    absent (below the reviewed-card floor) or low -- never the session's score.
    """
    _, factory = test_db
    async with factory() as s:
        cards = [_card(stability=1.5, reps=1, state="review") for _ in range(10)]
        s.add_all(cards)
        await s.flush()
        for i, card in enumerate(cards):
            s.add(_review(card.id, correct=i < 9))  # 9 of 10 correct == 90%
        await s.commit()

    body = await _summary()

    # Retention is honest about the sample: 10 reviews is below the floor.
    assert body["retention_30d"]["value"] is None
    assert body["retention_30d"]["sample_size"] == 10

    # Mastery reads from stability, not from the session's accuracy.
    mastery = body["mastery"]["value"]
    assert mastery is not None, "10 reviewed cards should clear the mastery floor"
    assert mastery < 20.0, f"one session of 1.5-day cards read as {mastery}% mastery"

    # And nothing is mature after a single review.
    assert body["mature_cards"]["value"] == 0


@pytest.mark.anyio
async def test_retention_computes_once_the_sample_is_large_enough(test_db):
    """The floor is a floor, not a ceiling: past it, the number appears."""
    _, factory = test_db
    async with factory() as s:
        card = _card(stability=1.0, reps=1, state="review")
        s.add(card)
        await s.flush()
        for i in range(20):
            s.add(_review(card.id, correct=i < 15))  # 15/20 == 75%
        await s.commit()

    body = await _summary()
    assert body["retention_30d"]["value"] == pytest.approx(75.0)
    assert body["retention_30d"]["sample_size"] == 20


@pytest.mark.anyio
async def test_reviews_outside_the_window_do_not_count(test_db):
    _, factory = test_db
    async with factory() as s:
        card = _card(stability=1.0, reps=1, state="review")
        s.add(card)
        await s.flush()
        for _ in range(25):
            s.add(_review(card.id, correct=True, days_ago=45))
        await s.commit()

    body = await _summary()
    assert body["reviews_30d"]["value"] == 0
    assert body["retention_30d"]["value"] is None


@pytest.mark.anyio
async def test_mature_cards_counts_stability_not_reviews(test_db):
    """A card is mature at 21 days' stability, however many times it was seen."""
    _, factory = test_db
    async with factory() as s:
        s.add_all([_card(stability=25.0, reps=4, state="review") for _ in range(3)])
        s.add_all([_card(stability=20.9, reps=9, state="review") for _ in range(7)])
        await s.commit()

    body = await _summary()
    assert body["mature_cards"]["value"] == 3
    assert body["mature_cards"]["sample_size"] == 10


@pytest.mark.anyio
async def test_new_cards_do_not_drag_mastery_down(test_db):
    """A generated-but-unreviewed card has stability 0. It is not a mastery of zero."""
    _, factory = test_db
    async with factory() as s:
        s.add_all([_card(stability=21.0, reps=5, state="review") for _ in range(10)])
        s.add_all([_card(stability=0.0, reps=0, state="new") for _ in range(500)])
        await s.commit()

    body = await _summary()
    assert body["mastery"]["value"] == pytest.approx(100.0)
    assert body["mastery"]["sample_size"] == 10


@pytest.mark.anyio
async def test_documents_count_is_served_in_public_mode(test_db):
    """The shipped-build defect: this number came from a router `public` never mounts."""
    _, factory = test_db
    async with factory() as s:
        for i in range(3):
            s.add(
                DocumentModel(
                    id=str(uuid.uuid4()),
                    title=f"d{i}",
                    format="txt",
                    content_type="book",
                    word_count=1,
                    page_count=0,
                    file_path=f"/tmp/d{i}.txt",
                    stage="complete",
                    tags=[],
                )
            )
        await s.commit()

    body = await _summary()
    assert body["documents"]["value"] == 3


@pytest.mark.anyio
async def test_notes_timeline_groups_in_sql(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        for i in range(3):
            r = await c.post("/notes", json={"content": f"n{i}", "tags": [], "document_id": None})
            assert r.status_code == 201, r.text
        body = (await c.get("/progress/notes-timeline")).json()

    assert body["total_notes"] == 3
    assert len(body["points"]) == 1
    assert body["points"][0]["count"] == 3


@pytest.mark.anyio
async def test_time_on_luminary_is_absent_not_zero_before_anything_is_recorded(test_db):
    """"Nothing recorded" and "you spent zero minutes" are opposite statements.

    A zero here would be the same defect this whole contract exists to prevent,
    on the one metric a reader is most likely to check on day one.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/progress/summary")).json()

    metric = body["time_on_luminary"]
    assert metric["value"] is None
    assert metric["basis"].strip()
    # Named for what it measures. "Time studied" would be a claim about
    # attention that the sampling cannot support.
    assert "attention" in metric["definition"].lower()


@pytest.mark.anyio
async def test_time_on_luminary_reports_the_minutes_actually_recorded(test_db):
    _, factory = test_db
    from app.models import TimeOnTaskModel

    async with factory() as s:
        s.add(
            TimeOnTaskModel(
                id=str(uuid.uuid4()),
                activity="document",
                member_id="doc-1",
                started_at=datetime.now(UTC).replace(tzinfo=None),
                last_beat_at=datetime.now(UTC).replace(tzinfo=None),
                seconds=600,
            )
        )
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/progress/summary")).json()

    assert body["time_on_luminary"]["value"] == 10.0
    assert body["time_on_luminary"]["unit"] == "minutes"


@pytest.mark.anyio
async def test_active_days_counts_days_that_carry_an_observation(test_db):
    """One day with work in it is one active day, however many rows it holds."""
    _, factory = test_db
    from app.models import TimeOnTaskModel

    now = datetime.now(UTC).replace(tzinfo=None)
    async with factory() as s:
        for _ in range(3):
            s.add(
                TimeOnTaskModel(
                    id=str(uuid.uuid4()),
                    activity="note",
                    member_id=None,
                    started_at=now,
                    last_beat_at=now,
                    seconds=60,
                )
            )
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/progress/summary")).json()

    assert body["active_days"]["value"] == 1.0
    assert body["active_days"]["unit"] == "days"


@pytest.mark.anyio
async def test_a_sub_minute_recording_says_so_rather_than_reading_as_nothing(test_db):
    """20s rounds to 0 minutes, which on screen looks like nothing recorded.

    The value stays truthful to its unit; the basis is what distinguishes
    "measured, under a minute" from "measured nothing".
    """
    _, factory = test_db
    from app.models import TimeOnTaskModel

    now = datetime.now(UTC).replace(tzinfo=None)
    async with factory() as s:
        s.add(
            TimeOnTaskModel(
                id=str(uuid.uuid4()),
                activity="document",
                member_id="doc-1",
                started_at=now,
                last_beat_at=now,
                seconds=20,
            )
        )
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        metric = (await c.get("/progress/summary")).json()["time_on_luminary"]

    assert metric["value"] == 0.0, "0 minutes is the truthful rounding of 20 seconds"
    assert metric["value"] is not None, "measured-but-small is not absent"
    assert "20s" in metric["basis"], f"basis hides the measurement: {metric['basis']!r}"
    assert metric["sample_size"] == 20


@pytest.mark.anyio
async def test_a_small_slice_of_a_large_week_keeps_its_own_unit(test_db):
    """Brackets the rule above: the unit belongs to the value it labels.

    Choosing it from the weekly total instead prints "review 0m" beside a
    40-minute week -- the same "looks like nothing recorded" the sub-minute
    case exists to prevent, reintroduced one level down in the basis string.
    """
    _, factory = test_db
    from app.models import TimeOnTaskModel

    now = datetime.now(UTC).replace(tzinfo=None)
    async with factory() as s:
        for activity, seconds in (("document", 2400), ("review", 30)):
            s.add(
                TimeOnTaskModel(
                    id=str(uuid.uuid4()),
                    activity=activity,
                    member_id=f"{activity}-1",
                    started_at=now,
                    last_beat_at=now,
                    seconds=seconds,
                )
            )
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        metric = (await c.get("/progress/summary")).json()["time_on_luminary"]

    assert "review 30s" in metric["basis"], f"slice lost its unit: {metric['basis']!r}"
    assert "document 40m" in metric["basis"], f"total lost its unit: {metric['basis']!r}"
