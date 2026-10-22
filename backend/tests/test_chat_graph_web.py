"""Unit tests for web_augment_node and version-mismatch prompt extension (S142)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.runtime.chat_graph import _route_after_confidence_gate, synthesize_node, web_augment_node


def _base_state(**overrides) -> dict:
    """Return a minimal ChatState-compatible dict with sensible defaults."""
    state: dict = {
        "question": "What is the recommended way to handle async errors in Python?",
        "doc_ids": [],
        "scope": "all",
        "model": None,
        "intent": "factual",
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
        "primary_strategy": "search_node",
        "conversation_history": [],
        "image_ids": [],
        "web_enabled": False,
        "web_calls_used": 0,
        "web_snippets": [],
    }
    state.update(overrides)
    return state


@pytest.mark.parametrize(
    "web_enabled, confidence, web_calls_used",
    [
        pytest.param(False, "low", 0, id="web_augment_node_skips_when_disabled"),
        pytest.param(True, "medium", 0, id="web_augment_node_skips_on_medium_confidence"),
        pytest.param(True, "high", 0, id="web_augment_node_skips_on_high_confidence"),
        pytest.param(True, "low", 3, id="web_augment_node_rate_limit"),
    ],
)
@pytest.mark.asyncio
async def test_web_augment_node_skips(web_enabled, confidence, web_calls_used):
    state = _base_state(
        web_enabled=web_enabled, confidence=confidence, web_calls_used=web_calls_used
    )
    result = await web_augment_node(state)
    assert result == {}


@pytest.mark.asyncio
async def test_web_augment_node_fires_on_low_confidence():
    """Fires and returns augmented context when web_enabled=True AND confidence=low."""
    from app.types import WebSnippet

    fake_snippet = WebSnippet(
        url="https://docs.python.org/3/library/asyncio.html",
        title="asyncio docs",
        content="Python 3.12 introduced ExceptionGroup for error handling.",
        source_quality="official_docs",
        version_info="Python 3.12",
        domain="docs.python.org",
    )

    state = _base_state(
        web_enabled=True,
        confidence="low",
        web_calls_used=0,
        section_context="Local content about Python 3.9 asyncio.",
    )

    mock_searcher = AsyncMock()
    mock_searcher.search.return_value = [fake_snippet]

    # web_augment_node uses a local import, so we patch at the source module
    with patch("app.services.web_searcher.get_web_searcher", return_value=mock_searcher):
        result = await web_augment_node(state)

    assert result.get("web_calls_used") == 1
    assert result.get("retry_attempted") is True
    assert len(result.get("web_snippets", [])) == 1
    assert result["web_snippets"][0]["domain"] == "docs.python.org"
    assert "section_context" in result
    assert "[Web: docs.python.org]" in result["section_context"]


@pytest.mark.asyncio
async def test_web_augment_node_accumulates_web_calls():
    """web_calls_used increments correctly across multiple calls."""
    from app.types import WebSnippet

    fake_snippet = WebSnippet(
        url="https://example.com/",
        title="Example",
        content="Some content.",
        source_quality="unknown",
        version_info="",
        domain="example.com",
    )

    state1 = _base_state(web_enabled=True, confidence="low", web_calls_used=0)
    state2 = _base_state(web_enabled=True, confidence="low", web_calls_used=1)
    state3 = _base_state(web_enabled=True, confidence="low", web_calls_used=2)
    state4 = _base_state(web_enabled=True, confidence="low", web_calls_used=3)

    mock_searcher = AsyncMock()
    mock_searcher.search.return_value = [fake_snippet]

    # web_augment_node uses a local import, so we patch at the source module
    with patch("app.services.web_searcher.get_web_searcher", return_value=mock_searcher):
        r1 = await web_augment_node(state1)
        r2 = await web_augment_node(state2)
        r3 = await web_augment_node(state3)
        r4 = await web_augment_node(state4)  # at rate limit -- should be no-op

    assert r1.get("web_calls_used") == 1
    assert r2.get("web_calls_used") == 2
    assert r3.get("web_calls_used") == 3
    assert r4 == {}  # rate-limited


@pytest.mark.parametrize(
    "web_enabled, web_calls_used, expected",
    [
        pytest.param(
            True,
            0,
            "web_augment_node",
            id="route_after_confidence_gate_routes_to_web_augment_when_enabled",
        ),
        pytest.param(
            False,
            0,
            "augment_node",
            id="route_after_confidence_gate_routes_to_augment_when_web_disabled",
        ),
        pytest.param(
            True,
            3,
            "augment_node",
            id="route_after_confidence_gate_routes_to_web_augment_respects_rate_limit",
        ),
    ],
)
def test_route_after_confidence_gate(web_enabled, web_calls_used, expected):
    state = _base_state(
        web_enabled=web_enabled,
        confidence="low",
        web_calls_used=web_calls_used,
        retry_attempted=False,
    )
    route = _route_after_confidence_gate(state)
    assert route == expected


def test_route_after_confidence_gate_routes_to_end_after_retry():
    """Routes to END when retry_attempted=True regardless of confidence."""
    from langgraph.graph import END

    state = _base_state(web_enabled=True, confidence="low", web_calls_used=0, retry_attempted=True)
    route = _route_after_confidence_gate(state)
    assert route == END


# Version mismatch prompt extension in synthesize_node


@pytest.mark.asyncio
async def test_version_mismatch_prompt_extension_fires_when_web_snippets_present():
    """synthesize_node adds version_mismatch instruction when web_snippets have version_info."""
    state = _base_state(
        chunks=[
            {
                "chunk_id": "c1",
                "document_id": "doc1",
                "text": "Python 3.9 introduced asyncio improvements.",
                "section_heading": "Asyncio",
                "page": 42,
                "score": 0.9,
                "source": "vector",
            }
        ],
        section_context=None,
        web_snippets=[
            {
                "url": "https://docs.python.org/3.12/library/asyncio.html",
                "title": "asyncio Python 3.12",
                "content": "Python 3.12 improved exception handling in asyncio.",
                "source_quality": "official_docs",
                "version_info": "Python 3.12",
                "domain": "docs.python.org",
            }
        ],
    )

    # Patch pack_context and DB calls so synthesize_node can run without real DB
    with (
        patch(
            "app.runtime.chat_nodes.synthesize._fetch_doc_titles_for_chunks",
            new_callable=AsyncMock,
            return_value={"doc1": "Python in Practice"},
        ),
        patch(
            "app.runtime.chat_nodes.synthesize._fetch_contradiction_context",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "app.services.context_packer.pack_context",
            return_value="[Asyncio p.42]\nPython 3.9 introduced asyncio improvements.",
        ),
    ):
        result = await synthesize_node(state)

    assert result.get("_system_prompt") is not None
    system_prompt = result["_system_prompt"]
    assert "version_mismatch" in system_prompt, (
        f"Expected 'version_mismatch' in system_prompt but got: {system_prompt[:200]}"
    )


@pytest.mark.asyncio
async def test_version_mismatch_prompt_not_added_when_no_web_snippets():
    """synthesize_node does NOT add version_mismatch instruction when no web_snippets."""
    state = _base_state(
        chunks=[
            {
                "chunk_id": "c1",
                "document_id": "doc1",
                "text": "Python 3.9 introduced asyncio improvements.",
                "section_heading": "Asyncio",
                "page": 42,
                "score": 0.9,
                "source": "vector",
            }
        ],
        section_context=None,
        web_snippets=[],  # no web snippets
    )

    with (
        patch(
            "app.runtime.chat_nodes.synthesize._fetch_doc_titles_for_chunks",
            new_callable=AsyncMock,
            return_value={"doc1": "Python in Practice"},
        ),
        patch(
            "app.runtime.chat_nodes.synthesize._fetch_contradiction_context",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "app.services.context_packer.pack_context",
            return_value="[Asyncio p.42]\nPython 3.9 introduced asyncio improvements.",
        ),
    ):
        result = await synthesize_node(state)

    assert result.get("_system_prompt") is not None
    system_prompt = result["_system_prompt"]
    assert "version_mismatch" not in system_prompt
