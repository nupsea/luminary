"""Tests for SummarizationService and POST /summarize/{document_id}."""

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from stubs import CapturingLLMService as _CapturingLLMService
from stubs import MockLLMService as _MockLLMService

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, SectionSummaryModel, SummaryModel
from app.services.qa import QA_SYSTEM_PROMPT
from app.services.summarizer import (
    GROUNDING_PREFIX,
    LIBRARY_SYSTEM_PROMPTS,
    MODE_INSTRUCTIONS,
    SummarizationService,
    _build_system_prompt,
    _input_token_budget,
)

# Shared DB fixture


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    """Wire an in-memory SQLite DB into the app's global singletons."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


async def _insert_doc_and_chunks(
    factory,
    tmp_path: Path,
    doc_id: str,
    chunk_texts: list[str],
    token_counts: list[int] | None = None,
):
    """Helper: insert a document and chunks into the in-memory DB."""
    if token_counts is None:
        token_counts = [len(t.split()) for t in chunk_texts]

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test Doc",
                format="txt",
                content_type="notes",
                word_count=sum(token_counts),
                page_count=1,
                file_path=str(tmp_path / "doc.txt"),
                stage="complete",
            )
        )
        await session.flush()
        for idx, (text, tokens) in enumerate(zip(chunk_texts, token_counts)):
            session.add(
                ChunkModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    text=text,
                    token_count=tokens,
                    chunk_index=idx,
                    page_number=1,
                )
            )
        await session.commit()


# _build_system_prompt — mode-specific prompt construction


def test_one_sentence_prompt_contains_grounding():
    prompt = _build_system_prompt("one_sentence")
    assert GROUNDING_PREFIX in prompt


def test_one_sentence_prompt_mentions_30_words():
    prompt = _build_system_prompt("one_sentence")
    assert "30 words" in prompt


def test_executive_prompt_mentions_bullet_points():
    prompt = _build_system_prompt("executive")
    assert "bullet" in prompt.lower()


def test_detailed_prompt_mentions_heading():
    prompt = _build_system_prompt("detailed")
    assert "heading" in prompt.lower()


def test_conversation_prompt_mentions_json():
    prompt = _build_system_prompt("conversation")
    assert "JSON" in prompt


def test_all_modes_include_grounding_prefix():
    for mode in MODE_INSTRUCTIONS:
        prompt = _build_system_prompt(mode)
        assert GROUNDING_PREFIX in prompt, f"mode={mode} missing grounding prefix"


def test_executive_prompt_contains_markdown_instruction():
    prompt = _build_system_prompt("executive")
    assert "Markdown" in prompt


def test_detailed_prompt_contains_markdown_instruction():
    prompt = _build_system_prompt("detailed")
    assert "Markdown" in prompt


def test_library_executive_prompt_contains_markdown_instruction():
    assert "Markdown" in LIBRARY_SYSTEM_PROMPTS["executive"]


def test_library_detailed_prompt_contains_markdown_instruction():
    assert "Markdown" in LIBRARY_SYSTEM_PROMPTS["detailed"]


def test_qa_system_prompt_contains_markdown_instruction():
    assert "Markdown" in QA_SYSTEM_PROMPT


# SummarizationService.stream_summary — SSE token events


@pytest.mark.asyncio
async def test_stream_collects_tokens_as_sse_events(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["Hello world."], [10])

    mock_llm = _MockLLMService(tokens=["Sum", "mary"])

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        events = [e async for e in svc.stream_summary(doc_id, "one_sentence", None)]

    # All but the last event should be token events
    token_events = events[:-1]
    for event in token_events:
        assert event.startswith("data: ")
        payload = json.loads(event[len("data: ") :])
        assert "token" in payload

    # Last event is the done event
    done_payload = json.loads(events[-1][len("data: ") :])
    assert done_payload["done"] is True
    assert "summary_id" in done_payload


@pytest.mark.asyncio
async def test_stream_token_values_match_llm_output(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["Some text."], [5])

    tokens = ["Hello", " ", "world"]
    mock_llm = _MockLLMService(tokens=tokens)

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        events = [e async for e in svc.stream_summary(doc_id, "executive", None)]

    collected = [json.loads(e[len("data: ") :])["token"] for e in events[:-1]]
    assert collected == tokens


# SummarizationService — small document: no map-reduce


@pytest.mark.asyncio
async def test_small_document_passes_full_text_to_llm(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    chunk_texts = ["chunk one", "chunk two"]
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, chunk_texts, [10, 10])

    mock_llm = _CapturingLLMService(tokens=["ok"])

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        _ = [e async for e in svc.stream_summary(doc_id, "one_sentence", None)]

    assert mock_llm.captured_prompts[0] == "chunk one\n\nchunk two"


# SummarizationService — large document: map-reduce applied


@pytest.mark.asyncio
async def test_large_document_triggers_map_reduce(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    # Token count over the input budget to trigger map-reduce
    big_tokens = _input_token_budget() + 1
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["large text"], [big_tokens])

    mock_llm = _MockLLMService(response="section summary", tokens=["summary"])

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        _ = [e async for e in svc.stream_summary(doc_id, "executive", None)]

    # Map-reduce means at least 2 calls: one map + one reduce
    assert mock_llm.call_count >= 2


# SummarizationService — summary stored in SQLite after streaming


@pytest.mark.asyncio
async def test_completed_summary_stored_in_sqlite(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["hello"], [5])

    mock_llm = _MockLLMService(tokens=["A", " summary"])

    # A streaming mode on purpose: this guards that what was streamed is what was
    # stored. `detailed` no longer streams -- it is assembled from the section
    # summaries, or generated batch by batch when none exist.
    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        events = [e async for e in svc.stream_summary(doc_id, "executive", None)]

    done_payload = json.loads(events[-1][len("data: ") :])
    summary_id = done_payload["summary_id"]

    async with factory() as session:
        result = await session.execute(select(SummaryModel).where(SummaryModel.id == summary_id))
        stored = result.scalar_one_or_none()

    assert stored is not None
    assert stored.document_id == doc_id
    assert stored.mode == "executive"
    assert stored.content == "A summary"


# POST /summarize/{document_id} — HTTP endpoint


@pytest.mark.asyncio
async def test_endpoint_returns_404_for_unknown_document(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/summarize/nonexistent-id",
            json={"mode": "executive"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_endpoint_returns_sse_content_type(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["sample text"], [8])

    mock_llm = _MockLLMService(tokens=["result"])

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/summarize/{doc_id}",
                json={"mode": "one_sentence"},
            )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_endpoint_streams_token_and_done_events(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["test content"], [5])

    mock_llm = _MockLLMService(tokens=["tok1", "tok2"])

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/summarize/{doc_id}",
                json={"mode": "executive"},
            )

    raw = resp.text
    events = [line for line in raw.splitlines() if line.startswith("data: ")]
    assert len(events) >= 2  # at least token events + done

    # Last event is done
    last = json.loads(events[-1][len("data: ") :])
    assert last["done"] is True
    assert "summary_id" in last


@pytest.mark.asyncio
async def test_endpoint_accepts_conversation_mode(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["meeting notes"], [10])

    json_output = '{"timeline": [], "decisions": [], "action_items": []}'
    mock_llm = _MockLLMService(tokens=[json_output])

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/summarize/{doc_id}",
                json={"mode": "conversation"},
            )

    assert resp.status_code == 200
    raw = resp.text
    events = [line for line in raw.splitlines() if line.startswith("data: ")]
    # First event should carry the JSON output as a token
    first = json.loads(events[0][len("data: ") :])
    assert "token" in first


# S71 — Cache and force_refresh tests


@pytest.mark.asyncio
async def test_stream_summary_returns_cached_on_second_call(test_db):
    """Second call to stream_summary must return cached: true without calling LLM."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["sample content"], [10])

    mock_llm = _MockLLMService(tokens=["First", " call"])

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        # First call — generates and stores
        _ = [e async for e in svc.stream_summary(doc_id, "executive", None)]
        assert mock_llm.call_count == 1

        # Second call — must serve from cache, no LLM call
        events = [e async for e in svc.stream_summary(doc_id, "executive", None)]

    assert mock_llm.call_count == 1, "LLM was called on second request (cache miss)"
    done_payload = json.loads(events[-1][len("data: ") :])
    assert done_payload.get("cached") is True


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache(test_db):
    """force_refresh=True must regenerate via LLM even when cache exists."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["text here"], [5])

    mock_llm = _MockLLMService(tokens=["Fresh", " summary"])

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        svc = SummarizationService()
        # Populate cache
        _ = [e async for e in svc.stream_summary(doc_id, "executive", None)]
        assert mock_llm.call_count == 1

        # force_refresh=True — must call LLM again
        events = [
            e async for e in svc.stream_summary(doc_id, "executive", None, force_refresh=True)
        ]

    assert mock_llm.call_count >= 2, "LLM not called on force_refresh=True"
    done_payload = json.loads(events[-1][len("data: ") :])
    assert done_payload.get("cached") is False


async def _insert_section_summaries(factory, doc_id, sections):
    async with factory() as session:
        for idx, (heading, content) in enumerate(sections):
            session.add(
                SectionSummaryModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    heading=heading,
                    content=content,
                    unit_index=idx,
                )
            )
        await session.commit()


_CHAPTERED = [
    ("Praise for the Book", "Reviewers love this book."),
    ("Preface", "This book grew out of a course on retrieval."),
    ("Chapter 1. Introduction to RAG", "RAG combines retrieval with LLM generation."),
    ("How Does RAG Work?", "Query flow fetches documents then prompts LLM."),
    ("Figure 1-1. Architecture", "Diagram of RAG stack."),
    ("", "An unlabelled passage about chunk overlap."),
    ("Chapter 2. Scaling RAG", "Scaling requires hybrid search and reranking."),
    ("Hybrid Search", "Combines BM25 with dense vector embeddings."),
    ("Index", "Index of terms."),
    ("A", "Terms under A."),
]


@pytest.mark.asyncio
async def test_assembled_detailed_keeps_every_authored_section_whole(test_db):
    """Only publisher boilerplate is left out; nothing authored is cut or capped."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["doc body"], [5])
    many = [(f"Topic {i}", f"Finding number {i} is stated in full here.") for i in range(40)]
    await _insert_section_summaries(factory, doc_id, _CHAPTERED[:6] + many + _CHAPTERED[6:])

    detailed = await SummarizationService().build_assembled_summary(doc_id, "detailed")

    assert detailed is not None
    for heading, content in _CHAPTERED[1:8] + many:
        assert content in detailed, f"{heading!r} lost"
    assert "## Chapter 1. Introduction to RAG" in detailed
    assert "### Hybrid Search" in detailed
    for boilerplate in ("Reviewers love", "Index of terms", "Terms under A"):
        assert boilerplate not in detailed


