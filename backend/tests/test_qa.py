"""Tests for QAService and POST /qa endpoint.

V2: stream_answer() delegates to the LangGraph chat router.  Integration tests
that exercise stream_answer() now mock app.runtime.chat_graph.get_chat_graph
with a mock graph whose ainvoke() returns a pre-built result dict.

Pure helper-function tests (_split_response, _build_context, etc.) are
unchanged — they test stateless functions that are still in qa.py.
"""

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, QAHistoryModel
from app.runtime.chat_nodes._shared import _COMPARATIVE_SYSTEM, _RELATIONAL_SYSTEM
from app.services.qa import (
    NOT_FOUND_SENTINEL,
    QA_CREATIVE_SYSTEM_PROMPT,
    QA_CREATIVE_TEMPERATURE,
    QA_FACTUAL_SYSTEM_PROMPT,
    QA_SYSTEM_PROMPT,
    QAService,
    _build_context,
    _drop_ungrounded_citations,
    _enrich_citation_titles,
    _excerpt_from_chunk,
    _gate_and_rank_citations,
    _resolve_marker_citations,
    _should_use_summary,
    _split_response,
)
from app.types import ScoredChunk

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


async def _insert_doc(factory, tmp_path: Path, doc_id: str, title: str = "Test Doc") -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title=title,
                format="txt",
                content_type="notes",
                word_count=100,
                page_count=2,
                file_path=str(tmp_path / "doc.txt"),
                stage="complete",
            )
        )
        await session.commit()


def _make_chunk(doc_id: str, text: str = "chunk text", section: str = "Intro") -> ScoredChunk:
    return ScoredChunk(
        chunk_id=str(uuid.uuid4()),
        document_id=doc_id,
        text=text,
        section_heading=section,
        page=1,
        score=0.9,
        source="vector",
    )


def _make_graph_result(
    *,
    answer: str = "The answer.",
    citations: list | None = None,
    confidence: str = "high",
    not_found: bool = False,
    chunks: list | None = None,
    intent: str = "factual",
) -> dict:
    """Build a mock graph result that matches ChatState shape."""
    return {
        "question": "",
        "doc_ids": [],
        "scope": "single",
        "model": None,
        "intent": intent,
        "rewritten_question": None,
        "chunks": chunks or [],
        "section_context": None,
        "answer": answer,
        "citations": citations or [],
        "confidence": confidence,
        "not_found": not_found,
    }


