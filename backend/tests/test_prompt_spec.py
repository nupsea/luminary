"""A prompt is a contract plus the compensations a model still needs.

Two things these guard. The rendered prompt is a snapshot, so a change to what
a model receives shows up in review instead of arriving with a refactor. And an
accommodation is only dropped on measured evidence — a capability flag is not
evidence about behaviour, which this repo learned the expensive way:
qwen2.5:14b-instruct declares `supports_json_schema` and wrapped every one of 40
flashcard generations in prose.
"""

from dataclasses import replace

import pytest

from app.model_registry import REGISTRY, ModelProfile, profile_for
from app.services.flashcard_prompts import FLASHCARD_USER_SPEC, flashcard_user_tmpl
from app.services.prompt_spec import Accommodation, PromptSpec, describe, render

# The flashcard prompt as every unmeasured model receives it. Update this when
# the prompt is meant to change, never to make a test pass.
FLASHCARD_RENDER = """\
Write {count} {difficulty}-level flashcards from the text below.
Difficulty: {difficulty_guidelines}
{extra_instructions}Return a JSON object:
{{"flashcards": [{{"question": "...", "answer": "...", "source_excerpt": "...", \
"bloom_level": N}}]}}
Use '\\n' for line breaks inside a string.
Example card with a multi-point answer:
{{"flashcards": [{{"question": "How do random hardware faults and systematic software errors \
differ for fault tolerance?", "answer": "They fail differently, so they need different \
defences.\\n- Hardware faults are largely independent -- redundancy masks them.\\n- Software \
errors are correlated and can fail many nodes at once -- they need testing and isolation.", \
"source_excerpt": "", "bloom_level": 4}}]}}
"""


def _unmeasured() -> ModelProfile:
    return next(iter(REGISTRY.values()))


def _measured(needed: tuple[str, ...]) -> ModelProfile:
    return replace(_unmeasured(), accommodations_measured=True, accommodations_needed=needed)


def test_the_rendered_flashcard_prompt_is_what_the_snapshot_says():
    assert render(FLASHCARD_USER_SPEC, _unmeasured()) == FLASHCARD_RENDER


def test_the_shipped_template_is_the_render_plus_its_text_slot():
    """The template callers format is built from the spec, so the two cannot
    drift into disagreeing about what the model is asked for."""
    assert flashcard_user_tmpl().startswith(FLASHCARD_RENDER)
    assert flashcard_user_tmpl().endswith("Text:\n{text}\n\nJSON object:")


def test_an_unmeasured_model_keeps_every_accommodation():
    """Empty `accommodations_needed` means nobody looked. Dropping on that is
    how a working prompt quietly breaks."""
    kept = FLASHCARD_USER_SPEC.for_profile(_unmeasured())
    assert len(kept) == len(FLASHCARD_USER_SPEC.accommodations)


def test_an_unregistered_model_keeps_every_accommodation():
    assert FLASHCARD_USER_SPEC.for_profile(profile_for("ollama/nobody-registered-this")) == (
        FLASHCARD_USER_SPEC.accommodations
    )


def test_a_measured_model_gets_only_what_it_was_measured_to_need():
    kept = FLASHCARD_USER_SPEC.for_profile(_measured(("worked_example",)))

    assert [a.id for a in kept] == ["worked_example"]


def test_a_capability_flag_alone_never_drops_an_accommodation():
    """The measurable mistake: `supports_json_schema` is true for the model that
    needed the format accommodation on every one of 40 generations."""
    schema_capable = replace(_unmeasured(), supports_json_schema=True)

    assert FLASHCARD_USER_SPEC.for_profile(schema_capable) == FLASHCARD_USER_SPEC.accommodations


@pytest.mark.parametrize("accommodation", FLASHCARD_USER_SPEC.accommodations)
def test_every_accommodation_names_a_model_an_observation_and_an_exit(accommodation):
    """An accommodation nobody can justify is dead code, and one with no exit
    condition is permanent — which is the ceiling this refactor exists to lift."""
    assert accommodation.introduced_for.startswith(("ollama/", "openai/", "anthropic/"))
    assert len(accommodation.because) > 20
    assert len(accommodation.drop_when) > 20


def test_describe_reports_what_this_model_gets_and_why():
    rows = describe(FLASHCARD_USER_SPEC, _measured(("worked_example",)))

    applied = {r["id"]: r["applied"] for r in rows}
    assert applied == {"json_escape_hint": "no", "worked_example": "yes"}


def test_a_contract_with_no_accommodations_renders_alone():
    spec = PromptSpec(task="t", contract="Do the thing.")

    assert render(spec, None) == "Do the thing.\n"


def test_accommodation_text_is_appended_in_declaration_order():
    spec = PromptSpec(
        task="t",
        contract="Contract.",
        accommodations=tuple(
            Accommodation(
                id=f"a{i}",
                kind="format",
                text=f"Line {i}.",
                introduced_for="ollama/x",
                because="because this model did the thing it should not have",
                drop_when="when the matrix says it no longer does the thing",
            )
            for i in (1, 2)
        ),
    )

    assert render(spec, None) == "Contract.\nLine 1.\nLine 2.\n"


# Every spec in the tree (P4)


def _all_specs() -> dict[str, PromptSpec]:
    import importlib.util
    from pathlib import Path

    dump = Path(__file__).resolve().parent.parent.parent / "scripts" / "prompt_dump.py"
    spec = importlib.util.spec_from_file_location("prompt_dump", dump)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SPECS


