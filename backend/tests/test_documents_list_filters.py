"""SQL pushdown tests for GET /documents — 2A.4.

Cover: pagination correctness, total count with filters, combined filters,
empty-collection case, collection_id filter.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import (
    CollectionMemberModel,
    CollectionModel,
    DocumentModel,
)
from tests.factories import make_card, make_document


@pytest.fixture
def test_db(memory_db):
    return memory_db.engine, memory_db.factory


def _make_doc(
    *,
    title: str,
    form: str = "prose",
    tags: list[str] | None = None,
    created_at: datetime | None = None,
) -> DocumentModel:
    return make_document(
        title=title,
        form=form,
        domain="general",
        word_count=10,
        page_count=1,
        file_path="/tmp/x.txt",
        tags=tags or [],
        created_at=created_at or datetime.now(UTC),
    )


def _make_collection(name: str = "C") -> CollectionModel:
    return CollectionModel(id=str(uuid.uuid4()), name=name)


@pytest.mark.anyio
async def test_pagination_total_and_page_window(test_db):
    _, factory = test_db
    base = datetime.now(UTC)
    async with factory() as s:
        for i in range(25):
            s.add(_make_doc(title=f"Doc {i:02d}", created_at=base - timedelta(seconds=i)))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        p1 = (await c.get("/documents?page=1&page_size=10")).json()
        p2 = (await c.get("/documents?page=2&page_size=10")).json()
        p3 = (await c.get("/documents?page=3&page_size=10")).json()
        assert p1["total"] == 25
        assert p2["total"] == 25
        assert len(p1["items"]) == 10
        assert len(p2["items"]) == 10
        assert len(p3["items"]) == 5
        ids = {d["id"] for d in p1["items"] + p2["items"] + p3["items"]}
        assert len(ids) == 25


@pytest.mark.anyio
async def test_kind_filter_total_reflects_filter(test_db):
    _, factory = test_db
    async with factory() as s:
        for i in range(5):
            s.add(_make_doc(title=f"B{i}", form="prose"))
        for i in range(3):
            s.add(_make_doc(title=f"P{i}", form="paper"))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = (await c.get("/documents?kind=book")).json()
        assert r["total"] == 5
        assert all(d["kind"] == "book" for d in r["items"])

        r = (await c.get("/documents?kind=book,paper")).json()
        assert r["total"] == 8


@pytest.mark.anyio
async def test_combined_kind_and_tag_filter(test_db):
    _, factory = test_db
    a = _make_doc(title="A", form="prose")
    b = _make_doc(title="B", form="prose")
    cdoc = _make_doc(title="C", form="paper")
    async with factory() as s:
        s.add(a)
        s.add(b)
        s.add(cdoc)
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.patch(f"/documents/{a.id}/tags", json={"tags": ["physics"]})
        await c.patch(f"/documents/{b.id}/tags", json={"tags": ["history"]})
        await c.patch(f"/documents/{cdoc.id}/tags", json={"tags": ["physics"]})

        r = (await c.get("/documents?kind=book&tag=physics")).json()
        assert r["total"] == 1
        assert r["items"][0]["title"] == "A"


@pytest.mark.anyio
async def test_collection_id_filter_returns_members_only(test_db):
    _, factory = test_db
    async with factory() as s:
        col = _make_collection("Reading")
        s.add(col)
        d_in = _make_doc(title="In", form="prose")
        d_out = _make_doc(title="Out", form="prose")
        s.add(d_in)
        s.add(d_out)
        s.add(
            CollectionMemberModel(
                id=str(uuid.uuid4()),
                collection_id=col.id,
                member_id=d_in.id,
                member_type="document",
            )
        )
        await s.commit()
        cid = col.id
        in_id = d_in.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = (await c.get(f"/documents?collection_id={cid}")).json()
        assert r["total"] == 1
        assert r["items"][0]["id"] == in_id


@pytest.mark.anyio
async def test_collection_id_filter_ignores_note_memberships(test_db):
    """A note-typed membership row with the same member_id must not leak documents in."""
    _, factory = test_db
    async with factory() as s:
        col = _make_collection("Mixed")
        s.add(col)
        d = _make_doc(title="D", form="prose")
        s.add(d)
        # Note membership using doc.id as member_id -- should NOT match.
        s.add(
            CollectionMemberModel(
                id=str(uuid.uuid4()),
                collection_id=col.id,
                member_id=d.id,
                member_type="note",
            )
        )
        await s.commit()
        cid = col.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = (await c.get(f"/documents?collection_id={cid}")).json()
        assert r["total"] == 0
        assert r["items"] == []


@pytest.mark.anyio
async def test_empty_collection_returns_zero(test_db):
    _, factory = test_db
    async with factory() as s:
        col = _make_collection("Empty")
        s.add(col)
        s.add(_make_doc(title="Loose", form="prose"))
        await s.commit()
        cid = col.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = (await c.get(f"/documents?collection_id={cid}")).json()
        assert r["total"] == 0
        assert r["items"] == []


@pytest.mark.anyio
async def test_alphabetical_sort_with_pagination(test_db):
    _, factory = test_db
    async with factory() as s:
        for name in ["Charlie", "alpha", "Bravo", "delta", "Echo"]:
            s.add(_make_doc(title=name))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = (await c.get("/documents?sort=alphabetical&page=1&page_size=3")).json()
        titles = [i["title"] for i in r["items"]]
        assert titles == ["alpha", "Bravo", "Charlie"]
        r2 = (await c.get("/documents?sort=alphabetical&page=2&page_size=3")).json()
        assert [i["title"] for i in r2["items"]] == ["delta", "Echo"]


@pytest.mark.anyio
async def test_every_sort_and_filter_orders_and_counts_as_before(test_db):
    """Characterization net for the list query's move into `DocumentListRepo`."""
    from app.models import (
        DocumentTagIndexModel,
        FlashcardModel,
        StudySessionModel,
        SummaryModel,
    )

    _, factory = test_db
    base = datetime.now(UTC)
    # created oldest first: a, b, c, d
    a = _make_doc(title="delta", created_at=base - timedelta(days=4))
    b = _make_doc(title="Alpha", created_at=base - timedelta(days=3), form="paper")
    c = _make_doc(title="charlie", created_at=base - timedelta(days=2))
    d = _make_doc(title="Bravo", created_at=base - timedelta(days=1))
    a.last_accessed_at = base - timedelta(hours=1)
    b.last_accessed_at = base - timedelta(hours=3)
    c.last_accessed_at = base - timedelta(hours=2)
    d.last_accessed_at = base - timedelta(hours=4)
    d.is_favorite = True

    def card(doc, stability: float, bloom: int = 1) -> FlashcardModel:
        return make_card(
            document_id=doc.id, source_excerpt="s", fsrs_stability=stability, bloom_level=bloom
        )

    async with factory() as s:
        s.add_all([a, b, c, d])
        s.add_all([card(a, 21.0), card(b, 2.0, bloom=4), card(c, 10.0)])
        s.add(StudySessionModel(id=str(uuid.uuid4()), document_id=c.id, mode="flashcard"))
        s.add(
            SummaryModel(id=str(uuid.uuid4()), document_id=d.id, mode="one_sentence", content="x")
        )
        s.add(
            DocumentTagIndexModel(
                document_id=a.id,
                tag_full="science/biology",
                tag_root="science",
                tag_parent="science",
            )
        )
        coll = _make_collection()
        s.add(coll)
        s.add(
            CollectionMemberModel(
                id=str(uuid.uuid4()), collection_id=coll.id, member_id=b.id, member_type="document"
            )
        )
        await s.commit()

    async def titles(query: str) -> tuple[int, list[str]]:
        body = (await client.get(f"/documents?{query}")).json()
        return body["total"], [i["title"] for i in body["items"]]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        assert await titles("sort=newest") == (4, ["Bravo", "charlie", "Alpha", "delta"])
        assert await titles("sort=oldest") == (4, ["delta", "Alpha", "charlie", "Bravo"])
        assert await titles("sort=alphabetical") == (4, ["Alpha", "Bravo", "charlie", "delta"])
        assert await titles("sort=last_accessed") == (4, ["delta", "charlie", "Alpha", "Bravo"])
        assert await titles("sort=weakest-first") == (4, ["Alpha", "charlie", "delta", "Bravo"])
        assert await titles("sort=most-studied") == (4, ["charlie", "Alpha", "delta", "Bravo"])
        assert await titles("kind=paper") == (1, ["Alpha"])
        assert await titles("format=txt,pdf&sort=oldest") == (
            4,
            ["delta", "Alpha", "charlie", "Bravo"],
        )
        assert await titles("tag=science") == (1, ["delta"])
        assert await titles(f"collection_id={coll.id}") == (1, ["Alpha"])
        assert await titles("favorite=true") == (1, ["Bravo"])
        assert await titles("favorite=false&sort=oldest") == (3, ["delta", "Alpha", "charlie"])

        items = {i["title"]: i for i in (await client.get("/documents")).json()["items"]}
        assert items["Bravo"]["summary_one_sentence"] == "x"
        assert items["delta"]["mastery_pct"] == 100.0
        assert items["Alpha"]["mastery_pct"] == round(2.0 / 21.0 * 100, 1)
        assert items["charlie"]["learning_status"] != items["Bravo"]["learning_status"]
        assert items["Bravo"]["mastery_pct"] is None
