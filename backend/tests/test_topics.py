"""Document -> study topics: top-level headings for clean docs, LLM outline for messy ones, with
front/back-matter + metadata (index, copyright, publisher, blank) never becoming a topic.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, FlashcardModel, SectionModel
from app.services.topic_service import is_junk_heading


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    orig_graph = graph_module._graph_service
    graph_module._graph_service = None
    yield factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    graph_module._graph_service = orig_graph


async def _doc(factory, doc_id, headings):
    """headings: list of (heading, level)."""
    async with factory() as s:
        s.add(
            DocumentModel(
                id=doc_id, title="Test Doc", format="pdf", content_type="application/pdf",
                file_path="/x",
            )
        )
        for i, (h, lvl) in enumerate(headings):
            s.add(
                SectionModel(
                    id=f"{doc_id}-s{i}", document_id=doc_id, heading=h, level=lvl,
                    section_order=i,
                )
            )
        await s.commit()


def test_is_junk_heading():
    long_sentence = (
        "Through firsthand experience working with data across organizations, tools, and "
        "industries we have uncovered a better way to develop and deliver analytics."
    )
    for junk in ["Index", "  ", "Table of Contents", "Copyright © 2020 O'Reilly", "ISBN 978-1",
                 "Get the developer newsletter", "Bibliography", "About the Author", "...",
                 "1", "18", "a", long_sentence]:  # bare list-markers + paragraph
        assert is_junk_heading(junk), junk
    for keep in ["I. A SCANDAL IN BOHEMIA", "CHAPTER I — Down the Rabbit-Hole",
                 "Replication", "Introduction to Distributed Systems", "Embrace change"]:
        assert not is_junk_heading(keep), keep


async def test_clean_doc_uses_top_level_sections_minus_junk(test_db):
    await _doc(
        test_db, "d1",
        [
            ("Table of Contents", 1), ("Chapter 1: Foundations", 1),
            ("1.1 sub", 2), ("Chapter 2: Replication", 1), ("Chapter 3: Partitioning", 1),
            ("Index", 1), ("Copyright", 1),
        ],
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/study/topics/d1")).json()
    assert body["source"] == "sections"
    titles = [t["title"] for t in body["topics"]]
    assert titles == ["Chapter 1: Foundations", "Chapter 2: Replication", "Chapter 3: Partitioning"]
    assert "Index" not in titles and "Copyright" not in titles and "Table of Contents" not in titles


async def test_ddia_like_uses_chapter_headings_not_outline(test_db):
    # flattened levels (Parts @ level 1, chapters+subsections all @ level 2) -- like DDIA.
    # The explicit "Chapter N" headings must become the topics, deterministically (no LLM).
    headings = [("Part I. Foundations", 1)]
    for n in range(1, 7):
        headings.append((f"Chapter {n}. Topic {n}", 2))
        headings.append((f"some subsection {n}a", 2))
        headings.append((f"some subsection {n}b", 2))
    await _doc(test_db, "ddia", headings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/study/topics/ddia")).json()
    assert body["source"] == "sections"  # NOT outline -- it's a clean book
    titles = [t["title"] for t in body["topics"]]
    assert titles == [f"Chapter {n}. Topic {n}" for n in range(1, 7)]
    assert not any("subsection" in t for t in titles)  # subsections excluded from topics
    assert "Part I. Foundations" not in titles  # parts are groupings, not topics


async def test_sections_search_returns_subsections(test_db):
    await _doc(
        test_db, "bk",
        [
            ("Index", 1), ("Chapter 1. Reliability", 2), ("Hardware Faults", 2),
            ("Software Errors", 2), ("Chapter 2. Scalability", 2), ("Describing Load", 2),
        ],
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        allsecs = (await client.get("/study/sections/bk")).json()
        titles = [s["title"] for s in allsecs]
        assert "Hardware Faults" in titles and "Describing Load" in titles  # subsections included
        assert "Index" not in titles  # junk still filtered
        hit = (await client.get("/study/sections/bk", params={"q": "fault"})).json()
        assert [s["title"] for s in hit] == ["Hardware Faults"]


async def test_due_cards_filter_by_section(test_db):
    past = datetime.now(UTC) - timedelta(days=1)
    async with test_db() as s:
        s.add(DocumentModel(id="d", title="D", format="pdf", content_type="x", file_path="/x"))
        for sec, ch in [("s1", "c1"), ("s2", "c2")]:
            s.add(SectionModel(id=sec, document_id="d", heading=sec, level=1, section_order=0))
            s.add(ChunkModel(id=ch, document_id="d", text="t", chunk_index=0, section_id=sec))
        s.add(FlashcardModel(
            id="f1", document_id="d", chunk_id="c1", question="q1", answer="a", source_excerpt="e",
            due_date=past,
        ))
        s.add(FlashcardModel(
            id="f2", document_id="d", chunk_id="c2", question="q2", answer="a", source_excerpt="e",
            due_date=past,
        ))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s1 = (await client.get("/study/due", params={"section_id": "s1"})).json()
        assert [c["id"] for c in s1] == ["f1"]  # only the section's card
        both = (await client.get("/study/due", params={"document_id": "d"})).json()
        assert {c["id"] for c in both} == {"f1", "f2"}


async def test_messy_doc_falls_back_to_llm_outline(test_db, monkeypatch):
    # one usable heading -> below the clean floor -> outline path
    await _doc(test_db, "d2", [("Some Heading", 1), ("Index", 1)])
    async with test_db() as s:
        s.add(ChunkModel(id="c0", document_id="d2", text="intro text about systems", chunk_index=0))
        await s.commit()

    async def _complete(messages, **k):
        return '{"topics": ["Real Topic A", "Real Topic B", "Copyright"]}'

    monkeypatch.setattr(
        "app.services.topic_service.get_llm_service",
        lambda: type("L", (), {"complete": staticmethod(_complete)})(),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/study/topics/d2")).json()
    assert body["source"] == "outline"
    titles = [t["title"] for t in body["topics"]]
    assert titles == ["Real Topic A", "Real Topic B"]  # LLM-suggested "Copyright" still filtered
