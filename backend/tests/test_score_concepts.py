"""score_concepts -- the LLM studyability gate (relevance lever 2).

Verifies it demotes the model's rejects to "candidate", leaves the rest "proposed", parses a
messy reply defensively, and fails OPEN (a model error never empties the library).
"""

import pytest

from app.workflows.concept_nodes.score_concepts import _parse_rejects, score_concepts


def _state(labels):
    return {"hierarchy": {"concepts": [{"label": ln, "sun": ln} for ln in labels]}}


class _FakeLLM:
    def __init__(self, reply):
        self._reply = reply
        self.calls = 0

    async def complete(self, messages, **kw):
        self.calls += 1
        return self._reply


@pytest.fixture
def labels():
    return ["iceberg tables", "servers", "oauth token", "example code"]


async def test_flags_rejected_concepts(monkeypatch, labels):
    fake = _FakeLLM("[2,4]")  # reject "servers" and "example code"
    monkeypatch.setattr(
        "app.workflows.concept_nodes.score_concepts.get_llm_service", lambda: fake
    )
    state = _state(labels)
    out = await score_concepts(state)
    statuses = {c["label"]: c.get("status", "proposed") for c in out["hierarchy"]["concepts"]}
    assert statuses["servers"] == "candidate"
    assert statuses["example code"] == "candidate"
    assert statuses["iceberg tables"] == "proposed"
    assert statuses["oauth token"] == "proposed"
    assert out["diagnostics"]["score_concepts"]["flagged"] == 2


async def test_fails_open_on_llm_error(monkeypatch, labels):
    class _Boom:
        async def complete(self, messages, **kw):
            raise RuntimeError("model down")

    monkeypatch.setattr(
        "app.workflows.concept_nodes.score_concepts.get_llm_service", lambda: _Boom()
    )
    out = await score_concepts(_state(labels))
    assert all(c.get("status", "proposed") == "proposed" for c in out["hierarchy"]["concepts"])
    assert out["diagnostics"]["score_concepts"]["flagged"] == 0


@pytest.mark.parametrize(
    "raw,n,expected",
    [
        ("[1,3]", 3, {0, 2}),
        ("reject these: [2]  ", 3, {1}),
        ("[]", 3, set()),
        ("garbage", 3, set()),
        ("[5,1]", 3, {0}),  # out-of-range 5 ignored
    ],
)
def test_parse_rejects(raw, n, expected):
    assert _parse_rejects(raw, n) == expected
