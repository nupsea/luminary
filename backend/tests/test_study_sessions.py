"""Tests for GET /study/sessions and GET /study/sessions/{id}/cards endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import FlashcardModel, ReviewEventModel, StudySessionModel

pytestmark = pytest.mark.usefixtures("card_documents")

# Test DB fixture


# Helpers


def _make_session(
    doc_id: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    cards_reviewed: int = 5,
    cards_correct: int = 4,
    accuracy_pct: float | None = None,
) -> StudySessionModel:
    now = datetime.now(UTC)
    return StudySessionModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        started_at=started_at or now,
        ended_at=ended_at or (started_at or now) + timedelta(minutes=15),
        cards_reviewed=cards_reviewed,
        cards_correct=cards_correct,
        accuracy_pct=accuracy_pct,
        mode="flashcard",
    )


def _make_card(doc_id: str) -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        chunk_id=str(uuid.uuid4()),
        question="What is the capital of France?",
        answer="Paris.",
        source_excerpt="Excerpt.",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=3.0,
        due_date=now,
        reps=0,
        lapses=0,
        created_at=now,
    )


def _make_review_event(
    session_id: str,
    flashcard_id: str,
    rating: str = "good",
    is_correct: bool = True,
) -> ReviewEventModel:
    return ReviewEventModel(
        id=str(uuid.uuid4()),
        session_id=session_id,
        flashcard_id=flashcard_id,
        rating=rating,
        is_correct=is_correct,
        reviewed_at=datetime.now(UTC),
    )


# GET /study/sessions


@pytest.mark.asyncio
async def test_list_sessions_empty(test_db):
    """Returns empty list with total=0 when no sessions exist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/sessions")

    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 20


@pytest.mark.asyncio
async def test_list_sessions_pagination(test_db):
    """Returns page_size items with correct total when there are more sessions."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    async with factory() as session:
        for i in range(5):
            session.add(_make_session(doc_id=doc_id, started_at=now - timedelta(hours=i)))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/sessions?page=1&page_size=2")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2


@pytest.mark.asyncio
async def test_list_sessions_sorted_desc(test_db):
    """Sessions are returned newest first."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    t_old = now - timedelta(hours=5)
    t_new = now - timedelta(hours=1)

    async with factory() as session:
        session.add(_make_session(doc_id=doc_id, started_at=t_old))
        session.add(_make_session(doc_id=doc_id, started_at=t_new))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/sessions")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    # First item should be the more recent one
    assert items[0]["started_at"] > items[1]["started_at"]


@pytest.mark.asyncio
async def test_list_sessions_document_filter(test_db):
    """document_id query param filters sessions by document."""
    _, factory, _ = test_db
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())

    async with factory() as session:
        session.add(_make_session(doc_id=doc_a))
        session.add(_make_session(doc_id=doc_a))
        session.add(_make_session(doc_id=doc_b))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/sessions?document_id={doc_a}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(item["document_id"] == doc_a for item in data["items"])


@pytest.mark.asyncio
async def test_list_sessions_accuracy_pct(test_db):
    """end_session stores accuracy_pct; GET /study/sessions returns it."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    # Create session with accuracy_pct already computed (simulates end_session result)
    async with factory() as session:
        session.add(
            _make_session(
                doc_id=doc_id,
                cards_reviewed=10,
                cards_correct=7,
                accuracy_pct=70.0,
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/study/sessions")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["accuracy_pct"] == 70.0
    assert items[0]["cards_reviewed"] == 10
    assert items[0]["cards_correct"] == 7


# GET /study/sessions/{session_id}/cards


@pytest.mark.asyncio
async def test_session_cards_returns_review_events(test_db):
    """GET /study/sessions/{id}/cards returns one entry per review event."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        card1 = _make_card(doc_id)
        card2 = _make_card(doc_id)
        sess = _make_session(doc_id=doc_id)
        session.add(card1)
        session.add(card2)
        session.add(sess)
        await session.flush()

        session.add(_make_review_event(sess.id, card1.id, rating="good", is_correct=True))
        session.add(_make_review_event(sess.id, card2.id, rating="again", is_correct=False))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/sessions/{sess.id}/cards")

    assert resp.status_code == 200
    cards = resp.json()
    assert len(cards) == 2
    assert all("answer" in c and c["answer"] is not None for c in cards)
    ratings = {c["rating"] for c in cards}
    assert ratings == {"good", "again"}
    correct_flags = {c["flashcard_id"]: c["is_correct"] for c in cards}
    assert correct_flags[card1.id] is True
    assert correct_flags[card2.id] is False