@pytest.mark.asyncio
async def test_a_single_letter_heading_is_only_boilerplate_inside_an_index(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["doc body"], [5])
    await _insert_section_summaries(
        factory,
        doc_id,
        [
            ("I", "A Scandal in Bohemia opens the collection."),
            ("II", "The Red-Headed League follows."),
            ("III", "A Case of Identity comes third."),
        ],
    )

    detailed = await SummarizationService().build_assembled_summary(doc_id, "detailed")

    assert detailed is not None
    assert "A Scandal in Bohemia opens the collection." in detailed


@pytest.mark.asyncio
async def test_assembled_summaries_never_invent_a_heading(test_db):
    """I-30: an unlabelled section gets no heading, not a numbered placeholder."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["doc body"], [5])
    await _insert_section_summaries(
        factory, doc_id, [("", f"Unlabelled finding {i}.") for i in range(4)]
    )

    svc = SummarizationService()
    detailed = await svc.build_assembled_summary(doc_id, "detailed")

    assert detailed is not None
    assert "#" not in detailed
    assert "Section" not in detailed


@pytest.mark.asyncio
async def test_assembled_key_points_cover_every_chapter_or_defer_to_the_llm(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["doc body"], [5])
    await _insert_section_summaries(factory, doc_id, _CHAPTERED)

    svc = SummarizationService()
    key_points = await svc.build_assembled_summary(doc_id, "executive")

    assert key_points is not None
    assert "**Chapter 1. Introduction to RAG**: RAG combines retrieval" in key_points
    assert "**Chapter 2. Scaling RAG**: Scaling requires hybrid search" in key_points
    for absent in ("Praise", "Preface", "Figure 1-1", "Index"):
        assert absent not in key_points

    flat_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, flat_id, ["doc body"], [5])
    await _insert_section_summaries(
        factory, flat_id, [(f"Topic {i}", f"Finding {i}.") for i in range(20)]
    )
    assert await svc.build_assembled_summary(flat_id, "executive") is None


@pytest.mark.asyncio
async def test_get_cached_does_not_rewrite_stored_summaries(test_db):
    """Opening a document reads summaries; it never replaces one the user has."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc_and_chunks(factory, tmp_path, doc_id, ["doc body"], [5])
    stored = "- One idea.\n- Another idea."
    async with factory() as session:
        session.add(
            SummaryModel(id=str(uuid.uuid4()), document_id=doc_id, mode="executive", content=stored)
        )
        await session.commit()
    await _insert_section_summaries(factory, doc_id, _CHAPTERED)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/summarize/{doc_id}/cached")

    assert resp.status_code == 200
    summaries = resp.json()["summaries"]
    assert summaries["executive"]["content"] == stored
    assert "detailed" not in summaries
    async with factory() as session:
        rows = (
            (await session.execute(select(SummaryModel).where(SummaryModel.document_id == doc_id)))
            .scalars()
            .all()
        )
    assert [r.content for r in rows] == [stored]
