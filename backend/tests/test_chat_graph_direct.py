"""Unit tests for direct model chat routing (Issue #79)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.runtime.chat_graph import build_chat_graph, classify_node, route_node
from app.runtime.chat_nodes.direct import direct_node
from app.services.qa import (
    QA_CREATIVE_TEMPERATURE,
    QA_DIRECT_SYSTEM_PROMPT,
    get_qa_service,
)


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
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


def _make_direct_state(question: str, history: list[dict] | None = None) -> dict:
    return {
        "question": question,
        "doc_ids": [],
        "scope": "all",
        "model": None,
        "direct": True,
        "intent": None,
        "rewritten_question": None,
        "chunks": [],
        "section_context": None,
        "retrieval_failed": False,
        "answer": "",
        "citations": [],
        "confidence": "low",
        "not_found": False,
        "_llm_prompt": None,
        "_system_prompt": None,
        "_passages_sent": None,
        "_context_chars": None,
        "_context_budget": None,
        "_budget_reason": None,
        "conversation_history": history or [],
        "retry_attempted": False,
        "primary_strategy": None,
        "image_ids": [],
        "web_enabled": False,
        "web_calls_used": 0,
        "web_snippets": [],
        "source_citations": [],
        "cited_chunks": [],
        "transparency": None,
        "transparency_augmented": False,
    }


@pytest.mark.asyncio
async def test_classify_node_bypasses_retrieval_when_direct():
    state = _make_direct_state("what is a mutex vs semaphore?")
    res = await classify_node(state)
    assert res["intent"] == "direct"
    assert res["primary_strategy"] == "direct_node"
    assert route_node({**state, **res}) == "direct_node"


@pytest.mark.asyncio
async def test_direct_node_formats_prompt_and_clears_context():
    state = _make_direct_state("give me a python regex for email")
    res = await direct_node(state)
    assert res["_llm_prompt"] == "give me a python regex for email"
    assert res["chunks"] == []
    assert res["citations"] == []
    assert res["source_citations"] == []
    assert res["cited_chunks"] == []
    assert res["not_found"] is False
    assert res["transparency"] is None


@pytest.mark.asyncio
async def test_direct_node_preserves_sliding_history():
    history = [
        {"role": "user", "content": "What is Python?"},
        {"role": "assistant", "content": "A high-level programming language."},
    ]
    state = _make_direct_state("How do I install packages?", history=history)
    res = await direct_node(state)
    assert "Prior conversation (most recent last):" in res["_llm_prompt"]
    assert "User: What is Python?" in res["_llm_prompt"]
    assert "Question: How do I install packages?" in res["_llm_prompt"]


@pytest.mark.asyncio
async def test_graph_ainvoke_direct_mode(test_db):
    graph = build_chat_graph().compile()
    state = _make_direct_state("explain recursion")
    result = await graph.ainvoke(state)
    assert result["intent"] == "direct"
    assert result["_llm_prompt"] == "explain recursion"
    assert result["chunks"] == []
    assert result["citations"] == []


@pytest.mark.asyncio
async def test_stream_answer_direct_emits_no_citations_and_direct_flag(test_db):
    tokens = ["A ", "mutex ", "is ", "locking."]

    async def mock_token_gen():
        for t in tokens:
            yield t

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=mock_token_gen())

    svc = get_qa_service()
    with patch("app.services.qa.get_llm_service", return_value=mock_llm):
        events = [
            e
            async for e in svc.stream_answer(
                "mutex vs semaphore", [], "all", None, direct=True
            )
        ]

    done_event_raw = next(e for e in events if '"done": true' in e.lower())
    done_payload = json.loads(done_event_raw.replace("data: ", "").strip())

    assert done_payload.get("direct") is True
    assert done_payload.get("citations") == []
    assert done_payload.get("source_citations") == []
    assert not done_payload.get("not_found")
    assert done_payload["receipt"]["passages_sent"] == 0
    assert done_payload["receipt"]["context_chars"] == 0
    assert done_payload["receipt"]["context_budget_reason"] == "direct"

    # Check LLM call received QA_DIRECT_SYSTEM_PROMPT
    mock_llm.generate.assert_called_once()
    call_kwargs = mock_llm.generate.call_args.kwargs
    assert call_kwargs["system"] == QA_DIRECT_SYSTEM_PROMPT
    assert call_kwargs["temperature"] is None


@pytest.mark.asyncio
async def test_stream_answer_direct_composes_with_creative(test_db):
    async def mock_token_gen():
        yield "Creative direct prose"

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=mock_token_gen())

    svc = get_qa_service()
    with patch("app.services.qa.get_llm_service", return_value=mock_llm):
        _ = [
            e
            async for e in svc.stream_answer(
                "tell a funny story about code",
                [],
                "all",
                None,
                direct=True,
                creative=True,
            )
        ]

    # Explicit precedence rule: Direct chooses prompt, Creative contributes temperature
    mock_llm.generate.assert_called_once()
    call_kwargs = mock_llm.generate.call_args.kwargs
    assert call_kwargs["system"] == QA_DIRECT_SYSTEM_PROMPT
    assert call_kwargs["temperature"] == QA_CREATIVE_TEMPERATURE
