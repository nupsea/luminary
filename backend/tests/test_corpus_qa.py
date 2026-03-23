"""Corpus-driven integration tests for all three canonical books.

Run with:
    cd backend && uv run pytest tests/test_corpus_qa.py -m slow -v

All tests use the all_books_ingested session fixture which:
  - ingests all 3 books with real ML (BAAI/bge-m3 + GLiNER), LiteLLM mocked
  - creates a shared temp SQLite + LanceDB + Kuzu environment
  - asserts each book reaches stage='complete'
"""

import re

import pytest
from sqlalchemy import select

pytest_plugins = ["conftest_books"]


# ---------------------------------------------------------------------------
# Alice in Wonderland retrieval tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_alice_factual_retrieval_hr3(all_books_ingested):
    """HR@3 >= 0.6 on 5 Alice factual questions using the hybrid retriever."""
    from app.services.retriever import get_retriever

    alice_doc_id = all_books_ingested["Alice in Wonderland"]["doc_id"]
    retriever = get_retriever()

    factual_qs = [
        (
            "What label was on the bottle Alice found?",
            "DRINK ME",
        ),
        (
            "What advice did the Caterpillar give Alice about the mushroom?",
            "One side will make you grow taller",
        ),
        (
            "What were the balls and mallets in the Queen's croquet game?",
            "the balls were live hedgehogs, the mallets live flamingoes",
        ),
        (
            "What did the Cheshire Cat say about everyone in Wonderland?",
            "we're all mad here",
        ),
        (
            "What did the Dodo declare the winner of the Caucus-race?",
            "has won, and all must have prizes",
        ),
    ]

    hits = 0
    for question, hint in factual_qs:
        chunks = await retriever.retrieve(
            query=question,
            document_ids=[alice_doc_id],
            k=3,
        )
        texts = [c.text for c in chunks]
        if any(hint.lower()[:80] in t.lower() for t in texts):
            hits += 1

    hr3 = hits / len(factual_qs)
    assert hr3 >= 0.6, (
        f"Alice HR@3={hr3:.2f} < 0.60 on {len(factual_qs)} factual questions"
    )


# ---------------------------------------------------------------------------
# Odyssey retrieval tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_odyssey_factual_retrieval_hr3(all_books_ingested):
    """HR@3 >= 0.6 on 5 Odyssey factual questions using the hybrid retriever."""
    from app.services.retriever import get_retriever

    odyssey_doc_id = all_books_ingested["The Odyssey"]["doc_id"]
    retriever = get_retriever()

    factual_qs = [
        (
            "Which god persecuted Ulysses and prevented him from getting home?",
            "Neptune, who still persecuted him without ceasing",
        ),
        (
            "What false name did Ulysses give the Cyclops?",
            "my name is Noman",
        ),
        (
            "What did Circe tell Ulysses to do to protect his men from the Sirens?",
            "stop your men's ears with wax",
        ),
        (
            "Where did Telemachus travel to seek news of his father?",
            "I am going to Sparta and to Pylos",
        ),
        (
            "Who was detaining Ulysses on an island at the start of the Odyssey?",
            "detained by the goddess Calypso, who had got him into a large cave",
        ),
    ]

    hits = 0
    for question, hint in factual_qs:
        chunks = await retriever.retrieve(
            query=question,
            document_ids=[odyssey_doc_id],
            k=3,
        )
        texts = [c.text for c in chunks]
        if any(hint.lower()[:80] in t.lower() for t in texts):
            hits += 1

    hr3 = hits / len(factual_qs)
    assert hr3 >= 0.6, (
        f"Odyssey HR@3={hr3:.2f} < 0.60 on {len(factual_qs)} factual questions"
    )


