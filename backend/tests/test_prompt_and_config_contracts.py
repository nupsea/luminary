"""Prompt, request-schema and config contracts that need no running server.

These ran as smoke scripts S69-S73, importing `app.` in-process;
they belong in the suite that gates every push, not under the wire contract.
"""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

APP = Path(__file__).resolve().parent.parent / "app"


def test_qa_prompt_asks_for_markdown():
    from app.services.qa import QA_SYSTEM_PROMPT

    assert "Markdown" in QA_SYSTEM_PROMPT


def test_ingestion_inserts_chunks_in_batches():
    # A per-row session.add() per chunk is what this guards against.
    paths = [
        APP / "workflows/ingestion.py",
        *sorted((APP / "workflows/ingestion_nodes").glob("*.py")),
    ]
    add_all_calls = sum(
        1
        for path in paths
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_all"
    )
    assert add_all_calls >= 4, f"{add_all_calls} add_all calls across the ingestion pipeline"


def test_summarize_requests_take_force_refresh_and_the_current_modes():
    from app.routers.summarize import LibrarySummarizeRequest, SummarizeRequest

    assert SummarizeRequest(mode="executive", force_refresh=True).force_refresh is True
    assert LibrarySummarizeRequest(mode="executive", force_refresh=True).force_refresh is True
    for mode in ("one_sentence", "executive", "detailed", "conversation"):
        assert SummarizeRequest(mode=mode).mode == mode
    # glossary was removed with /explain/glossary/*.
    with pytest.raises(ValidationError):
        SummarizeRequest(mode="glossary")


def test_flashcard_prompt_states_shape_and_names_no_taxonomy():
    from app.services.flashcard import FLASHCARD_SYSTEM

    for word in ("fact", "explain", "use", "relate", "limit", "build"):
        assert word in FLASHCARD_SYSTEM, f"missing depth word {word!r}"
    assert "AVOID" in FLASHCARD_SYSTEM
    assert "SOURCE_EXCERPT" in FLASHCARD_SYSTEM
    lowered = FLASHCARD_SYSTEM.lower()
    for term in ("bloom", "taxonomy", "comprehension", "application", "synthesis"):
        assert term not in lowered, f"I-28: taxonomy term {term!r} is in FLASHCARD_SYSTEM"