def _make_mock_graph(result: dict) -> MagicMock:
    """Return a mock graph whose ainvoke returns `result`."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=result)
    return mock_graph


async def _async_iter(items):
    for item in items:
        yield item


# _split_response — unit tests (unchanged)


def test_split_response_extracts_answer_and_citations():
    citations = [{"document_title": "Bio", "section_heading": "Cells", "page": 1, "excerpt": "..."}]
    full_text = "The cell is alive." + json.dumps({"citations": citations, "confidence": "high"})
    answer, parsed_citations, confidence = _split_response(full_text)
    assert answer == "The cell is alive."
    assert len(parsed_citations) == 1
    assert parsed_citations[0]["document_title"] == "Bio"
    assert confidence == "high"


def test_split_response_no_json_returns_full_text():
    full_text = "The answer is here."
    answer, citations, confidence = _split_response(full_text)
    assert answer == full_text
    assert citations == []
    assert confidence == "low"


def test_split_response_medium_confidence():
    citations: list = []
    full_text = "Partial answer." + json.dumps({"citations": citations, "confidence": "medium"})
    _, _, confidence = _split_response(full_text)
    assert confidence == "medium"


def test_split_response_malformed_json_returns_empty_citations():
    full_text = 'Answer text.{"citations": [invalid json'
    answer, citations, confidence = _split_response(full_text)
    assert citations == []
    assert confidence == "low"


def test_split_response_strips_json_label_line():
    citations = [{"document_title": "Bio", "section_heading": "Cells", "page": 1, "excerpt": "..."}]
    full_text = "The cell is the basic unit of life.\nJSON:\n" + json.dumps(
        {"citations": citations, "confidence": "high"}
    )
    answer, _, _ = _split_response(full_text)
    assert answer == "The cell is the basic unit of life."


# Truncated-generation salvage: local models sometimes embed the whole answer
# in a JSON block and then hit the token limit mid-block (done_reason=length).
# The answer must be recovered, not discarded.


def test_split_response_salvages_truncated_style_b_answer():
    embedded = (
        "Machine learning learns feature transformations from data, while deep learning "
        "stacks many neural layers to learn hierarchical representations end to end."
    )
    full_text = '{"answer": "' + embedded + '", "citations": [{"document_ti'
    answer, citations, confidence = _split_response(full_text)
    assert answer == embedded
    assert citations == []
    assert confidence == "medium"


def test_split_response_salvage_beats_stray_heading_prose():
    embedded = (
        "Use classical machine learning for small tabular datasets where interpretability "
        "matters; choose deep learning for perception tasks with large datasets."
    )
    full_text = "**Machine Learning:**\n" + '{"answer": "' + embedded + "  "
    answer, _, confidence = _split_response(full_text)
    assert answer == embedded
    assert confidence == "medium"


def test_split_response_salvage_unescapes_json_string():
    full_text = '{"answer": "Line one.\\nHe said \\"deep\\" learning.'
    answer, _, _ = _split_response(full_text)
    assert answer == 'Line one.\nHe said "deep" learning.'


def test_split_response_strips_leaked_citations_heading():
    """A markdown 'Citations:' heading the model writes before its JSON must not
    leak into the answer body."""
    prose = "Odysseus is inferred to hold authority in Ithaca."
    full_text = prose + "\n\n**Citations:**\n" + json.dumps({"citations": [], "confidence": "low"})
    answer, _, _ = _split_response(full_text)
    assert answer == prose
    assert "Citations" not in answer


def test_split_response_drops_placeholder_citations():
    """Placeholder citations (prompt format example echoed verbatim) are dropped
    so they never render as a '... · p.0' chip; real ones survive."""
    full_text = "An answer." + json.dumps(
        {
            "citations": [
                {"document_title": "...", "section_heading": "...", "page": 0, "excerpt": "..."},
                {"document_title": "the_odyssey", "page": 4, "excerpt": "Ithaca is fertile."},
            ],
            "confidence": "medium",
        }
    )
    answer, citations, _ = _split_response(full_text)
    assert answer == "An answer."
    assert len(citations) == 1
    assert citations[0]["document_title"] == "the_odyssey"


_TIME_MACHINE_GROUNDING = [
    "Within was a small apartment, and on a raised place in the corner of this was "
    "the Time Machine. I had the model fragments in my pocket.",
    "At once, like a lash across the face, came the possibility of losing my own age, "
    "of being left helpless in this strange new world.",
]


def test_drop_ungrounded_keeps_verbatim_excerpt():
    """A quote copied from the grounding is what a citation is supposed to be."""
    citations = [
        {"excerpt": "on a raised place in the corner of this was the Time Machine"}
    ]
    assert _drop_ungrounded_citations(citations, _TIME_MACHINE_GROUNDING) == citations


def test_drop_ungrounded_drops_model_narration():
    """Measured: the model wrote its own summary of events into `excerpt`, which
    renders as a source chip quoting a sentence the book does not contain."""
    citations = [
        {
            "excerpt": (
                "After the mysterious disappearance of the time machine, everyone is "
                "silent for a moment. Filby expresses disbelief."
            )
        }
    ]
    assert _drop_ungrounded_citations(citations, _TIME_MACHINE_GROUNDING) == []


def test_drop_ungrounded_drops_commentary_about_the_context():
    """Measured, and the worst of the class: the chip quotes the model talking
    about its own retrieval. The eval judge scored this one `yes`."""
    citations = [
        {
            "excerpt": (
                "The context does not provide specific details about the physical "
                "layout of the dining area. However, given that..."
            )
        }
    ]
    assert _drop_ungrounded_citations(citations, _TIME_MACHINE_GROUNDING) == []


def test_drop_ungrounded_drops_source_text_absent_from_the_grounding():
    """Real prose from the document, recited from the model's own memory rather
    than retrieved. The answer was not grounded on it and no chunk links to it."""
    citations = [
        {
            "excerpt": (
                "You can move about in all directions of space but cannot move "
                "about in time."
            )
        }
    ]
    assert _drop_ungrounded_citations(citations, _TIME_MACHINE_GROUNDING) == []


def test_drop_ungrounded_tolerates_repunctuation_and_ellipsis():
    """Models re-punctuate and stitch quotes; a contiguous run still identifies
    the passage, and demanding an exact string would drop real citations."""
    citations = [
        {"excerpt": "came the possibility of losing my own age ... left helpless"}
    ]
    assert len(_drop_ungrounded_citations(citations, _TIME_MACHINE_GROUNDING)) == 1


def test_drop_ungrounded_keeps_everything_when_there_is_no_grounding():
    """With no grounding text there is nothing to verify against, and the
    pass-through path never retrieved chunks in the first place."""
    citations = [{"excerpt": "Anything at all."}]
    assert _drop_ungrounded_citations(citations, []) == citations


def test_drop_ungrounded_keeps_citation_without_an_excerpt():
    """A chip carrying only a heading makes no quoting claim to falsify."""
    citations = [{"document_title": "the_odyssey", "section_heading": "Book I"}]
    assert _drop_ungrounded_citations(citations, _TIME_MACHINE_GROUNDING) == citations


@pytest.mark.parametrize(
    "prompt",
    [
        QA_SYSTEM_PROMPT,
        QA_CREATIVE_SYSTEM_PROMPT,
        QA_FACTUAL_SYSTEM_PROMPT,
        _RELATIONAL_SYSTEM,
        _COMPARATIVE_SYSTEM,
    ],
)
def test_every_citation_prompt_cites_by_marker(prompt):
    """All five citation-bearing prompts, not just the three in this module: the
    relational and comparative prompts live in chat_nodes/_shared.py and kept the
    old free-text excerpt format after the first pass at I-33."""
    assert '{"source":"S1"}' in prompt
    assert "Do not copy the passage text" in prompt
    assert '"excerpt":"..."' not in prompt


_MARKER_CHUNKS = [
    {
        "chunk_id": "c1",
        "document_id": "d1",
        "text": (
            "The Time Traveller smiled. Within was a small apartment, and on a raised "
            "place in the corner of this was the Time Machine."
        ),
        "section_heading": "XII",
        "page": 7,
    },
    {
        "chunk_id": "c2",
        "document_id": "d1",
        "text": "Fruit, by the bye, was all their diet.",
        "section_heading": "IV",
        "page": 3,
    },
]


def test_marker_citation_fills_excerpt_from_the_named_chunk():
    """The model names a source; the excerpt comes from that chunk, so it is
    verbatim by construction rather than by instruction."""
    resolved, unresolved = _resolve_marker_citations(
        [{"source": "S2"}], _MARKER_CHUNKS, {"d1": "the_time_machine"}
    )
    assert unresolved == 0
    assert resolved[0]["excerpt"] == "Fruit, by the bye, was all their diet."
    assert resolved[0]["chunk_id"] == "c2"
    assert resolved[0]["page"] == 3
    assert resolved[0]["document_title"] == "the_time_machine"


def test_marker_citation_quote_only_locates_never_supplies_text():
    """A quote the model types is a pointer into the chunk. Even when it is a
    paraphrase, what reaches the user is the chunk's own words. A chunk within the
    length budget is shown whole -- cropping a short passage hides context for no
    gain, and the window only has to be chosen when the budget forces a choice."""
    resolved, _ = _resolve_marker_citations(
        [{"source": "S1", "quote": "a raised place in the corner"}],
        _MARKER_CHUNKS,
        {},
    )
    assert "a raised place in the corner" in resolved[0]["excerpt"]
    assert resolved[0]["excerpt"] in " ".join(_MARKER_CHUNKS[0]["text"].split())


def test_marker_citation_naming_a_nonexistent_source_is_dropped():
    """`[S9]` when 2 passages were shown claims a source that does not exist."""
    resolved, unresolved = _resolve_marker_citations(
        [{"source": "S9"}], _MARKER_CHUNKS, {}
    )
    assert resolved == []
    assert unresolved == 1


def test_marker_citation_accepts_bare_and_bracketed_forms():
    """Small models write S1, 1, and [S1] interchangeably."""
    for form in ("S1", "1", "[S1]", " s1 "):
        resolved, unresolved = _resolve_marker_citations(
            [{"source": form}], _MARKER_CHUNKS, {}
        )
        assert unresolved == 0, form
        assert resolved[0]["chunk_id"] == "c1", form


def test_legacy_excerpt_citation_passes_through_untouched():
    """Prompts and models outside this path still emit excerpt citations; those
    stay on the I-33 verification path rather than being dropped as unresolvable."""
    legacy = [{"document_title": "the_odyssey", "excerpt": "Ithaca is fertile."}]
    resolved, unresolved = _resolve_marker_citations(legacy, _MARKER_CHUNKS, {})
    assert resolved == legacy
    assert unresolved == 0


def test_marker_citation_is_not_mistaken_for_a_placeholder():
    """A marker citation carries neither title nor excerpt until it is resolved,
    which is exactly the shape the placeholder guard drops."""
    full_text = "An answer." + json.dumps(
        {"citations": [{"source": "S1"}], "confidence": "high"}
    )
    _, citations, _ = _split_response(full_text)
    assert citations == [{"source": "S1"}]


def test_split_response_truncated_style_a_keeps_prose_with_medium_confidence():
    prose = (
        "Machine learning covers the broad family of data-driven algorithms, whereas deep "
        "learning is the neural-network subset suited to perception-scale data."
    )
    full_text = prose + '\n{"citations": [{"document_title": "d2l", "section_head'
    answer, citations, confidence = _split_response(full_text)
    assert answer == prose
    assert citations == []
    assert confidence == "medium"


def test_split_response_strips_instruction_echo():
    citations: list = []
    full_text = "ONLY JSON (no prose inside the JSON, do not repeat the answer):\n" + json.dumps(
        {"citations": citations, "confidence": "medium"}
    )
    answer, _, _ = _split_response(full_text)
    assert answer == ""


def test_split_response_strips_here_is_json_label():
    citations: list = []
    full_text = "Alice explores Wonderland.\nHere is a JSON response:\n" + json.dumps(
        {"citations": citations, "confidence": "high"}
    )
    answer, _, _ = _split_response(full_text)
    assert answer == "Alice explores Wonderland."


def test_split_response_style_b_answer_in_json():
    citations = [{"document_title": "Gita", "section_heading": "Ch1", "page": 1, "excerpt": "..."}]
    full_text = json.dumps(
        {"answer": "Arjuna questions his duty.", "citations": citations, "confidence": "medium"}
    )
    answer, parsed_citations, confidence = _split_response(full_text)
    assert answer == "Arjuna questions his duty."
    assert len(parsed_citations) == 1
    assert confidence == "medium"


def test_split_response_prose_with_colon_not_stripped():
    citations: list = []
    full_text = "The main themes are:\n- Adventure\n- Mystery.\n" + json.dumps(
        {"citations": citations, "confidence": "medium"}
    )
    answer, _, _ = _split_response(full_text)
    assert "main themes" in answer


# _build_context — unit tests (unchanged)


def test_build_context_includes_document_title():
    chunk = _make_chunk("doc1", text="ATP is produced in the mitochondria.", section="Energy")
    context = _build_context([chunk], {"doc1": "Cell Biology"})
    assert "Cell Biology" in context
    assert "Energy" in context
    assert "ATP is produced" in context


def test_build_context_fallback_uses_document_id():
    chunk = _make_chunk("doc-unknown")
    context = _build_context([chunk], {})
    assert "doc-unknown" in context


def test_qa_system_prompt_contains_not_found_sentinel():
    assert NOT_FOUND_SENTINEL in QA_SYSTEM_PROMPT


def test_qa_system_prompt_mentions_citations():
    assert "citations" in QA_SYSTEM_PROMPT


# QAService.stream_answer — normal flow
# V2: mock the chat graph (graph.ainvoke returns pre-built result)


@pytest.mark.asyncio
async def test_stream_emits_offline_notice_when_cloud_unreachable(test_db, monkeypatch):
    """When routing would go to the cloud but the provider is unreachable, the Ask
    stream tells the user it is answering locally."""
    from app.services import connectivity, settings_service

    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Biology Book")

    monkeypatch.setattr(
        settings_service, "get_effective_routing", lambda *a, **k: ("openai/gpt-5-mini", None)
    )
    connectivity.reset_cache()
    monkeypatch.setattr(connectivity, "provider_reachable", lambda model: False)

    result = _make_graph_result(answer="Local answer.", citations=[])
    mock_graph = _make_mock_graph(result)
    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        events = [e async for e in QAService().stream_answer("q?", [doc_id], "single", None)]

    notices = [json.loads(e[len("data: ") :]) for e in events if '"notice"' in e]
    assert notices, "expected an offline notice event"
    assert notices[0]["level"] == "offline"


@pytest.mark.asyncio
async def test_stream_no_notice_when_provider_reachable(test_db, monkeypatch):
    from app.services import connectivity, settings_service

    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Biology Book")

    monkeypatch.setattr(
        settings_service, "get_effective_routing", lambda *a, **k: ("openai/gpt-5-mini", None)
    )
    connectivity.reset_cache()
    monkeypatch.setattr(connectivity, "provider_reachable", lambda model: True)

    result = _make_graph_result(answer="Cloud answer.", citations=[])
    mock_graph = _make_mock_graph(result)
    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        events = [e async for e in QAService().stream_answer("q?", [doc_id], "single", None)]

    assert not any('"notice"' in e for e in events)


@pytest.mark.asyncio
async def test_stream_yields_token_events_for_answer(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Biology Book")

    citations = [
        {"document_title": "Biology Book", "section_heading": "Cells", "page": 1, "excerpt": "..."}
    ]
    result = _make_graph_result(answer="Mitochondria produces ATP.", citations=citations)
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e
            async for e in svc.stream_answer("What does mitochondria do?", [doc_id], "single", None)
        ]

    assert len(events) >= 2
    token_events = [e for e in events if '"token"' in e]
    assert len(token_events) > 0
    for event in token_events:
        assert event.startswith("data: ")
        payload = json.loads(event[len("data: ") :])
        assert "token" in payload


@pytest.mark.asyncio
async def test_stream_final_event_contains_citations(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Physics")

    citations = [
        {"document_title": None, "section_heading": "Forces", "page": 5, "excerpt": "F=ma"}
    ]
    result = _make_graph_result(
        answer="Force equals mass times acceleration.",
        citations=citations,
        confidence="high",
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e
            async for e in svc.stream_answer("What is Newton's 2nd law?", [doc_id], "single", None)
        ]

    done_payload = json.loads(events[-1][len("data: ") :])
    assert done_payload["done"] is True
    assert done_payload["confidence"] == "high"
    assert len(done_payload["citations"]) == 1
    assert "qa_id" in done_payload


@pytest.mark.asyncio
async def test_stream_stores_qa_in_database(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "History")

    result = _make_graph_result(answer="Napoleon was French.", confidence="medium")
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [e async for e in svc.stream_answer("Who was Napoleon?", [doc_id], "single", None)]

    done_payload = json.loads(events[-1][len("data: ") :])
    qa_id = done_payload["qa_id"]

    async with factory() as session:
        result_row = await session.execute(select(QAHistoryModel).where(QAHistoryModel.id == qa_id))
        stored = result_row.scalar_one_or_none()

    assert stored is not None
    assert stored.question == "Who was Napoleon?"
    assert "Napoleon" in stored.answer
    assert stored.confidence == "medium"


# QAService.stream_answer — NOT_FOUND flow


@pytest.mark.asyncio
async def test_not_found_yields_not_found_event(test_db):
    _engine, factory, tmp_path = test_db

    # Chunks present but LLM said NOT_FOUND → not_found event (not error event)
    result = _make_graph_result(
        answer="",
        not_found=True,
        chunks=[
            {
                "chunk_id": "c1",
                "document_id": "d1",
                "text": "x",
                "section_heading": "S",
                "page": 1,
                "score": 0.5,
                "source": "vector",
            }
        ],
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [e async for e in svc.stream_answer("Unknown question?", None, "all", None)]

    assert len(events) == 1
    payload = json.loads(events[0][len("data: ") :])
    assert payload["done"] is True
    assert payload["not_found"] is True


@pytest.mark.asyncio
async def test_not_found_no_token_events(test_db):
    _engine, factory, tmp_path = test_db

    result = _make_graph_result(answer="", not_found=True, chunks=[])
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [e async for e in svc.stream_answer("Unknowable?", None, "all", None)]

    token_events = [e for e in events if '"token"' in e]
    assert len(token_events) == 0


# POST /qa — HTTP endpoint integration tests


@pytest.mark.asyncio
async def test_endpoint_returns_sse_content_type(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id)

    result = _make_graph_result(answer="The answer is 42.")
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/qa", json={"question": "What is the answer?"})

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_endpoint_not_found_response(test_db):
    """No chunks → no_context error event."""
    _engine, factory, tmp_path = test_db

    result = _make_graph_result(answer="", not_found=True, chunks=[])
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/qa", json={"question": "Impossible question?"})

    assert resp.status_code == 200
    events = [line for line in resp.text.splitlines() if line.startswith("data: ")]
    assert len(events) == 1
    payload = json.loads(events[0][len("data: ") :])
    assert payload["error"] == "no_context"
    assert payload["done"] is True


@pytest.mark.asyncio
async def test_endpoint_all_scope_produces_answer(test_db):
    """scope='all' endpoint call produces a valid SSE response."""
    _engine, factory, tmp_path = test_db

    result = _make_graph_result(answer="An answer.", intent="factual")
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/qa",
                json={"question": "Any question?", "scope": "all", "document_ids": ["doc-1"]},
            )

    assert resp.status_code == 200
    events = [line for line in resp.text.splitlines() if line.startswith("data: ")]
    done_events = [e for e in events if '"done"' in e]
    assert len(done_events) >= 1


# QAService.stream_answer — error flows


@pytest.mark.asyncio
async def test_qa_no_context(test_db):
    """Graph returns not_found=True with no chunks → 1 SSE event with error='no_context'."""
    _engine, factory, tmp_path = test_db

    result = _make_graph_result(answer="", not_found=True, chunks=[])
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer("anything", ["nonexistent-doc-id"], "single", None)
        ]

    data_lines = [e for e in events if e.startswith("data: ")]
    assert len(data_lines) == 1
    payload = json.loads(data_lines[0][len("data: ") :])
    assert payload["error"] == "no_context"
    assert payload["done"] is True


@pytest.mark.asyncio
async def test_qa_ollama_offline(test_db):
    """Graph raises (LLM unavailable) → SSE event with error='llm_unavailable'."""
    _engine, factory, tmp_path = test_db

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(side_effect=Exception("connection refused"))

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [e async for e in svc.stream_answer("What is this about?", None, "all", None)]

    data_lines = [e for e in events if e.startswith("data: ")]
    assert len(data_lines) == 1
    payload = json.loads(data_lines[0][len("data: ") :])
    assert payload["error"] == "llm_unavailable"
    assert payload["type"] == "error"
    assert payload["done"] is True


@pytest.mark.asyncio
async def test_s103_ollama_offline_sse_type_error(test_db):
    """S103: litellm.acompletion raises ServiceUnavailableError during Path B streaming.

    POST /qa must return HTTP 200 (SSE) with a single data event where:
    - type == 'error'
    - message contains 'Ollama is unreachable'
    - done == True
    No HTTP 500 must be returned; the SSE connection closes cleanly.
    """
    import litellm as _litellm
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id)

    # Graph returns a state that requires Path B (LLM streaming): _llm_prompt is set.
    result_with_prompt = {
        "answer": "",
        "citations": [],
        "confidence": "low",
        "not_found": False,
        "chunks": [],
        "_llm_prompt": "Answer the question.",
        "_system_prompt": "",
        "intent": "factual",
    }
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=result_with_prompt)

    # Simulate Ollama offline: acompletion raises ServiceUnavailableError.
    offline_error = _litellm.ServiceUnavailableError(
        message="Connection refused", llm_provider="ollama", model="ollama/mistral"
    )
    with (
        patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph),
        patch("litellm.acompletion", new=AsyncMock(side_effect=offline_error)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/qa",
                json={"question": "What is this about?", "document_ids": [doc_id]},
            )

    assert resp.status_code == 200, "Must return 200 (SSE), not 500"
    assert "text/event-stream" in resp.headers.get("content-type", "")

    data_lines = [ln for ln in resp.text.splitlines() if ln.startswith("data: ")]
    assert len(data_lines) == 1, f"Expected 1 error event, got: {data_lines}"
    payload = json.loads(data_lines[0][len("data: ") :])
    assert payload.get("type") == "error", f"Expected type='error', got: {payload}"
    assert "LLM unreachable" in payload.get("message", ""), payload
    assert payload.get("done") is True


@pytest.mark.asyncio
async def test_s103_api_connection_error_sse_type_error(test_db):
    """S103: litellm.acompletion raises APIConnectionError during Path B streaming.

    APIConnectionError fires when the TCP connection is refused outright (as opposed
    to ServiceUnavailableError when the server returns 503). Both should yield the
    same type=error SSE event.
    """
    import litellm as _litellm

    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id)

    result_with_prompt = {
        "answer": "",
        "citations": [],
        "confidence": "low",
        "not_found": False,
        "chunks": [],
        "_llm_prompt": "Answer the question.",
        "_system_prompt": "",
        "intent": "factual",
    }
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=result_with_prompt)

    conn_error = _litellm.APIConnectionError(
        message="Connection refused", llm_provider="ollama", model="ollama/mistral"
    )
    with (
        patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph),
        patch("litellm.acompletion", new=AsyncMock(side_effect=conn_error)),
    ):
        svc = QAService()
        events = [e async for e in svc.stream_answer("What is this?", [doc_id], "single", None)]

    data_lines = [e for e in events if e.startswith("data: ")]
    assert len(data_lines) == 1
    payload = json.loads(data_lines[0][len("data: ") :])
    assert payload.get("type") == "error"
    assert "LLM unreachable" in payload.get("message", "")
    assert payload.get("done") is True


@pytest.mark.asyncio
async def test_qa_with_mock_llm(test_db):
    """Happy-path: graph returns answer + citations → token events + done event."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Time Machine")

    citations = [
        {
            "document_title": "Time Machine",
            "section_heading": "Chapter 1",
            "page": 3,
            "excerpt": "...",
        }
    ]
    result = _make_graph_result(
        answer="The Time Traveller invented a machine.",
        citations=citations,
        confidence="high",
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e
            async for e in svc.stream_answer("What is the time machine?", [doc_id], "single", None)
        ]

    token_events = [e for e in events if '"token"' in e]
    assert len(token_events) >= 1

    done_payload = json.loads(events[-1][len("data: ") :])
    assert done_payload["done"] is True
    assert len(done_payload["citations"]) >= 1


