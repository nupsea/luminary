"""Document -> study topics: top-level headings for clean docs, LLM outline for messy ones, with
front/back-matter + metadata (index, copyright, publisher, blank) never becoming a topic.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

import app.services.graph as graph_module
from app.main import app
from app.services.topic_service import is_junk_heading
from tests.factories import make_card, make_chunk, make_document, make_section


@pytest.fixture
def test_db(memory_db, monkeypatch):
    monkeypatch.setattr(graph_module, "_graph_service", None)
    return memory_db.factory


async def _doc(factory, doc_id, headings):
    """headings: list of (heading, level)."""
    async with factory() as s:
        s.add(
            make_document(
                id=doc_id,
                format="pdf",
                file_path="/x",
                stage="parsing",
            )
        )
        for i, (h, lvl) in enumerate(headings):
            s.add(
                make_section(
                    id=f"{doc_id}-s{i}", document_id=doc_id, heading=h, level=lvl, section_order=i
                )
            )
        await s.commit()


def test_is_junk_heading():
    long_sentence = (
        "Through firsthand experience working with data across organizations, tools, and "
        "industries we have uncovered a better way to develop and deliver analytics."
    )
    for junk in [
        "Index",
        "  ",
        "Table of Contents",
        "Copyright © 2020 O'Reilly",
        "ISBN 978-1",
        "Get the developer newsletter",
        "Bibliography",
        "About the Author",
        "Foreword",
        "Preface to the Second Edition",
        "Appendix",
        "Contributor List",
        "Copyright Page",
        "...",
        "1",
        "18",
        "a",
        long_sentence,
    ]:  # bare list-markers + paragraph
        assert is_junk_heading(junk), junk
    for keep in [
        "I. A SCANDAL IN BOHEMIA",
        "CHAPTER I — Down the Rabbit-Hole",
        "Replication",
        "Introduction to Distributed Systems",
        "Embrace change",
    ]:
        assert not is_junk_heading(keep), keep


async def test_clean_doc_uses_top_level_sections_minus_junk(test_db):
    await _doc(
        test_db,
        "d1",
        [
            ("Table of Contents", 1),
            ("Chapter 1: Foundations", 1),
            ("1.1 sub", 2),
            ("Chapter 2: Replication", 1),
            ("Chapter 3: Partitioning", 1),
            ("Index", 1),
            ("Copyright", 1),
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
        test_db,
        "bk",
        [
            ("Index", 1),
            ("Chapter 1. Reliability", 2),
            ("Hardware Faults", 2),
            ("Software Errors", 2),
            ("Chapter 2. Scalability", 2),
            ("Describing Load", 2),
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
        s.add(make_document(id="d", title="D", format="pdf", file_path="/x", stage="parsing"))
        for sec, ch in [("s1", "c1"), ("s2", "c2")]:
            s.add(make_section(id=sec, document_id="d", heading=sec))
            s.add(make_chunk(id=ch, document_id="d", section_id=sec))
        s.add(
            make_card(
                id="f1",
                document_id="d",
                chunk_id="c1",
                question="q1",
                source_excerpt="e",
                due_date=past,
            )
        )
        s.add(
            make_card(
                id="f2",
                document_id="d",
                chunk_id="c2",
                question="q2",
                source_excerpt="e",
                due_date=past,
            )
        )
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
        s.add(make_chunk(id="c0", document_id="d2", text="intro text about systems"))
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


def test_markdown_marks_are_stripped_from_titles():
    from app.services.topic_service import _clean_title

    assert _clean_title("[**Training**]") == "Training"
    assert _clean_title("(**Vanishing Gradients**)") == "Vanishing Gradients"
    assert _clean_title("**Bold** and **bold**") == "**Bold** and **bold**"


async def test_a_markdown_book_s_topics_are_its_top_level_headings(test_db):
    """#307: d2l, through the parser and the tech-book level pass, yields the eval's golden."""
    import json
    from pathlib import Path

    from app.services.parser import DocumentParser
    from app.services.tech_section_parser import assign_parent_headings_dicts

    root = Path(__file__).resolve().parents[2]
    golden = json.loads((root / "evals/golden/topics/d2l.json").read_text())
    parsed = DocumentParser().parse(root / golden["source_file"], "md")
    raw = [{"heading": s.heading, "level": s.level} for s in parsed.sections]
    assign_parent_headings_dicts(raw)
    await _doc(test_db, "d2l", [(s["heading"], s["level"]) for s in raw])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/study/topics/d2l")).json()
    assert body["source"] == "sections"
    assert [t["title"] for t in body["topics"]] == golden["expected_topics"]


def test_an_epistolary_novel_s_letters_are_topics():
    """#332: Frankenstein's chapter headings won the topic list and left its four Letters out."""
    from types import SimpleNamespace

    from app.services.topic_service import _pick_topic_sections

    headings = [f"Letter {n}" for n in range(1, 5)] + [f"Chapter {n}" for n in range(1, 6)]
    tops = _pick_topic_sections([SimpleNamespace(heading=h, level=1) for h in headings])

    assert [t.heading for t in tops] == headings