# ---------------------------------------------------------------------------
# Entity extraction tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_alice_known_entities_extracted(all_books_ingested):
    """'alice' and 'queen' present in entities; >= 10 distinct entity names."""
    import app.services.graph as graph_module

    alice_doc_id = all_books_ingested["Alice in Wonderland"]["doc_id"]
    graph = graph_module.get_graph_service()

    by_type = graph.get_entities_by_type_for_document(alice_doc_id)
    names = {name.lower() for type_names in by_type.values() for name in type_names}

    assert any("alice" in n for n in names), (
        f"'alice' not found in entities: {sorted(names)[:30]}"
    )
    assert any("queen" in n for n in names), (
        f"'queen' not found in entities: {sorted(names)[:30]}"
    )
    assert len(names) >= 10, (
        f"Expected >= 10 distinct entities for Alice, got {len(names)}: {sorted(names)}"
    )


@pytest.mark.slow
async def test_odyssey_known_entities_extracted(all_books_ingested):
    """'ulysses'/'odysseus', 'penelope', 'telemachus' present; >= 15 distinct entities."""
    import app.services.graph as graph_module

    odyssey_doc_id = all_books_ingested["The Odyssey"]["doc_id"]
    graph = graph_module.get_graph_service()

    by_type = graph.get_entities_by_type_for_document(odyssey_doc_id)
    names = {name.lower() for type_names in by_type.values() for name in type_names}

    # Butler translation uses "Ulysses" throughout; accept either form
    assert any("ulysses" in n or "odysseus" in n for n in names), (
        f"Neither 'ulysses' nor 'odysseus' found in entities. Found: {sorted(names)[:30]}"
    )
    for required in ["penelope", "telemachus"]:
        assert any(required in n for n in names), (
            f"'{required}' not found in entities. Found: {sorted(names)[:30]}"
        )

    assert len(names) >= 15, (
        f"Expected >= 15 distinct entities for Odyssey, got {len(names)}: {sorted(names)}"
    )


# ---------------------------------------------------------------------------
# Section summary Gutenberg filter tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_alice_section_summaries_no_gutenberg(all_books_ingested):
    """No Alice section summary contains 'project gutenberg' or 'terms of use'; >= 5 rows."""
    import app.database as db_module
    from app.models import SectionSummaryModel

    alice_doc_id = all_books_ingested["Alice in Wonderland"]["doc_id"]

    async with db_module.get_session_factory()() as session:
        rows = (
            await session.scalars(
                select(SectionSummaryModel)
                .where(SectionSummaryModel.document_id == alice_doc_id)
                .order_by(SectionSummaryModel.unit_index)
            )
        ).all()

    assert len(rows) >= 5, (
        f"Expected >= 5 section summaries for Alice, got {len(rows)}"
    )

    banned = ["project gutenberg", "terms of use"]
    for row in rows:
        text_lower = (row.content or "").lower()
        for phrase in banned:
            assert phrase not in text_lower, (
                f"Alice section summary contains banned phrase '{phrase}':\n"
                f"{row.content[:200]}"
            )


@pytest.mark.slow
async def test_odyssey_section_summaries_no_gutenberg(all_books_ingested):
    """No Odyssey section summary contains 'project gutenberg' or 'terms of use'; >= 5 rows."""
    import app.database as db_module
    from app.models import SectionSummaryModel

    odyssey_doc_id = all_books_ingested["The Odyssey"]["doc_id"]

    async with db_module.get_session_factory()() as session:
        rows = (
            await session.scalars(
                select(SectionSummaryModel)
                .where(SectionSummaryModel.document_id == odyssey_doc_id)
                .order_by(SectionSummaryModel.unit_index)
            )
        ).all()

    assert len(rows) >= 5, (
        f"Expected >= 5 section summaries for Odyssey, got {len(rows)}"
    )

    banned = ["project gutenberg", "terms of use"]
    for row in rows:
        text_lower = (row.content or "").lower()
        for phrase in banned:
            assert phrase not in text_lower, (
                f"Odyssey section summary contains banned phrase '{phrase}':\n"
                f"{row.content[:200]}"
            )


