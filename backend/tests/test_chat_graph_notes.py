"""Tests for the S92 'notes' intent path in the V2 chat graph.

Covers:
  1. classify_intent_heuristic returns 'notes' for notes-bearing queries
  2. No false positives: factual book queries do not route to notes_node
  3. route_node dispatches to 'notes_node' when intent='notes'
  4. notes_node formats '[From your notes]' prefix in section_context
  5. notes_node returns empty section_context when search returns no results
  6. Slow integration: two notes created, chat query finds them
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.runtime.chat_graph import notes_node, route_node
from app.services.intent import classify_intent_heuristic
from app.types import ChatState, NoteSearchResult

pytest_plugins = ["conftest_books"]

# Heuristic tests (pure function)


def test_heuristic_classifies_notes_intent():
    intent, confidence = classify_intent_heuristic("what did I note about Alice")
    assert intent == "notes"
    assert confidence >= 0.9


def test_heuristic_classifies_my_notes():
    intent, confidence = classify_intent_heuristic("in my notes about the White Rabbit")
    assert intent == "notes"


def test_heuristic_classifies_i_noted():
    intent, confidence = classify_intent_heuristic("I noted that Alice follows the rabbit")
    assert intent == "notes"


def test_heuristic_no_false_positive():
    """Factual book queries must not route to notes."""
    intent, _ = classify_intent_heuristic("what does Alice find in the garden")
    assert intent != "notes"


# route_node tests


def _make_minimal_state(**overrides) -> ChatState:
    base: dict = {
        "question": "test",
        "doc_ids": [],
        "scope": "all",
        "model": None,
        "intent": None,
        "rewritten_question": None,
        "chunks": [],
        "section_context": None,
        "answer": "",
        "citations": [],
        "confidence": "low",
        "not_found": False,
        "_llm_prompt": None,
        "_system_prompt": None,
        "retry_attempted": False,
        "primary_strategy": None,
        "conversation_history": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def test_route_node_notes_branch():
    state = _make_minimal_state(intent="notes")
    result = route_node(state)
    assert result == "notes_node"


def test_route_node_other_intents_unchanged():
    """Non-notes intents must not route to notes_node."""
    for intent in ("summary", "factual", "relational", "comparative", "exploratory"):
        state = _make_minimal_state(intent=intent, scope="single")
        result = route_node(state)
        assert result != "notes_node", f"intent={intent} incorrectly routed to notes_node"


# notes_node tests


@pytest.mark.asyncio
async def test_notes_node_formats_context():
    """notes_node formats results as '[From your notes] ...' in section_context."""
    mock_result = NoteSearchResult(
        note_id="n1",
        content="Alice meets Cheshire Cat",
        tags=[],
        group_name=None,
        document_id=None,
        score=0.9,
        source="fts",
    )
    mock_svc = MagicMock()
    mock_svc.search = AsyncMock(return_value=[mock_result])

    state = _make_minimal_state(question="what did I note about Cheshire Cat")

    with patch("app.services.note_search.get_note_search_service", return_value=mock_svc):
        result = await notes_node(state)

    assert "section_context" in result
    assert "[From your notes] Alice meets Cheshire Cat" in result["section_context"]
    assert result["chunks"] == []


@pytest.mark.asyncio
async def test_notes_node_empty_results():
    """notes_node returns empty section_context when search returns no results."""
    mock_svc = MagicMock()
    mock_svc.search = AsyncMock(return_value=[])

    state = _make_minimal_state(question="what did I write about xyz")

    with patch("app.services.note_search.get_note_search_service", return_value=mock_svc):
        result = await notes_node(state)

    assert result["chunks"] == []
    assert result.get("section_context") is None


@pytest.mark.asyncio
async def test_notes_node_multiple_results_joined():
    """notes_node joins multiple note results with double newline."""
    results = [
        NoteSearchResult("n1", "first note", [], None, None, 0.9, "fts"),
        NoteSearchResult("n2", "second note", [], None, None, 0.8, "fts"),
    ]
    mock_svc = MagicMock()
    mock_svc.search = AsyncMock(return_value=results)

    state = _make_minimal_state(question="what did I note about the rabbit")

    with patch("app.services.note_search.get_note_search_service", return_value=mock_svc):
        result = await notes_node(state)

    ctx = result["section_context"]
    assert "[From your notes] first note" in ctx
    assert "[From your notes] second note" in ctx


# Slow integration test


@pytest.mark.slow
def test_notes_chat_integration(all_books_ingested):
    """Create two notes, then chat query routes to notes_node and returns SSE stream."""
    with TestClient(app) as c:
        # Create two notes about Wonderland characters
        c.post("/notes", json={"content": "The Cheshire Cat grins and can disappear", "tags": []})
        c.post("/notes", json={"content": "The White Rabbit checks his pocket watch", "tags": []})

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].delta.content = "Your notes mention the Cheshire Cat and White Rabbit."
        mock_resp.__aiter__ = AsyncMock(return_value=iter([mock_resp]))

        # Mock LiteLLM to return a short streaming response
        async def _mock_stream(*args, **kwargs):
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = "Your notes mention Wonderland characters."

            async def _gen():
                yield chunk

            return _gen()

        with patch("litellm.acompletion", new=AsyncMock(side_effect=_mock_stream)):
            resp = c.post(
                "/chat/stream",
                json={
                    "query": "what did I note about Wonderland characters",
                    "document_ids": [],
                    "scope": "all",
                },
                headers={"Accept": "text/event-stream"},
            )

        assert resp.status_code == 200
        assert len(resp.content) > 0


# #141: a notes question that names no subject answers from the most recent notes


@pytest.mark.parametrize(
    ("question", "generic"),
    [
        ("what did I note about my reading", True),
        ("what did I note?", True),
        ("what have I noted recently", True),
        ("what did I note about my reading of Hamlet", False),
        ("what did I note about Alice", False),
        ("in my notes about the White Rabbit", False),
    ],
)
def test_notes_subject_is_generic(question, generic):
    from app.services.intent import notes_subject_is_generic

    assert notes_subject_is_generic(question) is generic


@pytest.fixture
async def notes_db(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.database as db_module
    from app.config import get_settings
    from app.database import make_engine
    from app.db_init import create_all_tables

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield factory
    db_module._engine, db_module._session_factory = orig
    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_notes_node_generic_subject_uses_recent_notes(notes_db):
    from datetime import UTC, datetime, timedelta

    from app.models import NoteModel

    now = datetime.now(UTC)
    async with notes_db() as s:
        for i, text in enumerate(
            ["older note", "The Cheshire Cat can vanish leaving only its grin"]
        ):
            s.add(
                NoteModel(
                    id=f"n{i}",
                    content=text,
                    tags=[],
                    created_at=now,
                    updated_at=now + timedelta(seconds=i),
                )
            )
        await s.commit()

    mock_svc = MagicMock()
    mock_svc.search = AsyncMock(return_value=[])
    state = _make_minimal_state(question="what did I note about my reading")
    with patch("app.services.note_search.get_note_search_service", return_value=mock_svc):
        result = await notes_node(state)

    mock_svc.search.assert_not_called()
    assert result["notes_recent"] is True
    ctx = result["section_context"]
    assert ctx.index("Cheshire Cat") < ctx.index("older note"), "most recent first"


@pytest.mark.asyncio
async def test_notes_node_generic_subject_without_notes_is_not_found(notes_db):
    state = _make_minimal_state(question="what did I note about my reading")
    result = await notes_node(state)
    assert result.get("section_context") is None
    assert not result.get("notes_recent")


@pytest.mark.asyncio
async def test_synthesize_uses_notes_prompt_only_for_recent_notes(notes_db):
    from app.runtime.chat_nodes.synthesize import synthesize_node
    from app.services.qa import NOT_FOUND_SENTINEL, QA_NOTES_RECENT_SYSTEM_PROMPT

    ctx = "[From your notes] The Cheshire Cat can vanish leaving only its grin"
    recent = await synthesize_node(
        _make_minimal_state(
            question="what did I note", intent="notes", section_context=ctx, notes_recent=True
        )
    )
    searched = await synthesize_node(
        _make_minimal_state(
            question="what did I note about Alice", intent="notes", section_context=ctx
        )
    )
    assert recent["_system_prompt"] == QA_NOTES_RECENT_SYSTEM_PROMPT
    assert NOT_FOUND_SENTINEL not in recent["_system_prompt"]
    assert NOT_FOUND_SENTINEL in searched["_system_prompt"]
