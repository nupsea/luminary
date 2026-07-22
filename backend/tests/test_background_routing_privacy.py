"""Work on the user's own content must not reach a cloud provider.

In hybrid mode `get_effective_routing` sends interactive traffic to the cloud
and everything flagged `background=True` to local Ollama. A caller that omits
the flag silently takes the interactive route -- which is how the note
description backfill came to send every note to OpenAI at startup, visible only
in the traces.

The policy is local-by-default: notes and documents are personal, so a call site
handling them stays on the machine even when a click triggered it. Cloud routing
is reserved for the surfaces where reaching for a bigger model is the point of
hybrid mode (chat, explain, feynman, study, flashcard generation).

These tests pin the routing contract and the call sites that depend on it.
"""

import ast
import pathlib

import pytest

from app.services import settings_service as ss

# Call sites that must never leave the machine, as (module, callee). Two groups:
# automatic tasks that run without the user asking, and user-triggered helpers
# that nonetheless process the user's own notes or documents.
LOCAL_ONLY_CALL_SITES = [
    # Automatic
    ("app/services/note_description_generator.py", "complete"),
    ("app/services/document_tagger.py", "complete"),
    ("app/workflows/ingestion_nodes/parse.py", "generate"),
    ("app/workflows/concept_nodes/score_concepts.py", "complete"),
    # User-triggered, but operating on the user's own notes / documents
    ("app/services/note_tagger.py", "complete"),
    ("app/services/note_title_generator.py", "complete"),
    ("app/services/clustering_service.py", "complete"),
    ("app/services/gap_detector.py", "complete"),
    ("app/services/suggestion_service.py", "complete"),
    ("app/services/topic_service.py", "complete"),
    ("app/services/flashcard_audit.py", "generate"),
]


@pytest.fixture
def hybrid_routing():
    """Hybrid mode with a stub cloud key.

    The key must be present or the interactive branch raises before it can
    return a model string -- and CI has no real key configured.
    """
    original = dict(ss._cache)
    ss._cache.update(
        {
            "llm_mode": "hybrid",
            "cloud_provider": "openai",
            "cloud_model": "gpt-5-mini",
            "openai_api_key": "sk-test-not-a-real-key",
        }
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


@pytest.mark.parametrize(("module_path", "callee"), LOCAL_ONLY_CALL_SITES)
def test_local_only_call_sites_declare_background(module_path, callee):
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