# S61 — _enrich_citation_titles unit tests (unchanged)


def test_enrich_citation_titles_single_scope_clears_title():
    chunk = _make_chunk("doc-a", section="Intro")
    citations = [{"document_title": "Some Book", "section_heading": "Intro", "page": 1}]
    result = _enrich_citation_titles(citations, [chunk], {"doc-a": "Some Book"}, "single")
    assert result[0]["document_title"] is None


def test_enrich_citation_titles_all_scope_populates_from_chunks():
    chunk = _make_chunk("doc-b", section="Chapter 2")
    chunk.page = 5
    citations = [{"document_title": "", "section_heading": "Chapter 2", "page": 5}]
    result = _enrich_citation_titles(citations, [chunk], {"doc-b": "The Odyssey"}, "all")
    assert result[0]["document_title"] == "The Odyssey"


@pytest.mark.asyncio
async def test_citations_passed_through_from_graph(test_db):
    """Citations returned by graph are passed through in the done event."""
    _engine, factory, tmp_path = test_db
    doc_id_a = str(uuid.uuid4())
    doc_id_b = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id_a, "Alice in Wonderland")
    await _insert_doc(factory, tmp_path, doc_id_b, "The Odyssey")

    citations = [
        {
            "document_title": "Alice in Wonderland",
            "section_heading": "Ch1",
            "page": 1,
            "excerpt": "...",
        },
        {
            "document_title": "The Odyssey",
            "section_heading": "Book I",
            "page": 10,
            "excerpt": "...",
        },
    ]
    result = _make_graph_result(
        answer="Comparison answer.", citations=citations, confidence="medium"
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [e async for e in svc.stream_answer("Compare the two books?", None, "all", None)]

    done_payload = json.loads(events[-1][len("data: ") :])
    assert done_payload["done"] is True
    titles = {c["document_title"] for c in done_payload["citations"]}
    assert "Alice in Wonderland" in titles
    assert "The Odyssey" in titles


@pytest.mark.asyncio
async def test_citations_no_title_for_single_scope(test_db):
    """Graph (synthesize_node) already cleared document_title for scope=single."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Physics Textbook")

    citations = [
        {"document_title": None, "section_heading": "Forces", "page": 3, "excerpt": "F=ma"}
    ]
    result = _make_graph_result(
        answer="Force equals mass times acceleration.",
        citations=citations,
        confidence="high",
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e
            async for e in svc.stream_answer("What is Newton's 2nd law?", [doc_id], "single", None)
        ]

    done_payload = json.loads(events[-1][len("data: ") :])
    assert done_payload["done"] is True
    assert all(c["document_title"] is None for c in done_payload["citations"])


# S71 — _should_use_summary unit tests (unchanged)


def test_should_use_summary_matches_keywords():
    assert _should_use_summary("Can you summarize this document?") is True
    assert _should_use_summary("Give me an overview of the book") is True
    assert _should_use_summary("What are the key points?") is True
    assert _should_use_summary("What is this about?") is True


def test_should_use_summary_no_match():
    assert _should_use_summary("Who is Achilles?") is False
    assert _should_use_summary("What happens in chapter 3?") is False


@pytest.mark.asyncio
async def test_qa_summary_question_routes_via_graph(test_db):
    """Summary-intent question: S77 summary_node stub returns stub answer string."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, title="Iliad")

    result = _make_graph_result(
        answer="[summary_node stub]",
        confidence="high",
        intent="summary",
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e
            async for e in svc.stream_answer(
                "Can you summarize this document?", [doc_id], "single", None
            )
        ]

    done_payload = json.loads(events[-1][len("data: ") :])
    assert done_payload["done"] is True
    assert "summary_node" in done_payload["answer"]


# Creative mode — grounded generative synthesis (UI toggle + creative prompt + higher temp)


def _make_llm_capturing_generate():
    """Return (mock_llm, calls) where mock_llm.generate records its kwargs and
    streams two plain tokens (no stop markers, so a single iteration suffices)."""
    calls: list[dict] = []

    async def _generate(prompt, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        return _async_iter(["Once upon ", "a time."])

    mock_llm = MagicMock()
    mock_llm.generate = _generate
    return mock_llm, calls


@pytest.mark.asyncio
async def test_creative_mode_uses_creative_prompt_and_higher_temperature(test_db):
    """creative=True (Path B) swaps in the creative system prompt and raises temperature."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "My Daily Thoughts")

    result = {
        **_make_graph_result(answer="", intent="exploratory"),
        "_llm_prompt": "Context:\n\n...\n\nQuestion: Write a kids story",
        "_system_prompt": QA_SYSTEM_PROMPT,
    }
    mock_graph = _make_mock_graph(result)
    mock_llm, calls = _make_llm_capturing_generate()

    with (
        patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        svc = QAService()
        _ = [
            e
            async for e in svc.stream_answer(
                "Write a kids story based on the content", [doc_id], "single", None, creative=True
            )
        ]

    assert len(calls) == 1
    assert calls[0]["system"] == QA_CREATIVE_SYSTEM_PROMPT
    assert calls[0]["temperature"] == QA_CREATIVE_TEMPERATURE


@pytest.mark.asyncio
async def test_default_mode_preserves_grounded_prompt_and_no_temperature(test_db):
    """creative defaults to False: the ground-truth prompt and temperature=None are untouched."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Physics")

    result = {
        **_make_graph_result(answer="", intent="factual"),
        "_llm_prompt": "Context:\n\n...\n\nQuestion: What is force?",
        "_system_prompt": QA_SYSTEM_PROMPT,
    }
    mock_graph = _make_mock_graph(result)
    mock_llm, calls = _make_llm_capturing_generate()

    with (
        patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        svc = QAService()
        _ = [e async for e in svc.stream_answer("What is force?", [doc_id], "single", None)]

    assert len(calls) == 1
    assert calls[0]["system"] == QA_SYSTEM_PROMPT
    assert calls[0]["temperature"] is None


def test_repeated_marker_yields_one_chip():
    """Two markers naming the same passage are one source, not two chips."""
    resolved, unresolved = _resolve_marker_citations(
        [{"source": "S1"}, {"source": "S1"}, {"source": "S2"}], _MARKER_CHUNKS, {}
    )
    assert [c["chunk_id"] for c in resolved] == ["c1", "c2"]
    assert unresolved == 0


def test_citation_cap_matches_the_sources_panel():
    """Relieved of retyping the quote the model cites freely -- a 737-character
    answer came back with 12 chips. Both lists under one answer share the cap."""
    from app.services.qa import MAX_CITATIONS

    assert MAX_CITATIONS == 5
    many = [
        {
            "chunk_id": f"c{i}",
            "document_id": "d1",
            "text": f"Passage number {i} of the source material.",
            "section_heading": "H",
            "page": i,
        }
        for i in range(1, 13)
    ]
    resolved, _ = _resolve_marker_citations(
        [{"source": f"S{i}"} for i in range(1, 13)], many, {}
    )
    # The resolver dedupes; the cap itself is applied where both paths merge.
    assert len(resolved) == 12
    assert len(resolved[:MAX_CITATIONS]) == 5


_SCORED_CHUNKS = [
    {"chunk_id": "hi", "document_id": "d1", "text": "Strongly relevant passage.",
     "section_heading": "A", "page": 1, "score": 0.030},
    {"chunk_id": "mid", "document_id": "d1", "text": "Moderately relevant passage.",
     "section_heading": "B", "page": 2, "score": 0.020},
    {"chunk_id": "weak", "document_id": "d1", "text": "Barely related passage.",
     "section_heading": "C", "page": 3, "score": 0.004},
]


def _resolve_and_gate(sources):
    resolved, _ = _resolve_marker_citations(
        [{"source": s} for s in sources], _SCORED_CHUNKS, {}
    )
    return _gate_and_rank_citations(resolved)


def test_gate_drops_chips_far_below_the_best_source():
    """`paper` cited every answer it gave (coverage 1.0000) while under half the
    chips supported anything: the model cites what it was shown, not what carries
    the claim. The sources panel has always gated on relevance; chips now do too."""
    kept = _resolve_and_gate(["S1", "S2", "S3"])
    assert [c["chunk_id"] for c in kept] == ["hi", "mid"]


def test_gate_ranks_by_retrieval_score_not_citation_order():
    """The cap must keep the strongest sources, so ranking has to happen first --
    capping the model's emission order keeps whichever it happened to name first."""
    kept = _resolve_and_gate(["S3", "S2", "S1"])
    assert [c["chunk_id"] for c in kept] == ["hi", "mid"]


def test_gate_always_keeps_the_single_best_source():
    """An answer that retrieved something must never show zero sources because
    the gate was strict -- same rule source_citations follows."""
    only_weak = [dict(_SCORED_CHUNKS[2])]
    resolved, _ = _resolve_marker_citations([{"source": "S1"}], only_weak, {})
    kept = _gate_and_rank_citations(resolved)
    assert [c["chunk_id"] for c in kept] == ["weak"]


def test_gate_caps_at_max_citations():
    many = [
        {"chunk_id": f"c{i}", "document_id": "d1", "text": f"Passage {i}.",
         "section_heading": "H", "page": i, "score": 0.030}
        for i in range(1, 13)
    ]
    resolved, _ = _resolve_marker_citations(
        [{"source": f"S{i}"} for i in range(1, 13)], many, {}
    )
    assert len(_gate_and_rank_citations(resolved)) == 5


def test_gate_keeps_unrankable_legacy_citations():
    """A free-text excerpt citation carries no score and cannot be ranked; scoring
    it as zero would let the gate delete every citation from a non-marker prompt."""
    legacy = [{"document_title": "the_odyssey", "excerpt": "Ithaca is fertile."}]
    assert _gate_and_rank_citations(legacy) == legacy


def test_gate_strips_the_internal_score_key():
    """`_score` is plumbing for ranking, never part of the wire payload."""
    kept = _resolve_and_gate(["S1", "S2"])
    assert all("_score" not in c for c in kept)


_LONG_CHUNK = (
    "The Psychologist opened the discussion with a digression about the weather in "
    "Richmond, which had been unkind all that week and gave everyone something to "
    "complain about over dinner. The company argued for some minutes about nothing "
    "in particular, as companies do. Then the Time Traveller said the machine had "
    "travelled into futurity, and that the levers controlled the direction of its "
    "flight through time. He showed them the small ivory lever that sent it forward. "
    "Afterwards the conversation turned again to trivial matters and the fire."
)


def test_excerpt_shows_the_part_that_bears_on_the_answer():
    """A chunk is sized for the embedder, so the sentence carrying the claim sits
    anywhere in it. Cutting the head showed the wrong text: measured over `book`
    chips, 12 of 15 excerpts were head cuts and judging them scored 0.5667 against
    0.8667 for the same chips judged on their full chunk."""
    answer = "The levers controlled the direction of the machine's flight through time."
    excerpt = _excerpt_from_chunk(_LONG_CHUNK, "", answer)
    assert "levers controlled the direction" in excerpt
    assert "weather in Richmond" not in excerpt


def test_excerpt_prefers_the_models_own_pointer():
    """The quote hint outweighs general answer overlap: it is the model saying
    which sentence it meant."""
    answer = "They discussed several things over dinner."
    excerpt = _excerpt_from_chunk(_LONG_CHUNK, "small ivory lever", answer)
    assert "ivory lever" in excerpt


def test_excerpt_is_always_verbatim_from_the_chunk():
    """The hint and the answer only choose a window; neither may put words into
    the source. A paraphrased hint costs relevance, never fidelity."""
    excerpt = _excerpt_from_chunk(_LONG_CHUNK, "levers steered it forwards in time", "")
    body = excerpt.lstrip(".").strip().rstrip(".")
    assert body[:80] in " ".join(_LONG_CHUNK.split())


def test_excerpt_returns_short_chunks_whole():
    short = "Fruit, by the bye, was all their diet."
    assert _excerpt_from_chunk(short, "", "anything") == short


def test_excerpt_respects_the_length_budget():
    long_text = " ".join(f"Sentence number {i} about the subject." for i in range(200))
    assert len(_excerpt_from_chunk(long_text, "", "subject")) <= 340


def test_a_citation_excerpt_never_quotes_the_generated_section_summary():
    """I-33 says an excerpt is a quote the grounding contains. The packed `text`
    is not the grounding: `search_node` prefixes it with a machine-written
    section summary, so an excerpt cut from `text` can be presented to the reader
    as a quote from their document when the document never contained it."""
    from app.services.qa import _excerpt_from_chunk

    summary = "This section argues that redundancy masks independent faults."
    document = "The Eloi were small, and their manner was that of children."
    packed = f"### Chapter II\n{summary}\n---\n{document}"

    chunk = {"text": packed, "source_text": document}

    excerpt = _excerpt_from_chunk(
        chunk.get("source_text") or chunk.get("text", ""), "", "What were the Eloi like?"
    )

    assert excerpt
    assert excerpt in document
    assert "redundancy masks" not in excerpt
