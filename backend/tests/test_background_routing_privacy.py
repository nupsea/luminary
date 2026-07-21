"""Automatic tasks must not send user content to a cloud provider.

In hybrid mode `get_effective_routing` sends interactive traffic to the cloud
and background traffic to local Ollama. A background caller that omits
`background=True` silently takes the interactive route -- which is how the note
description backfill came to send every note to OpenAI at startup, visible only
in the traces.

These tests pin the routing contract and the call sites that depend on it.
"""

import ast
import pathlib

import pytest

from app.services import settings_service as ss

# Automatic, non-user-initiated work on private content. Each entry is the
# module and the callee whose invocation must carry background=True.
AUTOMATIC_CALL_SITES = [
    ("app/services/note_description_generator.py", "complete"),
    ("app/services/document_tagger.py", "complete"),
    ("app/workflows/ingestion_nodes/parse.py", "generate"),
    ("app/workflows/concept_nodes/score_concepts.py", "complete"),
]


@pytest.fixture
def hybrid_routing():
    original = dict(ss._cache)
    ss._cache.update(
        {"llm_mode": "hybrid", "cloud_provider": "openai", "cloud_model": "gpt-5-mini"}
    )
    yield
    ss._cache.clear()
    ss._cache.update(original)


def test_hybrid_sends_background_work_to_ollama(hybrid_routing):
    interactive, _ = ss.get_effective_routing(background=False)
    background, _ = ss.get_effective_routing(background=True)

    assert interactive.startswith("openai/")
    assert background.startswith("ollama/"), (
        "background work must stay local in hybrid mode; routing it to the cloud "
        "sends private content off the machine"
    )


@pytest.mark.parametrize(("module_path", "callee"), AUTOMATIC_CALL_SITES)
def test_automatic_call_sites_declare_background(module_path, callee):
    path = pathlib.Path(__file__).resolve().parents[1] / module_path
    tree = ast.parse(path.read_text())

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == callee
    ]
    assert calls, f"no .{callee}() call found in {module_path}"

    for call in calls:
        kwargs = {k.arg for k in call.keywords if k.arg}
        # An explicit model= pins routing directly and is equally acceptable.
        assert "background" in kwargs or "model" in kwargs, (
            f"{module_path}:{call.lineno} calls .{callee}() without background=True; "
            "in hybrid mode this routes user content to the cloud provider"
        )