@pytest.mark.asyncio
async def test_session_cards_404_unknown_session(test_db):
    """GET /study/sessions/{id}/cards returns 404 for unknown session_id."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/sessions/{uuid.uuid4()}/cards")

    assert resp.status_code == 404


# DELETE /study/sessions/{id}?if_unused=true


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", [None, "review", "pending_teachback"])
async def test_discard_if_unused_keeps_any_run_with_an_attempt(test_db, attempt):
    """A run left without an answer is discarded; one holding a review, or a teach-back
    still being graded, is kept. The empty one sat in history beside the real run."""
    from app.models import TeachbackResultModel

    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    sess = _make_session(doc_id=doc_id, cards_reviewed=0, cards_correct=0)
    sess.ended_at = None
    card = _make_card(doc_id)
    async with factory() as session:
        session.add_all([sess, card])
        if attempt == "review":
            session.add(_make_review_event(sess.id, card.id))
        elif attempt == "pending_teachback":
            session.add(
                TeachbackResultModel(
                    id=str(uuid.uuid4()),
                    flashcard_id=card.id,
                    user_explanation="Mostly with her mother.",
                    score=0,
                    status="pending",
                    session_id=sess.id,
                )
            )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/study/sessions/{sess.id}", params={"if_unused": "true"})
        listed = await client.get("/study/sessions")

    assert resp.status_code == 204
    ids = {item["id"] for item in listed.json()["items"]}
    assert (sess.id in ids) is (attempt is not None)


@pytest.mark.asyncio
async def test_list_sessions_filters_and_labels(test_db):
    """mode, status and collection filters; titles, names and pending flags on each row."""
    from app.models import CollectionModel, DocumentModel, TeachbackResultModel

    _, factory, _ = test_db
    now = datetime.now(UTC)
    flash_done = _make_session(doc_id="doc_t", started_at=now - timedelta(hours=3))
    teach_open = _make_session(started_at=now - timedelta(hours=2))
    teach_open.mode, teach_open.ended_at, teach_open.collection_id = "teachback", None, "col"
    teach_done = _make_session(started_at=now - timedelta(hours=1))
    teach_done.mode, teach_done.collection_id = "teachback", "col"
    async with factory() as session:
        session.add_all([flash_done, teach_open, teach_done])
        session.add(
            DocumentModel(
                id="doc_t",
                title="The Doc",
                format="txt",
                content_type="book",
                word_count=1,
                page_count=0,
                file_path="/tmp/x.txt",
                stage="complete",
            )
        )
        session.add(CollectionModel(id="col", name="The Collection"))
        session.add(
            TeachbackResultModel(
                id=str(uuid.uuid4()),
                session_id=teach_open.id,
                flashcard_id="c",
                user_explanation="e",
                score=0,
                status="pending",
            )
        )
        await session.commit()

    async def ids(query: str) -> list[str]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/study/sessions{query}")
        assert resp.status_code == 200
        return [item["id"] for item in resp.json()["items"]]

    assert await ids("?mode=teachback") == [teach_done.id, teach_open.id]
    assert await ids("?status=incomplete") == [teach_open.id]
    assert await ids("?status=complete") == [teach_done.id, flash_done.id]
    assert await ids("?collection_id=col&status=complete") == [teach_done.id]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        items = {i["id"]: i for i in (await c.get("/study/sessions")).json()["items"]}
    assert items[flash_done.id]["document_title"] == "The Doc"
    assert items[flash_done.id]["collection_name"] is None
    assert items[teach_open.id]["collection_name"] == "The Collection"
    assert items[teach_open.id]["duration_minutes"] is None
    assert items[teach_done.id]["duration_minutes"] == 15.0
    assert [i for i in items if items[i]["has_pending_evaluations"]] == [teach_open.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["cards", "remaining-cards"])
async def test_session_card_reads_404_for_a_missing_session(test_db, path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/study/sessions/nope/{path}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Session not found"