# ---------------------------------------------------------------------------
# Executive summary quality tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_alice_executive_summary_quality(all_books_ingested):
    """Alice executive summary: no 3-line numbered-list pattern; mentions key terms."""
    import app.database as db_module
    from app.models import SummaryModel

    alice_doc_id = all_books_ingested["Alice in Wonderland"]["doc_id"]

    async with db_module.get_session_factory()() as session:
        exec_row = (
            await session.scalars(
                select(SummaryModel).where(
                    SummaryModel.document_id == alice_doc_id,
                    SummaryModel.mode == "executive",
                )
            )
        ).first()

    assert exec_row is not None, "Alice executive summary row is None"
    text = exec_row.content or ""
    assert len(text) > 50, f"Alice executive summary too short: {text!r}"

    # No 3-or-more consecutive numbered lines (would indicate passage-list output)
    lines = text.splitlines()
    numbered_consecutive = 0
    for line in lines:
        if re.match(r"^\s*\d+\.\s", line):
            numbered_consecutive += 1
        else:
            numbered_consecutive = 0
        assert numbered_consecutive < 3, (
            "Alice executive summary looks like a passage-list (3+ numbered lines):\n"
            + text[:400]
        )

    text_lower = text.lower()
    required_terms = ["alice", "wonderland", "queen", "rabbit", "mad"]
    missing = [t for t in required_terms if t not in text_lower]
    assert not missing, (
        f"Alice executive summary missing terms {missing}:\n{text[:400]}"
    )


@pytest.mark.slow
async def test_odyssey_executive_summary_quality(all_books_ingested):
    """Odyssey executive summary: no 3-line numbered-list pattern; mentions key terms."""
    import app.database as db_module
    from app.models import SummaryModel

    odyssey_doc_id = all_books_ingested["The Odyssey"]["doc_id"]

    async with db_module.get_session_factory()() as session:
        exec_row = (
            await session.scalars(
                select(SummaryModel).where(
                    SummaryModel.document_id == odyssey_doc_id,
                    SummaryModel.mode == "executive",
                )
            )
        ).first()

    assert exec_row is not None, "Odyssey executive summary row is None"
    text = exec_row.content or ""
    assert len(text) > 50, f"Odyssey executive summary too short: {text!r}"

    lines = text.splitlines()
    numbered_consecutive = 0
    for line in lines:
        if re.match(r"^\s*\d+\.\s", line):
            numbered_consecutive += 1
        else:
            numbered_consecutive = 0
        assert numbered_consecutive < 3, (
            "Odyssey executive summary looks like a passage-list (3+ numbered lines):\n"
            + text[:400]
        )

    # Accept "ulysses" as alternative to "odysseus" (Butler translation)
    text_lower = text.lower()
    hero_terms = ["odysseus", "ulysses"]
    assert any(t in text_lower for t in hero_terms), (
        f"Odyssey executive summary missing hero name {hero_terms}:\n{text[:400]}"
    )
    required_terms = ["penelope", "journey", "hero"]
    missing = [t for t in required_terms if t not in text_lower]
    assert not missing, (
        f"Odyssey executive summary missing terms {missing}:\n{text[:400]}"
    )


# ---------------------------------------------------------------------------
# Cross-book retrieval test
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_cross_book_retrieval(all_books_ingested):
    """A broad query returns chunks from >= 2 different document_ids."""
    from app.services.retriever import get_retriever

    retriever = get_retriever()

    chunks = await retriever.retrieve(
        query="adventure and journey",
        document_ids=None,  # cross-book: no filter
        k=10,
    )
    doc_ids = {c.document_id for c in chunks}
    assert len(doc_ids) >= 2, (
        f"Cross-book query returned chunks from only {len(doc_ids)} document(s): {doc_ids}"
    )


# ---------------------------------------------------------------------------
# Section summary count test (all 3 books)
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_all_books_have_section_summaries(all_books_ingested):
    """Each of the 3 books has >= 10 section summary rows in the DB."""
    import app.database as db_module
    from app.models import SectionSummaryModel

    async with db_module.get_session_factory()() as session:
        for book_name, info in all_books_ingested.items():
            doc_id = info["doc_id"]
            rows = (
                await session.scalars(
                    select(SectionSummaryModel).where(
                        SectionSummaryModel.document_id == doc_id
                    )
                )
            ).all()
            assert len(rows) >= 10, (
                f"Book '{book_name}' has only {len(rows)} section summaries"
                f" (expected >= 10)"
            )
