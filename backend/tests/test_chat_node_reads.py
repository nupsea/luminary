"""The repo reads the chat nodes moved out of `runtime/` (0.17.0 batch 1), on a real database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import (
    CollectionMemberModel,
    CollectionModel,
    ImageModel,
    LibrarySummaryModel,
    SectionSummaryModel,
    SummaryModel,
)
from app.repos.collection_repo import CollectionRepo
from app.repos.document_repo import DocumentRepo
from app.repos.image_repo import ImageRepo
from app.repos.summary_repo import SummaryRepo
from tests.factories import make_chunk, make_document

T0 = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
async def session(memory_db):
    factory = async_sessionmaker(memory_db.engine, expire_on_commit=False)
    async with factory() as s:
        s.add_all(
            [
                make_document(
                    id="d1", title="The Time Machine", file_path="/x", publication_year=1895
                ),
                make_document(
                    id="d2",
                    title="Frankenstein",
                    form="entries",
                    file_path="/y",
                    stage="chunking",
                ),
            ]
        )
        s.add_all(
            make_chunk(id=f"c{i}", document_id="d1", text=f"t{i}", token_count=1, chunk_index=i)
            for i in range(5)
        )
        s.add_all(
            [
                SummaryModel(
                    id="s1", document_id="d1", mode="executive", content="old", created_at=T0
                ),
                SummaryModel(
                    id="s2",
                    document_id="d1",
                    mode="executive",
                    content="new",
                    created_at=T0 + timedelta(days=1),
                ),
                SummaryModel(
                    id="s3", document_id="d2", mode="executive", content="f", created_at=T0
                ),
                SummaryModel(
                    id="s4",
                    document_id="d2",
                    mode="detailed",
                    content="x",
                    created_at=T0 + timedelta(hours=1),
                ),
                LibrarySummaryModel(id="l1", mode="executive", content="lib", created_at=T0),
                SectionSummaryModel(
                    id="ss1", document_id="d1", heading="I", content="one", unit_index=0
                ),
                SectionSummaryModel(
                    id="ss2", document_id="d1", heading="II", content="two", unit_index=1
                ),
            ]
        )
        s.add_all(
            ImageModel(
                id=iid,
                document_id="d1",
                page=1,
                path="/p",
                width=1,
                height=1,
                content_hash=iid,
                description=desc,
                image_type=kind,
            )
            for iid, desc, kind in (
                ("i1", "a chart", "chart"),
                ("i2", None, "chart"),
                ("i3", "a border", "decorative"),
            )
        )
        s.add_all(
            [
                CollectionModel(id="col1", name="auto", auto_document_id="d1"),
                CollectionMemberModel(
                    id="m1", collection_id="col1", member_id="n1", member_type="note"
                ),
                CollectionMemberModel(
                    id="m2", collection_id="col1", member_id="d1", member_type="document"
                ),
            ]
        )
        await s.commit()
        yield s


async def test_document_reads(session):
    docs = DocumentRepo(session)

    assert sorted(await docs.id_stages()) == [("d1", "complete"), ("d2", "chunking")]
    assert sorted(await docs.ids_and_titles()) == [
        ("d1", "The Time Machine"),
        ("d2", "Frankenstein"),
    ]
    assert await docs.ids_titled_like("TIME") == ["d1"]
    assert await docs.publication_years(["d1", "d2"]) == {"d1": 1895, "d2": None}
    assert sorted(await docs.neighbor_chunks("d1", 2)) == [(1, "t1"), (3, "t3")]
    assert await docs.neighbor_chunk_texts([("d1", 0), ("d1", 4)]) == {
        ("d1", 1): "t1",
        ("d1", 3): "t3",
    }


async def test_summary_reads(session):
    summaries = SummaryRepo(session)

    assert await summaries.latest_executive_with_titles() == [
        ("Frankenstein", "f"),
        ("The Time Machine", "new"),
    ]
    assert await summaries.section_summaries_by_heading([("d1", "II"), ("d1", "missing")]) == {
        ("d1", "II"): "two"
    }
    assert (await summaries.latest("d1", "executive")).content == "new"
    assert (await summaries.latest_library("executive")).content == "lib"


async def test_only_described_informative_images_are_read(session):
    images = await ImageRepo(session).described_by_ids(["i1", "i2", "i3"])
    assert [i.id for i in images] == ["i1"]


async def test_a_document_s_auto_collection_notes(session):
    collections = CollectionRepo(session)

    assert await collections.auto_collection_id("d1") == "col1"
    assert await collections.auto_collection_id("d2") is None
    assert await collections.note_ids("col1") == ["n1"]


async def test_a_summary_of_another_mode_written_at_the_same_instant_is_not_executive(memory_db):
    factory = async_sessionmaker(memory_db.engine, expire_on_commit=False)
    async with factory() as s:
        s.add(make_document(id="d", title="D", file_path="/d", stage="parsing"))
        s.add_all(
            SummaryModel(id=mode, document_id="d", mode=mode, content=mode, created_at=T0)
            for mode in ("executive", "detailed")
        )
        await s.commit()

        assert await SummaryRepo(s).latest_executive_with_titles() == [("D", "executive")]