def _defined_specs() -> set[str]:
    """Modules that construct a PromptSpec, by grep rather than import."""
    from pathlib import Path

    services = Path(__file__).resolve().parent.parent / "app" / "services"
    return {
        path.name
        for path in services.glob("*.py")
        if "PromptSpec(" in path.read_text() and path.name != "prompt_spec.py"
    }


def test_every_prompt_spec_is_dumpable():
    """A spec that `make prompt-dump` cannot print is a prompt that exists only
    at runtime -- the cost this refactor pays back, unpaid."""
    dumped = _all_specs()

    assert len(dumped) >= len(_defined_specs()), (
        f"{len(_defined_specs())} modules define a PromptSpec but only "
        f"{len(dumped)} are registered in scripts/prompt_dump.py"
    )


@pytest.mark.parametrize("task", sorted(_all_specs()))
def test_every_registered_spec_renders_and_justifies_itself(task):
    spec = _all_specs()[task]
    rendered = render(spec, _unmeasured())

    assert rendered.strip(), task
    for accommodation in spec.accommodations:
        assert accommodation.text.strip() in rendered, f"{task}: {accommodation.id} missing"
        assert accommodation.introduced_for.startswith(("ollama/", "openai/", "anthropic/"))
        assert len(accommodation.because) > 20, f"{task}: {accommodation.id} has no observation"
        assert len(accommodation.drop_when) > 20, f"{task}: {accommodation.id} has no exit"


def test_the_shared_format_accommodation_is_one_object_not_a_copied_sentence():
    """"No explanation, no preamble, no markdown fences" appeared in five
    prompts. One observation, one accommodation: copying the sentence is what
    made it look like part of each task's contract."""
    from app.services.prompt_spec import NO_FENCES

    users = [t for t, s in _all_specs().items() if NO_FENCES in s.accommodations]

    assert len(users) >= 5, users


# The matrix's two arms (P6). Both are restart-level settings, so what these
# guard is that the switch reaches the render and shows up in `describe` -- an
# arm that silently did nothing would produce a scaffolding-tax measurement of
# zero on every model.


@pytest.fixture
def prompt_settings(monkeypatch):
    import app.config as config_module
    import app.services.prompt_spec as spec_module

    def _apply(**overrides):
        stub = config_module.Settings().model_copy(update=overrides)
        monkeypatch.setattr(spec_module, "get_settings", lambda: stub)
        return stub

    return _apply


def test_the_shipped_arm_is_the_default():
    from app.services.prompt_spec import withheld

    bare, dropped = withheld()

    assert bare is False
    assert dropped == frozenset()


def test_the_bare_arm_renders_the_contract_alone(prompt_settings):
    prompt_settings(PROMPT_ARM="bare")

    rendered = render(FLASHCARD_USER_SPEC, _unmeasured())

    assert rendered.strip() == FLASHCARD_USER_SPEC.contract.strip()
    for accommodation in FLASHCARD_USER_SPEC.accommodations:
        assert accommodation.text.strip() not in rendered


def test_one_accommodation_can_be_withheld_for_the_necessity_check(prompt_settings):
    dropped_id = FLASHCARD_USER_SPEC.accommodations[0].id
    prompt_settings(PROMPT_DROP_ACCOMMODATIONS=dropped_id)

    rendered = render(FLASHCARD_USER_SPEC, _unmeasured())
    reported = {row["id"]: row["applied"] for row in describe(FLASHCARD_USER_SPEC, _unmeasured())}

    assert FLASHCARD_USER_SPEC.accommodations[0].text.strip() not in rendered
    assert reported[dropped_id] == "no"
    for accommodation in FLASHCARD_USER_SPEC.accommodations[1:]:
        assert accommodation.text.strip() in rendered
        assert reported[accommodation.id] == "yes"


# A prompt is rendered for the model that will answer (P4 gap, closed 2026-08-16).


def test_a_prompt_is_rendered_for_the_model_that_will_answer(monkeypatch):
    """Rendering against the configured default meant a model chosen in Settings
    answered with another model's accommodations -- and `accommodations_needed`
    on a registry entry would have been read for a model nobody was going to
    call, which is the whole output of the matrix's necessity check."""
    from types import SimpleNamespace

    import app.services.model_router as router_module

    measured = _measured(needed=())
    monkeypatch.setattr(
        router_module,
        "resolve",
        lambda role, background=False: SimpleNamespace(profile=measured, model="ollama/measured"),
    )

    rendered = flashcard_user_tmpl()

    assert rendered.startswith(FLASHCARD_USER_SPEC.contract.rstrip())
    for accommodation in FLASHCARD_USER_SPEC.accommodations:
        assert accommodation.text.strip() not in rendered


def test_nothing_renders_a_prompt_against_the_configured_default():
    """The guard that keeps the hole shut. `profile_for(default_*_model())` asks
    what config defaults to, which is a different question from what will serve
    the call -- and the two disagree the moment a user picks a model."""
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "app"
    pattern = re.compile(r"render\s*\(\s*\w+\s*,\s*profile_for\s*\(\s*default_\w*model\(\)")
    offenders = [
        f"{path.relative_to(app_dir)}:{i}"
        for path in app_dir.rglob("*.py")
        for i, line in enumerate(path.read_text().splitlines(), start=1)
        if pattern.search(line)
    ]

    assert offenders == [], (
        "these render for the configured default instead of the resolved model: "
        f"{offenders}. Use render_for(spec, role)."
    )
