"""A text role answering with a model nobody measured for text is reported.

`residency_report` checked size and nothing else, so a shipped 0.7.5 install had
`ollama/qwen2.5vl:7b` -- the registry's dedicated figure reader -- stored as
`local_chat_model`. Every field in the report read clean: it fits the host, the
set fits the budget, no narrowing, no unmeasured footprint. The only symptom was
that answers got worse, which no report says.

Nothing validates the choice at selection time either: `available_local_models`
is whatever Ollama lists, and `PATCH /settings/llm` takes any id. So the report
is where it has to surface, and it is advisory for the same reason the size
warnings are -- a model chosen by hand is honoured.
"""

import pytest

from app.model_registry import TEXT_PREFERENCE, TEXT_ROLES, is_measured_text_model


def test_the_measured_order_is_text_models_only():
    """The figure reader is in the registry but must not be in this order."""
    assert "ollama/qwen2.5vl:7b" not in TEXT_PREFERENCE
    assert is_measured_text_model("ollama/qwen2.5:14b-instruct")
    assert not is_measured_text_model("ollama/qwen2.5vl:7b")


def test_vision_is_not_a_text_role():
    """A figure reader is the right answer for vision and the wrong one elsewhere."""
    assert "vision" not in TEXT_ROLES
    assert set(TEXT_ROLES) == {"chat", "generation", "background"}


@pytest.fixture()
def report_with(monkeypatch):
    """Build a residency report with the roles resolving to chosen models."""

    def _build(per_role: dict[str, str]):
        import app.services.model_router as router
        from app.model_registry import ROLES

        def fake_resolve(role, *, background=False):
            return router.ModelChoice(
                role, per_role[role], None, router.profile_for(per_role[role]), explicit=True
            )

        monkeypatch.setattr(router, "resolve", fake_resolve)
        monkeypatch.setattr(router, "narrowed_defaults", lambda: {})
        assert set(per_role) == set(ROLES), "every role needs a model"
        return router.residency_report()

    return _build


def test_a_figure_reader_as_the_chat_model_is_reported(report_with):
    """The shipped case, exactly."""
    report = report_with(
        {
            "chat": "ollama/qwen2.5vl:7b",
            "generation": "ollama/qwen2.5vl:7b",
            "background": "ollama/qwen2.5vl:7b",
            "vision": "ollama/qwen2.5vl:7b",
        }
    )
    unranked = report["unranked_text_roles"]
    assert set(unranked) == {"chat", "generation", "background"}, (
        "vision must not be flagged for using a vision model"
    )
    assert unranked["chat"]["model"] == "ollama/qwen2.5vl:7b"
    assert unranked["chat"]["multimodal"] is True


def test_a_measured_text_model_is_not_reported(report_with):
    report = report_with(
        {
            "chat": "ollama/qwen2.5:14b-instruct",
            "generation": "ollama/qwen3.5:4b",
            "background": "ollama/llama3.2",
            "vision": "ollama/qwen2.5vl:7b",
        }
    )
    assert report["unranked_text_roles"] == {}


def test_the_warning_names_the_role_the_model_and_the_alternatives(report_with):
    """A warning nobody can act on is the failure mode the size warnings had."""
    import app.services.model_router as router

    report_with(
        {
            "chat": "ollama/qwen2.5vl:7b",
            "generation": "ollama/qwen2.5:14b-instruct",
            "background": "ollama/qwen2.5:14b-instruct",
            "vision": "ollama/qwen2.5vl:7b",
        }
    )
    warnings = router.warn_if_configuration_exceeds_host()
    hits = [w for w in warnings if "qwen2.5vl" in w and w.startswith("chat")]
    assert len(hits) == 1, f"expected one chat warning, got {warnings}"
    line = hits[0]
    assert "figure reader" in line
    assert "ollama/qwen2.5:14b-instruct" in line, "the warning must name what to use instead"
